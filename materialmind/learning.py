"""Residual adaptation and held-out uncertainty calibration for crystal stability.

All energies are signed distances to a fixed DFT composition hull, in eV/atom.
An interval crossing zero is uncertainty, not evidence of physical synthesis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.special import ndtr
from sklearn.decomposition import PCA
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.preprocessing import StandardScaler


def feature_matrix(records: Sequence[dict]) -> np.ndarray:
    """Only candidate-visible features enter this function, never oracle labels."""
    if not records:
        raise ValueError("At least one candidate is required")
    x = np.asarray([r["features"] for r in records], dtype=float)
    p = np.asarray([r["predicted_hull"] for r in records], dtype=float)
    c = np.asarray([r["cost"] for r in records], dtype=float)
    if x.ndim != 2 or not np.isfinite(x).all() or not np.isfinite(p).all():
        raise ValueError("Features and prior energies must be finite, fixed-width arrays")
    if not np.isfinite(c).all() or np.any(c <= 0):
        raise ValueError("Evaluation cost proxies must be positive and finite")
    return np.column_stack([x, p, np.log(c)])


def conformal_quantile(scores: np.ndarray, coverage: float = .9) -> float:
    """Finite-sample split-conformal order statistic (infinite if unavailable)."""
    values = np.asarray(scores, dtype=float)
    if not 0 < coverage < 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("Calibration needs finite scores and coverage between zero and one")
    k = int(np.ceil((len(values) + 1) * coverage))
    return float(np.partition(values, k - 1)[k - 1]) if k <= len(values) else float("inf")


@dataclass
class StabilityModel:
    """An adapted CHGNet prior with a separately held-out calibration residual set."""

    estimator: ExtraTreesRegressor
    scaler: StandardScaler
    projector: PCA
    calibration_z: np.ndarray
    quantile90: float
    cost_scale: float
    train_ids: tuple[str, ...]
    calibration_ids: tuple[str, ...]
    seed: int

    def latent(self, records: Sequence[dict]) -> np.ndarray:
        return self.projector.transform(self.scaler.transform(feature_matrix(records)))

    def energy(self, records: Sequence[dict]) -> tuple[np.ndarray, np.ndarray]:
        x = feature_matrix(records)
        members = np.asarray([tree.predict(x) for tree in self.estimator.estimators_])
        mean = np.asarray([r["predicted_hull"] for r in records]) + members.mean(axis=0)
        # Ensemble disagreement is not a physical error bar. Calibration supplies
        # the empirical error scale. A floor avoids zero-width intervals.
        sigma = np.sqrt(members.var(axis=0) + .01 ** 2)
        return mean, sigma

    def arrays(self, records: Sequence[dict], calibrated: bool = True) -> dict[str, np.ndarray]:
        mean, sigma = self.energy(records)
        if calibrated:
            z = np.sort(self.calibration_z)
            probability = (np.searchsorted(z, -mean / sigma, side="right") + .5) / (len(z) + 1)
            width = sigma * self.quantile90
        else:
            probability = ndtr(-mean / sigma)
            width = sigma * 1.6448536269514722
        return {"mean": mean, "sigma": sigma, "width": width, "probability": probability}


def fit_model(train: list[dict], calibration: list[dict], oracle: dict[str, float],
              seed: int = 0, n_estimators: int = 40) -> StabilityModel:
    """Fit from explicitly known training labels; reserve calibration labels.

    The caller supplies only labels legitimately available at that stage. For
    active learning, append already-revealed candidates to ``train``. Calibration
    candidates never enter surrogate training or acquisition pools.
    """
    if len(train) < 8 or len(calibration) < 10:
        raise ValueError("Need at least 8 training and 10 calibration candidates")
    train_ids = tuple(r["id"] for r in train)
    calibration_ids = tuple(r["id"] for r in calibration)
    if len(set(train_ids)) != len(train_ids) or len(set(calibration_ids)) != len(calibration_ids):
        raise ValueError("Duplicate candidate IDs")
    if set(train_ids) & set(calibration_ids):
        raise ValueError("Training and calibration partitions overlap")
    x = feature_matrix(train)
    y = np.asarray([oracle[r["id"]] - r["predicted_hull"] for r in train])
    if not np.isfinite(y).all():
        raise ValueError("Training labels must be finite")
    estimator = ExtraTreesRegressor(n_estimators=n_estimators, min_samples_leaf=3,
                                   max_features=.8, random_state=seed, n_jobs=1)
    estimator.fit(x, y)
    scaler = StandardScaler().fit(x)
    projector = PCA(n_components=min(12, x.shape[1], len(train) - 1),
                    svd_solver="full").fit(scaler.transform(x))
    model = StabilityModel(estimator, scaler, projector, np.empty(0), 1.,
                           float(np.median([r["cost"] for r in train])),
                           train_ids, calibration_ids, seed)
    mean, sigma = model.energy(calibration)
    labels = np.asarray([oracle[r["id"]] for r in calibration], dtype=float)
    if not np.isfinite(labels).all():
        raise ValueError("Calibration labels must be finite")
    model.calibration_z = (labels - mean) / sigma
    model.quantile90 = conformal_quantile(np.abs(model.calibration_z), .9)
    return model


def predict(model: StabilityModel, records: list[dict]) -> list[dict]:
    if not records:
        return []
    a = model.arrays(records)
    return [{"id": r["id"], "predicted_hull": float(a["mean"][i]),
             "pretrained_hull": float(r["predicted_hull"]),
             "uncertainty": float(a["sigma"][i]),
             "interval_low": float(a["mean"][i] - a["width"][i]),
             "interval_high": float(a["mean"][i] + a["width"][i]),
             "stable_probability": float(a["probability"][i]),
             "evidence": "adapted CHGNet prior; held-out empirical calibration; no new DFT"}
            for i, r in enumerate(records)]


def calibration_metrics(model: StabilityModel, records: list[dict], labels: np.ndarray,
                        calibrated: bool = True) -> dict:
    a = model.arrays(records, calibrated)
    truth = np.asarray(labels) <= 0
    p = a["probability"]
    bins = []
    ece = 0.
    for lower, upper in zip(np.linspace(0, 1, 11)[:-1], np.linspace(0, 1, 11)[1:]):
        mask = (p >= lower) & ((p <= upper) if upper == 1 else (p < upper))
        if mask.any():
            confidence, fraction = float(p[mask].mean()), float(truth[mask].mean())
            count = int(mask.sum())
            ece += count / len(p) * abs(confidence - fraction)
            bins.append({"probability": confidence, "stable_fraction": fraction, "n": count})
    covered = np.abs(a["mean"] - labels) <= a["width"]
    # Cluster bootstrap by the held-out chemical system, conditional on this
    # fitted model/calibration set. Structures within a chemistry need not be
    # independent. These intervals still do not imply population-level validity.
    groups, inverse = np.unique([r["chemistry_group"] for r in records], return_inverse=True)
    counts = np.bincount(inverse)
    rng = np.random.default_rng(42)
    sampled = rng.integers(0, len(groups), size=(2000, len(groups)))
    totals = counts[sampled].sum(axis=1)
    intervals = {}
    for name, values in (("mae_ev_atom", np.abs(a["mean"] - labels)),
                         ("brier", (p - truth) ** 2), ("coverage90", covered.astype(float))):
        sums = np.bincount(inverse, weights=values)
        bootstrap = sums[sampled].sum(axis=1) / totals
        intervals[name] = [float(x) for x in np.quantile(bootstrap, [.025, .975])]
    return {"mae_ev_atom": float(np.mean(np.abs(a["mean"] - labels))),
            "rmse_ev_atom": float(np.sqrt(np.mean((a["mean"] - labels) ** 2))),
            "brier": float(np.mean((p - truth) ** 2)), "ece": float(ece),
            "coverage90": float(np.mean(covered)), "ci95": intervals,
            "ci_scope": "Chemical-system cluster bootstrap within this fixed test pool, conditional on fitted model and calibration set.",
            "mean_interval_width_ev_atom": float(np.mean(2 * a["width"])),
            "bins": bins}
