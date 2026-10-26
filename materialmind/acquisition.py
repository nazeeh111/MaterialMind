"""Candidate-visible acquisition policies and a reveal-only retrospective oracle."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable
from types import MappingProxyType

import numpy as np
from scipy.spatial.distance import cdist
from scipy.special import ndtr
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, RBF

from .learning import StabilityModel, predict


@dataclass(frozen=True)
class AcquisitionWeights:
    exploration: float = .15
    diversity: float = .15
    cost_exponent: float = .5

    def to_dict(self) -> dict:
        return asdict(self)


class RetrospectiveOracle:
    """Reference-label boundary. Selection code receives no label dictionary.

    This is an auditable software interface, not cryptographic label hiding.
    Ground truth lives locally because this is a retrospective study.
    """
    def __init__(self, labels: dict[str, float], allowed_ids: Iterable[str]):
        self.__labels = MappingProxyType(dict(labels))
        self.allowed_ids = frozenset(allowed_ids)
        self.revealed: dict[str, float] = {}

    def reveal(self, ids: list[str]) -> dict[str, float]:
        if len(ids) != len(set(ids)):
            raise ValueError("Repeated IDs in oracle request")
        if any(i not in self.allowed_ids for i in ids):
            raise ValueError("Oracle request outside the selected partition")
        if any(i in self.revealed for i in ids):
            raise ValueError("A candidate can only be evaluated once")
        selected = {i: float(self.__labels[i]) for i in ids}
        if not np.isfinite(list(selected.values())).all():
            raise ValueError("Reference labels must be finite")
        self.revealed.update(selected)
        return selected


def novelty(model: StabilityModel, candidates: list[dict], known: list[dict]) -> np.ndarray:
    z = model.latent(candidates)
    # A few outlying embedding coordinates should not dominate diversity.
    z = np.clip(z, -10, 10)
    if not known:
        return np.ones(len(candidates))
    nearest = cdist(z, np.clip(model.latent(known), -10, 10)).min(axis=1)
    return np.clip(nearest / np.sqrt(z.shape[1]), 0, 2)


def acquisition_scores(model: StabilityModel, records: list[dict], known: list[dict],
                       weights: AcquisitionWeights = AcquisitionWeights(),
                       calibrated: bool = True) -> tuple[np.ndarray, dict]:
    """Expected stability, error-scale exploration, diversity, and relative cost.

    Coefficients are fitted on development rollouts. Cost is a stated n-site
    proxy; it is not measured DFT wall-clock time or monetary cost.
    """
    a = model.arrays(records, calibrated)
    nov = novelty(model, records, known)
    relative_cost = np.asarray([r["cost"] for r in records]) / model.cost_scale
    score = combine_acquisition(a["probability"], a["width"], nov, relative_cost, weights)
    exploration = np.clip(a["width"] / .2, 0, 2)
    return score, {"probability": a["probability"], "novelty": nov,
                   "exploration": exploration, "relative_cost": relative_cost}


def combine_acquisition(probability: np.ndarray, width: np.ndarray, novelty_values: np.ndarray,
                        relative_cost: np.ndarray, weights: AcquisitionWeights) -> np.ndarray:
    """Shared arithmetic for the API and cached, label-blind batch selection."""
    exploration = np.clip(width / .2, 0, 2)
    return (probability + weights.exploration * exploration
            + weights.diversity * novelty_values) / relative_cost ** weights.cost_exponent


def rank_candidates(model: StabilityModel, records: list[dict], observed_records: list[dict],
                    policy: dict | AcquisitionWeights | None = None) -> list[dict]:
    """Return the same score decomposition used by the retrospective study."""
    if not records:
        return []
    if isinstance(policy, dict):
        weights = AcquisitionWeights(**policy.get("weights", policy))
    else:
        weights = policy or AcquisitionWeights()
    scores, components = acquisition_scores(model, records, observed_records, weights)
    predictions = predict(model, records)
    rows = []
    for i, (record, prediction) in enumerate(zip(records, predictions)):
        rows.append({**record, **prediction, "acquisition": float(scores[i]),
                     "novelty": float(components["novelty"][i]),
                     "exploration": float(components["exploration"][i]),
                     "relative_cost": float(components["relative_cost"][i]),
                     "acquisition_weights": weights.to_dict(),
                     "reason": "Expected stability plus calibrated-error exploration and embedding novelty, divided by relative cost to the fitted exponent."})
    return sorted(rows, key=lambda r: (-r["acquisition"], r["id"]))


def gaussian_ei(model: StabilityModel, records: list[dict], known: list[dict],
                known_labels: dict[str, float], incumbent: float) -> np.ndarray:
    """Numerically stable log expected improvement with a CHGNet prior mean.

    Every known training label enters this fixed-kernel GP. The incumbent is
    taken from revealed candidates in the active pool, not an unrelated training
    chemistry. Hyperparameters and the train-fitted projection remain frozen.
    """
    known = sorted(known, key=lambda r: r["id"])
    x = np.clip(model.latent(known)[:, :8], -10, 10) / 3.
    xp = np.clip(model.latent(records)[:, :8], -10, 10) / 3.
    residual = np.array([known_labels[r["id"]] - r["predicted_hull"] for r in known])
    gp = GaussianProcessRegressor(kernel=ConstantKernel(.05 ** 2) * RBF(1.),
                                  alpha=.05 ** 2, optimizer=None, normalize_y=False)
    gp.fit(x, residual)
    residual_mean, sigma = gp.predict(xp, return_std=True)
    mean = np.array([r["predicted_hull"] for r in records]) + residual_mean
    improvement = incumbent - mean
    sigma = np.maximum(sigma, 1e-10)
    z = improvement / sigma
    # Direct EI underflows for confidently poor candidates and can silently
    # become ID ranking. Log EI preserves order, including its negative tail.
    log_phi = -.5 * z * z - .5 * np.log(2 * np.pi)
    scores = np.empty_like(z)
    ordinary = z >= -8
    scores[ordinary] = np.log(np.maximum(sigma[ordinary] * (
        np.exp(log_phi[ordinary]) + z[ordinary] * ndtr(z[ordinary])), np.finfo(float).tiny))
    tail = z[~ordinary]
    inv2 = 1 / (tail * tail)
    correction = 1 - 3 * inv2 + 15 * inv2 ** 2 - 105 * inv2 ** 3
    scores[~ordinary] = np.log(sigma[~ordinary]) + log_phi[~ordinary] - 2 * np.log(-tail) + np.log(correction)
    if not np.isfinite(scores).all():
        raise ValueError("Non-finite GP log expected improvement")
    return scores
