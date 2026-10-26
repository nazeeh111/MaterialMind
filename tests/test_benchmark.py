import numpy as np
import pytest

from materialmind.acquisition import AcquisitionWeights, RetrospectiveOracle, acquisition_scores
from materialmind.benchmark import bootstrap_mean_ci, run_episode, validate_partitions
from materialmind.learning import fit_model


def sample():
    rng = np.random.default_rng(67)
    records, labels = [], {}
    for i in range(120):
        split = "train" if i < 45 else "calibration" if i < 65 else "development" if i < 85 else "test"
        x = rng.normal(size=4)
        r = {"id": str(i), "features": x.tolist(), "predicted_hull": .1 * x[0],
             "cost": 1. + (i % 3) / 4, "chemistry_group": str(i), "split": split}
        records.append(r)
        labels[str(i)] = .1 * x[0] + .03 * x[1]
    return records, labels


def test_group_leakage_rejected():
    records, labels = sample()
    assert len(validate_partitions(records, labels)["test"]) == 35
    records[-1]["chemistry_group"] = records[0]["chemistry_group"]
    with pytest.raises(ValueError, match="leakage"):
        validate_partitions(records, labels)


def test_shared_initialization_and_no_double_evaluation():
    records, labels = sample()
    partitions = validate_partitions(records, labels)
    train, cal, test = [partitions[k] for k in ("train", "calibration", "test")]
    known = {r["id"]: labels[r["id"]] for r in train + cal}
    traces = []
    for method in ("random", "materialmind"):
        oracle = RetrospectiveOracle(labels, [r["id"] for r in test])
        episode = run_episode(train, cal, test, known, oracle, method,
                              AcquisitionWeights(), seed=13, budget=10)
        ids = [r["id"] for r in episode["history"]]
        assert len(ids) == len(set(ids))
        assert set(ids) == set(oracle.revealed)
        assert len(ids) >= 10
        traces.append(ids)
    assert traces[0][:5] == traces[1][:5]


def test_no_online_update_ablation_keeps_surrogate_frozen():
    records, labels = sample()
    parts = validate_partitions(records, labels)
    known = {r["id"]: labels[r["id"]] for r in parts["train"] + parts["calibration"]}
    episode = run_episode(parts["train"], parts["calibration"], parts["test"], known,
                          RetrospectiveOracle(labels, [r["id"] for r in parts["test"]]),
                          "no_online_update", AcquisitionWeights(), seed=2, budget=10)
    assert episode["model_updates"] == 1
    assert len(episode["history"]) >= 10


def test_cached_batch_matches_direct_sequential_score_recomputation():
    records, labels = sample()
    parts = validate_partitions(records, labels)
    train, cal, pool = [parts[k] for k in ("train", "calibration", "test")]
    known_labels = {r["id"]: labels[r["id"]] for r in train + cal}
    weights = AcquisitionWeights(.2, .2, .5)
    ep = run_episode(train, cal, pool, known_labels,
                     RetrospectiveOracle(labels, [r["id"] for r in pool]),
                     "materialmind", weights, seed=19, budget=10)
    initial_ids = [r["id"] for r in ep["history"][:5]]
    known = train + [r for r in pool if r["id"] in initial_ids]
    # Preserve reveal order, since the ExtraTrees training row order is fixed.
    known = train + [next(r for r in pool if r["id"] == i) for i in initial_ids]
    known_labels.update({i: labels[i] for i in initial_ids})
    model = fit_model(known, cal, known_labels, seed=19)
    remaining = [r for r in pool if r["id"] not in initial_ids]
    expected = []
    for _ in range(5):
        scores, _ = acquisition_scores(model, remaining, known, weights)
        candidate = remaining.pop(int(np.argmax(scores)))
        expected.append(candidate["id"])
        known.append(candidate)
    assert expected == [r["id"] for r in ep["history"][5:10]]


def test_confidence_interval_reproducible_and_paired_zero():
    assert bootstrap_mean_ci([0, 0, 0]) == {"mean": 0., "ci95": [0., 0.]}
    assert bootstrap_mean_ci([1, 3, 5]) == bootstrap_mean_ci([1, 3, 5])
