"""Auditable retrospective discovery experiments on fixed reference labels.

The policy is fitted on development rollouts and serialized before test labels
are requested. This is adaptation on a WBM subset, not an official blind score.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import time
from dataclasses import replace
from pathlib import Path

import joblib
import numpy as np
from scipy.spatial.distance import pdist

from .acquisition import (AcquisitionWeights, RetrospectiveOracle,
                          acquisition_scores, combine_acquisition, gaussian_ei, novelty)
from .learning import calibration_metrics, fit_model, predict

METHODS = ("random", "pretrained_greedy", "property_greedy", "uncertainty",
           "diversity", "gp_ei", "materialmind", "uncalibrated",
           "no_diversity", "no_cost", "no_online_update")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def validate_partitions(candidates: list[dict], labels: dict[str, float]) -> dict[str, list[dict]]:
    ids = [r["id"] for r in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("Candidate IDs overlap")
    partitions = {s: sorted([r for r in candidates if r["split"] == s], key=lambda r: r["id"])
                  for s in ("train", "calibration", "development", "test")}
    if sum(map(len, partitions.values())) != len(candidates):
        raise ValueError("Unknown partition")
    if any(not records for records in partitions.values()):
        raise ValueError("All four partitions are required")
    for first, second in itertools.combinations(partitions, 2):
        a = {r["chemistry_group"] for r in partitions[first]}
        b = {r["chemistry_group"] for r in partitions[second]}
        if a & b:
            raise ValueError(f"Chemical-system leakage between {first} and {second}")
    if set(ids) - labels.keys():
        raise ValueError("Missing reference labels")
    # Check pool-label validity at reveal/analysis time. Dataset membership and
    # policy fitting do not inspect test reference values.
    return partitions


def run_episode(train: list[dict], calibration: list[dict], pool: list[dict],
                known_labels: dict[str, float], oracle: RetrospectiveOracle,
                method: str, weights: AcquisitionWeights, seed: int,
                budget: int, batch_size: int = 5, initial: int = 5) -> dict:
    """Select before revealing; refit every batch. Cost and count share a trace."""
    if method not in METHODS:
        raise ValueError(f"Unknown acquisition method: {method}")
    if budget < initial or batch_size < 1:
        raise ValueError("Budget must cover the shared initial batch")
    rng = np.random.default_rng(seed)
    available = {r["id"]: r for r in sorted(pool, key=lambda r: r["id"])}
    start_ids = rng.choice(list(available), min(initial, len(available)), replace=False).tolist()
    known = list(train)
    available_labels = dict(known_labels)
    history, cumulative_cost, cumulative_stable = [], 0., 0
    cost_scale = float(np.median([r["cost"] for r in train]))
    start = time.perf_counter()
    model = fit_model(known, calibration, available_labels, seed=seed)
    model_updates = 1
    adaptive = {"property_greedy", "uncertainty", "materialmind", "uncalibrated", "no_diversity", "no_cost"}
    while available and (len(history) < budget or cumulative_cost < budget):
        if history and method in adaptive:
            model = fit_model(known, calibration, available_labels, seed=seed)
            model_updates += 1
        if not history:
            selected = start_ids
            details = {i: {"reason": "shared random initialization", "score": None}
                       for i in selected}
        else:
            selected, details = [], {}
            visible = list(available.values())
            arrays = model.arrays(visible, calibrated=method != "uncalibrated")
            prior = np.array([r["predicted_hull"] for r in visible])
            relative_cost = np.array([r["cost"] for r in visible]) / cost_scale
            novelty_values = novelty(model, visible, known)
            latent = np.clip(model.latent(visible), -10, 10)
            mask = np.ones(len(visible), dtype=bool)
            w = replace(weights, diversity=0) if method == "no_diversity" else weights
            w = replace(w, cost_exponent=0) if method == "no_cost" else w
            gp_scores = None
            if method == "gp_ei":
                incumbent = min(available_labels[r["id"]] for r in known[len(train):])
                gp_scores = gaussian_ei(model, visible, known, available_labels, incumbent)
            for _ in range(min(batch_size, len(available))):
                indexes = np.flatnonzero(mask)
                if not len(indexes):
                    break
                if method == "random":
                    score = rng.random(len(indexes))
                elif method == "pretrained_greedy":
                    score = -prior[indexes]
                elif method == "property_greedy":
                    score = -arrays["mean"][indexes]
                elif method == "uncertainty":
                    score = arrays["width"][indexes]
                elif method == "diversity":
                    score = novelty_values[indexes]
                elif method == "gp_ei":
                    # Fantasy locations affect diversity, but GP fitting only
                    # sees candidates whose reference labels are already known.
                    score = gp_scores[indexes]
                else:
                    score = combine_acquisition(arrays["probability"][indexes], arrays["width"][indexes],
                                                novelty_values[indexes], relative_cost[indexes], w)
                best_local = int(np.argmax(score))
                best = int(indexes[best_local])
                r = visible[best]
                selected.append(r["id"])
                details[r["id"]] = {"reason": method, "score": float(score[best_local]),
                                      "predicted_hull": float(arrays["mean"][best]),
                                      "stable_probability": float(arrays["probability"][best]),
                                      "interval_halfwidth": float(arrays["width"][best])}
                mask[best] = False
                distances = np.linalg.norm(latent - latent[best], axis=1) / np.sqrt(latent.shape[1])
                novelty_values = np.minimum(novelty_values, np.clip(distances, 0, 2))
        # The first reference-label access happens after every ID in the batch
        # has been fixed. No rejected candidates are used for fitting.
        revealed = oracle.reveal(selected)
        for candidate_id in selected:
            r = available.pop(candidate_id)
            label = revealed[candidate_id]
            cumulative_cost += r["cost"] / cost_scale
            cumulative_stable += int(label <= 0)
            history.append({"step": len(history) + 1, "id": candidate_id,
                            "reference_hull": label, "stable": bool(label <= 0),
                            "relative_cost": r["cost"] / cost_scale,
                            "cumulative_cost": cumulative_cost,
                            "cumulative_stable": cumulative_stable,
                            **details[candidate_id]})
            known.append(r)
            available_labels[candidate_id] = label
    return {"method": method, "seed": seed, "history": history,
            "runtime_seconds": time.perf_counter() - start,
            "model_updates": model_updates}


def episode_metrics(episode: dict, pool: list[dict], labels: dict[str, float],
                    model, budget: int) -> dict:
    """Analysis only, after the policy has selected its complete trajectory."""
    trace = episode["history"]
    count = trace[:budget]
    cost = [r for r in trace if r["cumulative_cost"] <= budget + 1e-10]
    stable_total = sum(labels[r["id"]] <= 0 for r in pool)
    best_pool = min(labels[r["id"]] for r in pool)
    selected = {r["id"] for r in count}
    z = model.latent([r for r in pool if r["id"] in selected])
    diversity = float(pdist(z).mean() / np.sqrt(z.shape[1])) if len(z) > 1 else 0.
    def stables(records):
        return sum(int(r["stable"]) for r in records)
    found = stables(count)
    return {"method": episode["method"], "seed": episode["seed"],
            "n_selected": len(count), "stable_at_budget": found,
            "precision_at_k": found / len(count) if count else 0,
            "recall_at_budget": found / stable_total if stable_total else 0,
            "stable_per_evaluation": found / len(count) if count else 0,
            "simple_regret_ev_atom": min((r["reference_hull"] for r in count), default=best_pool) - best_pool,
            "discovery_auc": float(np.mean([r["cumulative_stable"] for r in count])) if count else 0.,
            "embedding_diversity": diversity,
            "chemical_systems": len({r["chemistry_group"] for r in pool if r["id"] in selected}),
            "stable_at_cost_budget": stables(cost), "evaluations_at_cost_budget": len(cost),
            "spent_at_cost_budget": float(cost[-1]["cumulative_cost"]) if cost else 0.,
            "runtime_seconds": episode["runtime_seconds"],
            "model_updates": episode["model_updates"]}


def bootstrap_mean_ci(values: list[float], seed: int = 42) -> dict:
    a = np.asarray(values, dtype=float)
    if not len(a):
        raise ValueError("Cannot summarize no observations")
    rng = np.random.default_rng(seed)
    means = rng.choice(a, size=(4000, len(a)), replace=True).mean(axis=1)
    return {"mean": float(a.mean()), "ci95": [float(x) for x in np.quantile(means, [.025, .975])]}


def tune_policy(train, calibration, development, labels, budget=30, seeds=(811, 812)) -> tuple[AcquisitionWeights, list[dict]]:
    """Fit acquisition coefficients by development-only sequential rewards.

    This finite policy search learns a small, inspectable acquisition model. The
    measured reward is discoveries under the same normalized proxy-cost budget.
    It does not establish a novel algorithm or general superiority.
    """
    known = {r["id"]: labels[r["id"]] for r in train + calibration}
    rows = []
    for exploration, diversity, exponent in itertools.product((0., .2), (0., .2), (0., .5, 1.)):
        w = AcquisitionWeights(exploration, diversity, exponent)
        rewards, count_rewards = [], []
        for seed in seeds:
            episode = run_episode(train, calibration, development, known,
                                  RetrospectiveOracle(labels, [r["id"] for r in development]),
                                  "materialmind", w, seed, min(budget, len(development)))
            trace = episode["history"]
            rewards.append(sum(r["stable"] for r in trace if r["cumulative_cost"] <= budget))
            count_rewards.append(sum(r["stable"] for r in trace[:budget]))
            print(f"Development {len(rows) + 1}/12 seed={seed}: weights={w.to_dict()} discoveries={rewards[-1]}", flush=True)
        rows.append({**w.to_dict(), "cost_reward": float(np.mean(rewards)),
                     "count_reward": float(np.mean(count_rewards)),
                     "development_seeds": list(seeds)})
    # Fixed deterministic tie-breaking favors smaller, more parsimonious terms.
    chosen = max(rows, key=lambda r: (r["cost_reward"], r["count_reward"],
                                     -r["exploration"], -r["diversity"], -r["cost_exponent"]))
    return AcquisitionWeights(**{k: chosen[k] for k in ("exploration", "diversity", "cost_exponent")}), rows


def run_study(candidates: list[dict], oracle: dict[str, float], outdir: str | Path,
              seeds: int = 10, budget: int = 40, batch_size: int = 5,
              frozen_policy: str | Path | None = None) -> dict:
    if seeds < 2:
        raise ValueError("At least two seeds are required for confidence intervals")
    if budget < 5 or batch_size < 1:
        raise ValueError("Budget must be at least five and batch size positive")
    start = time.perf_counter()
    output = Path(outdir)
    output.mkdir(parents=True, exist_ok=True)
    partitions = validate_partitions(candidates, oracle)
    train, calibration, development, test = (partitions[s] for s in
                                            ("train", "calibration", "development", "test"))
    if len(test) < budget:
        raise ValueError("Test partition is smaller than the evaluation budget")
    known_labels = {r["id"]: oracle[r["id"]] for r in train + calibration}
    initial_model = fit_model(train, calibration, known_labels)
    joblib.dump(initial_model, output / "model.joblib")
    if frozen_policy is None:
        weights, development_rows = tune_policy(train, calibration, development, oracle,
                                                 budget=min(30, budget))
        policy = {"weights": weights.to_dict(), "objective": "development discoveries at normalized proxy-cost budget",
                  "development_trials": development_rows, "test_labels_used": False,
                  "stable_threshold_ev_atom": 0., "count_budget": budget,
                  "proxy_cost_budget": budget, "batch_size": batch_size}
    else:
        # Resume an interrupted execution with the already-frozen development
        # policy. This does not refit coefficients from any test observation.
        policy = json.loads(Path(frozen_policy).read_text())
        if policy.get("test_labels_used") is not False or policy.get("count_budget") != budget or policy.get("batch_size") != batch_size:
            raise ValueError("Frozen policy protocol does not match this study")
        weights = AcquisitionWeights(**policy["weights"])
    # Persist/fingerprint the policy before any test episode/evaluation.
    write_json(output / "policy.json", policy)
    policy_sha256 = hashlib.sha256((output / "policy.json").read_bytes()).hexdigest()
    episodes, metrics = [], []
    for seed in range(seeds):
        for method in METHODS:
            episode = run_episode(train, calibration, test, known_labels,
                                  RetrospectiveOracle(oracle, [r["id"] for r in test]),
                                  method, weights, seed, budget, batch_size)
            episodes.append(episode)
            write_json(output / "progress.json", {"completed": len(episodes), "total": seeds * len(METHODS),
                                                   "last_method": method, "last_seed": seed})
            print(f"Benchmark {len(episodes)}/{seeds * len(METHODS)}: seed={seed} {method}", flush=True)
    # Full-pool reference labels enter metrics only after every selection trace
    # has been generated. They cannot feed a subsequent test policy fit.
    metrics = [episode_metrics(episode, test, oracle, initial_model, budget) for episode in episodes]
    labels_test = np.array([oracle[r["id"]] for r in test])
    calibration_report = {"calibrated": calibration_metrics(initial_model, test, labels_test, True),
                          "uncalibrated": calibration_metrics(initial_model, test, labels_test, False),
                          "quantile90": initial_model.quantile90,
                          "n_calibration": len(calibration),
                          "note": "Chemical-system shift can violate exchangeability; coverage is empirical, not guaranteed."}
    aggregate = {}
    fields = [k for k in metrics[0] if k not in ("method", "seed")]
    for method in METHODS:
        rows = [r for r in metrics if r["method"] == method]
        aggregate[method] = {k: bootstrap_mean_ci([r[k] for r in rows]) for k in fields}
    paired = {}
    target = [r for r in metrics if r["method"] == "materialmind"]
    for method in METHODS:
        if method == "materialmind":
            continue
        baseline = [r for r in metrics if r["method"] == method]
        paired[method] = {k: bootstrap_mean_ci([a[k] - b[k] for a, b in zip(target, baseline)])
                          for k in ("stable_at_budget", "stable_at_cost_budget")}
    curves, cost_curves = [], []
    for method in METHODS:
        group = [ep for ep in episodes if ep["method"] == method]
        for k in range(1, budget + 1):
            for target_curves, cost_axis in ((curves, False), (cost_curves, True)):
                values = [max((r["cumulative_stable"] for r in ep["history"]
                               if (r["cumulative_cost"] <= k if cost_axis else r["step"] <= k)), default=0)
                          for ep in group]
                result = bootstrap_mean_ci(values)
                target_curves.append({"method": method, "budget": k, "mean": result["mean"],
                                      "lower": result["ci95"][0], "upper": result["ci95"][1]})
    summary = {"schema_version": 1, "study": "WBM retrospective adaptation; not official blind Matbench Discovery",
               "counts": {s: len(r) for s, r in partitions.items()},
               "test_stable": int((labels_test <= 0).sum()), "stable_threshold_ev_atom": 0.,
               "n_seeds": seeds, "budget": budget, "batch_size": batch_size,
               "cost_definition": "candidate cost proxy / median training cost; no measured DFT cost",
               "policy": weights.to_dict(), "policy_sha256": policy_sha256,
               "resumed_frozen_policy": frozen_policy is not None,
               "methods": aggregate, "paired_materialmind_minus_baseline": paired,
               "curves": curves, "cost_curves": cost_curves,
               "dataset_sha256": hashlib.sha256(json.dumps(candidates, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
               "calibration": calibration_report,
               "runtime_seconds": time.perf_counter() - start,
               "ci_scope": "Paired bootstrap over initialization seeds on one fixed test pool; not independent material populations.",
               "limitations": ["No new DFT, synthesis, or materials discovery claim.",
                               "Pretrained model training-data overlap cannot be excluded.",
                               "WBM labels used for adaptation, calibration and development; no official blind result.",
                               "Cost is an explicit relative proxy, not measured electronic-structure work.",
                               "Conformal coverage requires exchangeability; chemical-system shift is evaluated empirically.",
                               "Only a bounded subset, a small finite policy search and fixed-kernel GP log-EI baseline."]}
    write_json(output / "summary.json", summary)
    write_json(output / "traces.json", {"episodes": episodes})
    write_json(output / "predictions.json", {"predictions": predict(initial_model, candidates)})
    with (output / "metrics.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metrics[0]))
        writer.writeheader()
        writer.writerows(metrics)
    plot_results(output, summary, episodes)
    return summary


def plot_results(output: Path, summary: dict, episodes: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none", "figure.facecolor": "#fafaf6",
                         "axes.facecolor": "#fafaf6"})
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    colors = {"materialmind": "#087c83", "property_greedy": "#b86d3f", "random": "#89949a",
              "gp_ei": "#7c66ae", "pretrained_greedy": "#ad8933", "uncertainty": "#6898b8",
              "diversity": "#8d9d54"}
    labels = {"materialmind": "MATERIALMIND", "property_greedy": "Adapted greedy", "random": "Random",
              "gp_ei": "GP log-EI", "pretrained_greedy": "CHGNet greedy",
              "uncertainty": "Uncertainty", "diversity": "Diversity"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    for method in colors:
        for axis, kind in zip(axes, ("count", "cost")):
            # Use exactly the published curve statistics, including the same
            # 4000 bootstrap draws as the endpoint tables and interactive UI.
            rows = sorted([r for r in summary["curves" if kind == "count" else "cost_curves"]
                           if r["method"] == method], key=lambda r: r["budget"])
            x = np.array([r["budget"] for r in rows])
            mean = np.array([r["mean"] for r in rows])
            axis.plot(x, mean, color=colors[method], label=labels[method], linewidth=2 if method == "materialmind" else 1.3)
            lo = np.array([r["lower"] for r in rows])
            hi = np.array([r["upper"] for r in rows])
            axis.fill_between(x, lo, hi, color=colors[method], alpha=.08)
            axis.set_xlabel("Reference evaluations" if kind == "count" else "Normalized proxy-cost budget")
            axis.set_ylabel("DFT-reference-stable candidates found")
            axis.grid(alpha=.15)
    axes[0].set_title("Equal evaluation counts")
    axes[1].set_title("Equal stated proxy costs")
    axes[1].legend(fontsize=8, frameon=False)
    fig.suptitle(f"Retrospective WBM discovery · {summary['n_seeds']} initialization seeds · 95% bootstrap bands", fontsize=12)
    fig.tight_layout()
    for extension in ("svg", "png"):
        fig.savefig(figures / f"discovery.{extension}", dpi=180, bbox_inches="tight")
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for key, color in (("calibrated", "#087c83"), ("uncalibrated", "#b86d3f")):
        bins = summary["calibration"][key]["bins"]
        axes[0].plot([b["probability"] for b in bins], [b["stable_fraction"] for b in bins],
                     "o-", color=color, label=key.capitalize())
    axes[0].plot([0, 1], [0, 1], "--", color="#89949a", linewidth=1)
    axes[0].set(xlabel="Predicted stability probability", ylabel="Observed stable fraction", title="Test-pool probability calibration")
    axes[0].legend(frameon=False)
    coverage = [summary["calibration"][k]["coverage90"] for k in ("uncalibrated", "calibrated")]
    axes[1].bar(["Raw ensemble", "Held-out calibrated"], coverage, color=["#b86d3f", "#087c83"], width=.55)
    if all("ci95" in summary["calibration"][k] for k in ("uncalibrated", "calibrated")):
        bounds = [summary["calibration"][k]["ci95"]["coverage90"] for k in ("uncalibrated", "calibrated")]
        errors = [[max(0, c - b[0]) for c, b in zip(coverage, bounds)],
                  [max(0, b[1] - c) for c, b in zip(coverage, bounds)]]
        axes[1].errorbar([0, 1], coverage, yerr=errors, fmt="none", color="#203b3c", capsize=4)
    axes[1].axhline(.9, linestyle="--", color="#89949a", linewidth=1, label="Nominal 90%")
    axes[1].set(ylim=(0, 1), ylabel="Observed interval coverage", title="Energy interval coverage under shift")
    axes[1].legend(frameon=False)
    fig.tight_layout()
    for extension in ("svg", "png"):
        fig.savefig(figures / f"calibration.{extension}", dpi=180, bbox_inches="tight")
    plt.close(fig)
    methods = ("materialmind", "uncalibrated", "no_diversity", "no_cost", "no_online_update")
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, method in enumerate(methods):
        result = summary["methods"][method]["stable_at_cost_budget"]
        m, (lo, hi) = result["mean"], result["ci95"]
        ax.bar(i, m, color="#087c83" if method == "materialmind" else "#a7b9b4", width=.55)
        ax.errorbar(i, m, yerr=[[m - lo], [hi - m]], color="#203b3c", capsize=4)
    ax.set_xticks(range(5), ["MATERIALMIND", "Raw uncertainty", "No diversity", "No cost term", "Frozen surrogate"], fontsize=9)
    ax.set(ylabel="Stable candidates at proxy-cost budget", title="Ablations · frozen development-fitted coefficients")
    fig.tight_layout()
    for extension in ("svg", "png"):
        fig.savefig(figures / f"ablations.{extension}", dpi=180, bbox_inches="tight")
    plt.close(fig)


def audit_results(candidates: list[dict], labels: dict[str, float], outdir: str | Path) -> dict:
    """Check frozen artifacts against source labels, without retraining policy.

    This is a reproducibility audit of a retrospective artifact, not independent
    DFT validation. It also adds conditional cluster CIs for calibration metrics.
    """
    began = time.perf_counter()
    output = Path(outdir)
    summary = json.loads((output / "summary.json").read_text())
    episodes = json.loads((output / "traces.json").read_text())["episodes"]
    partitions = validate_partitions(candidates, labels)
    test = partitions["test"]
    by_id = {r["id"]: r for r in test}
    model = joblib.load(output / "model.joblib")
    cost_scale = float(np.median([r["cost"] for r in partitions["train"]]))
    policy_hash = hashlib.sha256((output / "policy.json").read_bytes()).hexdigest()
    if policy_hash != summary["policy_sha256"]:
        raise ValueError("Frozen policy hash does not match summary")
    data_hash = hashlib.sha256(json.dumps(candidates, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if data_hash != summary["dataset_sha256"]:
        raise ValueError("Candidate dataset hash does not match summary")
    if len(episodes) != summary["n_seeds"] * len(METHODS):
        raise ValueError("Incomplete method/seed matrix")
    shared_initials = {}
    keys = set()
    for episode in episodes:
        key = (episode["method"], episode["seed"])
        if key in keys:
            raise ValueError("Repeated method/seed episode")
        keys.add(key)
        trace = episode["history"]
        ids = [r["id"] for r in trace]
        if len(ids) != len(set(ids)) or not set(ids) <= by_id.keys():
            raise ValueError("Repeated evaluation or cross-partition selection")
        initial = tuple(ids[:5])
        if episode["seed"] in shared_initials and shared_initials[episode["seed"]] != initial:
            raise ValueError("Methods do not share initialization")
        shared_initials[episode["seed"]] = initial
        cumulative_cost, cumulative_stable = 0., 0
        for index, row in enumerate(trace, 1):
            truth = labels[row["id"]]
            cumulative_cost += by_id[row["id"]]["cost"] / cost_scale
            cumulative_stable += int(truth <= 0)
            if row["step"] != index or row["reference_hull"] != truth or row["stable"] != (truth <= 0):
                raise ValueError("Reveal trace differs from source reference")
            if row["cumulative_stable"] != cumulative_stable or not np.isclose(row["cumulative_cost"], cumulative_cost):
                raise ValueError("Cumulative budgets or discoveries are incorrect")
            if row["score"] is not None and not np.isfinite(row["score"]):
                raise ValueError("Non-finite acquisition score")
        if len(trace) < summary["budget"] or (cumulative_cost < summary["budget"] and len(trace) < len(test)):
            raise ValueError("Trajectory did not cover both declared budgets")
        if episode["method"] == "no_online_update" and episode["model_updates"] != 1:
            raise ValueError("Frozen-surrogate ablation updated its model")
    expected_keys = set(itertools.product(METHODS, range(summary["n_seeds"])))
    if keys != expected_keys:
        raise ValueError("Method/seed coverage does not match protocol")
    # Check that GP ranking is informative after the shared seed0 initialization.
    initial_ids = shared_initials[0]
    initial_records = [by_id[i] for i in initial_ids]
    gp_known = partitions["train"] + initial_records
    gp_labels = {r["id"]: labels[r["id"]] for r in gp_known}
    remaining = [r for r in test if r["id"] not in initial_ids]
    gp_scores = gaussian_ei(model, remaining, gp_known, gp_labels,
                            incumbent=min(labels[i] for i in initial_ids))
    if len(np.unique(gp_scores)) < 2:
        raise ValueError("GP log-EI ranking is degenerate")
    test_labels = np.array([labels[r["id"]] for r in test])
    for calibrated, name in ((True, "calibrated"), (False, "uncalibrated")):
        new_metrics = calibration_metrics(model, test, test_labels, calibrated)
        for field in ("mae_ev_atom", "brier", "coverage90"):
            if not np.isclose(new_metrics[field], summary["calibration"][name][field]):
                raise ValueError("Saved model/calibration results do not match summary")
        summary["calibration"][name] = new_metrics
    audit = {"passed": True, "episodes": len(episodes), "n_seeds": summary["n_seeds"],
             "methods": list(METHODS), "policy_sha256": policy_hash, "dataset_sha256": data_hash,
             "checks": ["complete method/seed matrix", "shared initialization", "unique in-partition evaluations",
                        "revealed labels match source", "cumulative budgets and discovery counts",
                        "finite acquisition scores", "frozen no-online ablation", "model metrics match artifact"],
             "gp_first_batch": {"all_finite": bool(np.isfinite(gp_scores).all()),
                                "n_candidates": len(gp_scores), "unique_scores": len(np.unique(gp_scores)),
                                "minimum_log_ei": float(gp_scores.min()), "maximum_log_ei": float(gp_scores.max()),
                                "would_underflow_direct_ei": int((gp_scores < np.log(np.finfo(float).tiny)).sum())},
             "runtime_seconds": time.perf_counter() - began,
             "limits": "Retrospective artifact audit; not independent DFT or proof of cryptographic label hiding."}
    summary["audit"] = audit
    summary["bootstrap_draws"] = {"initialization_seed_metrics_and_curves": 4000,
                                  "conditional_calibration_chemical_system_clusters": 2000}
    write_json(output / "audit.json", audit)
    write_json(output / "summary.json", summary)
    plot_results(output, summary, episodes)
    return audit
