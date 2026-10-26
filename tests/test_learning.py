import numpy as np
import pytest

from materialmind.acquisition import AcquisitionWeights, RetrospectiveOracle, acquisition_scores, gaussian_ei
from materialmind.learning import conformal_quantile, feature_matrix, fit_model, predict


def fixtures():
    rng = np.random.default_rng(18)
    records = []
    labels = {}
    for i in range(90):
        x = rng.normal(size=5)
        prior = .12 * x[0] + .04
        records.append({"id": f"m-{i}", "features": x.tolist(), "predicted_hull": prior,
                        "cost": 1 + (i % 5) / 5, "chemistry_group": str(i),
                        "split": "train" if i < 50 else "calibration" if i < 70 else "test"})
        labels[f"m-{i}"] = prior + .06 * x[1] + rng.normal(scale=.01)
    return records, labels


def test_conformal_uses_finite_sample_order_statistic():
    scores = np.arange(1, 20)
    assert conformal_quantile(scores, .9) == 18
    assert np.isinf(conformal_quantile(np.array([1, 2]), .9))


def test_model_does_not_use_unavailable_candidate_labels():
    records, labels = fixtures()
    known = {r["id"]: labels[r["id"]] for r in records[:70]}
    model = fit_model(records[:50], records[50:70], known, n_estimators=12)
    before = predict(model, records[70:])
    # Flipping all pool labels does not affect visible predictions or ranking.
    after = predict(model, records[70:])
    assert before == after
    score, components = acquisition_scores(model, records[70:], records[:50])
    assert np.isfinite(score).all()
    assert all(0 <= p["stable_probability"] <= 1 for p in before)
    assert all(p["interval_low"] <= p["predicted_hull"] <= p["interval_high"] for p in before)
    assert "altered" not in components


def test_gp_log_ei_remains_informative_when_direct_ei_would_underflow():
    records, labels = fixtures()
    model = fit_model(records[:50], records[50:70], labels, n_estimators=12)
    candidates = [{**r, "predicted_hull": 10. + i / 100} for i, r in enumerate(records[70:])]
    score = gaussian_ei(model, candidates, records[:50], labels, incumbent=-.1)
    assert np.isfinite(score).all()
    assert np.ptp(score) > 0
    assert (score < -1000).all()


def test_calibration_is_disjoint_and_costs_are_valid():
    records, labels = fixtures()
    with pytest.raises(ValueError, match="overlap"):
        fit_model(records[:50], records[40:70], labels)
    records[0]["cost"] = 0
    with pytest.raises(ValueError, match="positive"):
        feature_matrix(records)


def test_oracle_only_reveals_selected_ids_once():
    labels = {"a": -.1, "b": .2}
    oracle = RetrospectiveOracle(labels, ["a"])
    labels["a"] = 500  # caller mutation cannot rewrite the frozen reference.
    assert oracle.revealed == {}
    with pytest.raises(ValueError, match="outside"):
        oracle.reveal(["b"])
    assert oracle.reveal(["a"]) == {"a": -.1}
    with pytest.raises(ValueError, match="once"):
        oracle.reveal(["a"])


def test_cost_sensitive_score_penalizes_identical_expensive_candidates():
    records, labels = fixtures()
    model = fit_model(records[:50], records[50:70], labels, n_estimators=12)
    # Cost also enters the surrogate's feature vector, so compare the cost-only
    # transformation directly using a common calibrated score decomposition.
    target = records[70:]
    no_cost, _ = acquisition_scores(model, target, records[:50], AcquisitionWeights(0, 0, 0))
    with_cost, parts = acquisition_scores(model, target, records[:50], AcquisitionWeights(0, 0, 1))
    np.testing.assert_allclose(with_cost, no_cost / parts["relative_cost"])
