# Independent MATERIALMIND release review

Review scope: objective in `work/goal-objective.md`; current source under `outputs/MaterialMind`; read-only review except this report. Scientific source/data/API/tests/packaging inspected independently. Full ten-seed traces and public release pending at initial review.

## Actionable issues

1. **High: approximate CIF match replaces imported geometry and attaches another geometry's predictions.** `materialmind/server.py:168-173` uses `StructureMatcher(ltol=.2, stol=.3, angle_tol=5)` with its default `scale=True`. Focused real API check imported `wbm-1-48468` after doubling every lattice length. Original volume 33.2245989407 Å³; imported volume 265.796791526 Å³. The response is `matched=true`, same catalog ID, original volume 33.2245989407, and a prediction. Unit-cell scaling changes the input crystal and must not be silently erased or assigned cached physics. Restrict cached reuse to physically equivalent geometry with scale disabled and stringent tolerances; a loose structural analog should retain its imported geometry and have unavailable prediction. Add expanded-cell regression check alongside valid equivalent-cell reuse.

2. **Medium: periodic self-overlap check misses skew-cell lattice images.** `materialmind/structures.py:25-28` replaces the same-site diagonal with infinity and tests only the three supplied lattice-vector lengths. A one-Si structure with lattice `[[5,0,0],[4.9,.1,0],[0,0,5]]` passes `validate_structure`, although neighboring periodic copies lie `|a-b|=0.1414213562 Å` apart, below the declared .55 Å safeguard. Check shortest nonzero lattice translations or periodic neighbors including same-site images. Preserve finite/ordered/volume guards.

Both issues were reported to the parent immediately with reproduction evidence. No model, data, experiment or app changes made by this reviewer.

## Initial scientific findings

- No direct reference labels enter `feature_matrix`, graph embedding extraction, geometric descriptors, PCA/scaler training or acquisition arithmetic. The fixed composition-hull reference is derived as `reference formation energy - signed hull distance`, matching the stated fixed-hull normalization rather than formation-energy ranking.
- Sample eligibility/hash ordering, initial-structure deduplication, and chemical-system split are input-only. Chemical-system grouping prevents same-composition cross-split duplicates; prototype transfer and pretrained contamination are explicitly disclaimed.
- Training/calibration separation, selected-before-reveal batches, development-only finite policy search, and policy write/hash before test episode access are defensible in source. Label hiding is an API/process boundary, correctly not cryptographic secrecy.
- The finite-sample split-conformal order statistic is implemented correctly. Empirical residual CDF probabilities are estimates, not guaranteed conditional probabilities. Chemical-system shift and adaptive recalibration invalidate universal conformal guarantees; existing README caveats accurately limit the claim. Actual empirical coverage/Brier and trace arithmetic still need review.
- Baselines share initialization seed, five initial candidates, batch size, and pool. Count and proxy-cost metrics are prefixes of the same trajectory; running beyond one budget to satisfy the other does not feed later outcomes backward. Proxy cost is explicitly synthetic. Seed-bootstrap scope is correctly limited to this fixed test pool.
- GP baseline uses all known training/revealed labels, a fixed-kernel residual GP, active-pool incumbent and stable log-EI. It is documented as a fixed-kernel reference rather than a tuned universal BO comparison.
- Public documentation is still being assembled. Missing `docs/REPORT.md`, `MODEL_CARD.md`, `REPRODUCIBILITY.md`, actual output metrics and versioned public release are pending work, not yet completed evidence.

## Remaining review

Audit real summary/traces and figures, claims versus outcomes, fresh-install wheel/API behavior and public remote release once available. Do not tune policy on final outcomes or rerun a second full study.

## Fix verification

Parent addressed both findings before release. Independent re-read and original real-input reproductions confirm:

- Strict CIF equivalence uses `scale=False`, `ltol=stol=1e-4`, angle tolerance .01°. The doubled-cell import now returns `matched=false`, retains 265.796791526 Å³, and attaches no prediction.
- Geometry validation uses the shortest Niggli-reduced lattice basis length plus a conditioning guard. The .1414 Å self-image example is rejected as periodic overlap.
- Current structure/API suite: **8 passed**. First invocation from the task root failed package import collection; rerun from repository root succeeded. Deprecation warnings only.

No remaining issue from the initial two findings. Benchmark numerical output and public release remain pending.

## Independent dataset consistency audit

All 3,072 delivered rows pass the declared split-hash assignment and numeric reference identity (`predicted_hull = pretrained_formation_energy - reference_hull_formation_energy`). IDs are unique, each feature vector has 84 entries, and explicit outcome fields are absent from candidate records. The delivered four counts match 1,360/540/531/641. Chemical-system intersections are empty for every split pair. Recomputing anonymous initial-prototype train/test intersection gives 213, matching provenance and README. This audit did not inspect test oracle values or feed observations to model selection.

## Completed real experiment audit

Independent script `work/audit_real_artifacts.py` and output `work/artifact-audit.json` validate all 110 final episodes (11 methods × ten seeds): shared five-candidate initialization per seed; unique test-only selections; reference values and stable flags; cumulative costs and stable counts; metric CSV arithmetic; aggregate means; every one of 880 count/cost curve means; frozen policy SHA256; dataset SHA256. No additional full experiment was run. An additional independent calculation reproduced all 20 paired discovery intervals and six chemical-system-bootstrap calibration intervals from stored traces and the trusted local seed0 model.

Actual outcomes at count40 / cost40:

| Method | Stable at count40 | Stable at cost40 |
|---|---:|---:|
| MATERIALMIND | 29.6 | 28.2 |
| Random | 6.7 | 6.3 |
| Published CHGNet greedy | 28.6 | 27.6 |
| Adapted greedy | 30.6 | 28.6 |
| Uncalibrated ablation | 30.3 | 28.6 |
| No diversity ablation | 31.5 | 30.3 |
| Frozen surrogate | 29.6 | 28.2 |

The learned policy remains exploration0, diversity0.2, cost exponent0.5. Calibration does not improve discovery in this study; no-diversity outperforms the frozen fitted policy by 2.1 discoveries at cost40 (paired 95% interval 1.6–2.7 in favor of removing diversity). Online updating has no demonstrated mean benefit at these endpoints. These are substantive negative outcomes to retain, not grounds for test-driven retuning.

Seed0 held-out test calibration: MAE .0504458 eV/atom; calibrated Brier .0972578 versus raw .0962073; calibrated ECE .0347957 versus raw .0325110; coverage91.4197% versus raw92.9797%; interval width .209680 versus .223672 eV/atom. Calibration makes intervals narrower and closer to nominal90% marginal coverage, but does not improve probability error or measured discovery yield. Calling it universally better uncertainty would be unsupported.

Current rendered discovery, calibration and ablation figures were visually inspected from successful output PNGs. Axes, visible endpoints, method labels, retrospective/cost qualifications and error bars match artifact content. No consequential figure defect found.

Outstanding: final README/report/launch claim consistency and independent public remote/fresh-install verification following publication.
