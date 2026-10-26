# MATERIALMIND scientific source review

Reviewed current source on 2026-10-25: `scripts/prepare_data.py`, `materialmind/structures.py`, `learning.py`, `acquisition.py`, `benchmark.py`. Read-only review, before prepared data and experiment outputs were present. Consequently numerical model performance is not verified by this review.

## Actionable findings

1. **Anonymous prototype overlap is undercounted.** `prepare_data.py` creates `prototype_sets` from the complete `initial_prototype` string and reports its train/test intersection. The upstream label includes a colon-separated chemical-system suffix. Since the split already separates chemical systems, that intersection can return zero even when both sides contain the same anonymous prototype. Strip the suffix before the anonymous-prototype audit; retain both audits with explicit names. Report all partition-pair overlap counts. The present chemical-system holdout is defensible, but does not establish prototype holdout or new-prototype transfer. If prototype generalization is claimed, enforce prototype-group separation rather than just reporting it.

2. **The GP-EI baseline is materially restricted and needs a collapse audit before comparison claims.** `acquisition.py:108-120` deterministically truncates all known training plus revealed data to 192 entries, uses a fixed 0.05 eV signal/noise scale with no development fitting, and sets the EI incumbent to the minimum among this truncated cross-chemistry training set. Other adaptive policies fit all available known training labels. New evaluations can also be dropped by the deterministic subsample. If the historical training incumbent is much lower than pool means and GP uncertainty, EI can become effectively zero across the pool, turning `argmax` into ID order. This is a source-supported risk, not an observed local collapse yet. Inspect score distributions/zero-score fractions and whether recently revealed points enter the GP. A stronger controlled baseline uses the initial campaign-pool incumbent, keeps revealed pool points when compressing old training data, and chooses sensible fixed hyperparameters using development data only. Log-EI avoids numerical underflow. Otherwise describe this as a restricted fixed-kernel GP reference and avoid broad superiority against Bayesian optimization.

3. **Runtime is engine runtime, not intrinsic policy compute.** `benchmark.py:74-88` refits ExtraTrees and computes all ensemble predictions for every strategy, including random, pretrained-greedy and the GP method. The exported `runtime_seconds` therefore includes work those baselines do not inherently require and, for cost-sensitive campaigns, extra selections beyond the count budget. Keep this metric if described as measured shared-engine trajectory runtime; add fit/selection clocks or avoid claims that one acquisition algorithm is computationally faster based on it.

4. **Calibration guarantees must remain empirical in adaptive runs.** The finite-sample conformal quantile calculation is correct under exchangeability, but the split is by chemical system and the calibration set is repeatedly reused after model refits. Probability estimates are an empirical standardized-residual CDF, not conformal posterior probabilities. Current summary correctly says coverage is empirical under shift; ensure README/interface/report never shorten this to guaranteed 90% coverage or guaranteed calibrated probabilities. Compare actual test Brier, reliability and coverage. A zero fitted exploration/diversity/cost coefficient makes its ablation identical; report that honestly rather than claiming that term helped.

## Observations that appear scientifically sound

- Input-only hash selection, initial-geometry descriptors and frozen initial-structure CHGNet embeddings avoid the relaxed-volume/band-gap leakage identified in the source research.
- The composition-reference calculation `pred_eform - (true_eform - true_hull_distance)` matches the upstream fixed-hull normalization and preserves signed distances. The reference-hull offset is a known composition reference rather than a candidate label feature, provided that distinction is documented.
- `StructureMatcher` deduplication is applied before label loading; all structures sharing a chemical system share a split. The adapter excludes source joins/nonfinite-energy failures explicitly rather than fabricating predictions.
- Surrogate residuals are trained only from train plus revealed labels. Calibration labels are excluded from estimator fitting. Acquisition IDs are fixed before batch oracle reveals, with fantasy locations used only for novelty.
- Identical initial random batches, same pools, paired seeds and fixed ablation weights make the policy comparisons interpretable. Count-budget and cost-budget traces are separately truncated, and prefix results are not influenced by labels revealed later in the trajectory.
- Data adaptation is explicitly labeled retrospective WBM, not official blind Matbench Discovery. Pretraining overlap, synthetic cost, fixed GP limitations and seed-CI scope are already stated in the summary.

## Checks to run when real data exists

- Initial anonymous-prototype overlap audit; train/calibration/development/test composition disjointness.
- Source-hull equality spot checks and input-feature invariance to changes in unrelated oracle labels.
- GP-EI score dynamic range and ordering versus ID order across seeds, including retention of queried points.
- Exact zero-weight ablation identity and nonzero-weight ablation divergence where applicable.
- Per-trace no repeated reveals, identical seed initialization, prefix budgets, calibrated interval coverage and actual inference/proxy-cost separation.
