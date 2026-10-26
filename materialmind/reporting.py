"""Generate a portable analysis report from actual saved experiment outputs."""
from __future__ import annotations


NAMES = {
    "random": "Random", "pretrained_greedy": "Published CHGNet greedy",
    "property_greedy": "Adapted greedy", "uncertainty": "Uncertainty sampling",
    "diversity": "Diversity sampling", "gp_ei": "Fixed-kernel GP log-EI",
    "materialmind": "MATERIALMIND", "uncalibrated": "Uncalibrated ablation",
    "no_diversity": "No diversity ablation", "no_cost": "No cost ablation",
    "no_online_update": "Frozen surrogate ablation",
}


def render_report(summary: dict, provenance: dict) -> str:
    def interval(value):
        lo, hi = value["ci95"]
        return f'{value["mean"]:.1f} [{lo:.1f}, {hi:.1f}]'

    lines = ["# MATERIALMIND retrospective analysis", "",
             f'{summary["counts"]["test"]} final candidates, {summary["test_stable"]} reference-stable; '
             f'{summary["n_seeds"]} paired initialization seeds. Stable means signed distance to the fixed '
             'MP2020 DFT hull <= 0 eV/atom. No new DFT or synthesis was performed.', "",
             f'| Strategy | Stable at {summary["budget"]} evaluations (95% CI) | Stable at {summary["budget"]} proxy-cost units (95% CI) |',
             '|---|---:|---:|']
    for method, metrics in summary["methods"].items():
        lines.append(f'| {NAMES.get(method, method)} | {interval(metrics["stable_at_budget"])} | {interval(metrics["stable_at_cost_budget"])} |')
    calibrated = summary["calibration"]["calibrated"]
    raw = summary["calibration"]["uncalibrated"]
    lines += ["", "## Calibration", "",
              "| Quantity | Held-out calibrated | Raw ensemble transform |",
              "|---|---:|---:|",
              f'| Brier score (lower is better) | {calibrated["brier"]:.5f} | {raw["brier"]:.5f} |',
              f'| Observed nominal-90% interval coverage | {calibrated["coverage90"]:.2%} | {raw["coverage90"]:.2%} |',
              f'| Mean interval width (eV/atom) | {calibrated["mean_interval_width_ev_atom"]:.5f} | {raw["mean_interval_width_ev_atom"]:.5f} |',
              "", "## Scope and reproducibility", "",
              f'Frozen acquisition weights: `{summary["policy"]}`.',
              f'Policy SHA256: `{summary["policy_sha256"]}`.',
              f'Dataset SHA256: `{summary["dataset_sha256"]}`.', "",
              summary["ci_scope"], "",
              summary["calibration"]["note"], "",
              f'Initial anonymous prototype train/test overlap: {provenance["prototype_train_test_overlap"]}. '
              'Chemical-system separation does not establish independent pretrained-model generalization.', "",
              "The diversity, calibration, cost and update ablations are diagnostics on this test pool. "
              "Choosing the best ablation after inspecting these results does not create a newly validated policy.", "",
              f'Saved test-invocation wall time: {summary["runtime_seconds"]:.3f} seconds. '
              'This measures this simulator implementation, excludes prior development fitting when resumed, '
              'and is not measured DFT cost.', ""]
    return "\n".join(lines)
