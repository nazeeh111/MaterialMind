# Engine method and execution record

This is an adapted retrospective WBM study. There is no new DFT, synthesis, official blind Matbench Discovery result, or demonstrated theoretical algorithmic novelty.

## Surrogate and calibration

- Candidate-visible feature matrix: 64 frozen CHGNet 0.3 initial-structure graph features, 20 initial-only geometric/composition descriptors, published CHGNet signed hull prior, log cost (86 total inputs).
- Fit 40 ExtraTrees residual regressors, minimum leaf size 3, feature fraction 0.8, seed fixed per episode. Target = reference signed hull distance minus published CHGNet signed hull prior. Predicted mean = prior + mean tree correction.
- Ensemble sigma = sqrt(member variance + 0.01^2) eV/atom. This raw disagreement is not a calibrated error bar.
- Fixed calibration partition is excluded from training. For calibration residual z=(reference-mean)/sigma, the 90% two-sided halfwidth is sigma times the finite-sample 90% order statistic of |z|. Stable probability is the smoothed empirical CDF of signed calibration z evaluated at -mean/sigma.
- Chemical-system distribution shift can violate conformal exchangeability. Report observed coverage, Brier score, ECE, interval width and failures, not a coverage guarantee.
- Static calibration metrics condition on the seed0 initial trained model and fixed calibration set. CIs added by chemical-system cluster bootstrap on the test pool; discovery CIs bootstrap initialization seeds on one fixed pool. These are different uncertainty scopes.

## Acquisition

score = (p_stable + exploration * clip(halfwidth / 0.2, 0, 2) + diversity * novelty) / relative_cost^cost_exponent.

novelty = clipped minimum distance to known inputs in standardized PCA12 coordinates, divided by sqrt(12). PCA/scaling is fitted from known training inputs, never the candidate test population. Within each batch, novelty updates as candidate locations are selected; candidate labels remain hidden until the complete batch has been fixed. The surrogate updates from train plus already revealed labels every batch of five. Calibration labels remain reserved.

A finite coefficient search on development-only episodes uses exploration in {0,0.2}, diversity in {0,0.2}, cost exponent in {0,0.5,1}, seeds811/812 and development count/proxy-cost budgets30. Objective maximizes mean stable discoveries under cost cap, ties by count discoveries then smaller terms. Learned coefficients frozen before test: exploration0, diversity0.2, cost_exponent0.5. Thus an explicit uncertainty bonus was not selected. Calibration still affects p_stable. Publish the full search including this negative evidence.

## Test protocol

3072 input-only selected structures: train1360, calibration540, development531, test641. Chemical systems do not cross partitions. Initial geometry deduplication is parent-owned; prototype overlap and pretrained contamination remain explicit caveats.

Ten test initialization seeds0–9; every method shares the same five random initial pool evaluations for a seed. These count against both budgets. Subsequent labels enter only through the selected-ID oracle. All trajectories are generated before full-pool analysis. Budgets: count40 and normalized proxycost40. The underlying declared proxy is 1+(initial_nsites/16)^3, divided by the median training proxy. The cost comparison uses the longest sequential trace prefix below the cap and reports spent cost, which can leave a small unused remainder. This is synthetic relative cost, not DFT timing or money.

Eleven methods: uniform random; published CHGNet greedy; adapted-mean property greedy; interval-width uncertainty sampling; maximum embedding diversity; fixed-kernel GP log expected improvement; MATERIALMIND; uncalibrated transform; no diversity term; no cost term; no online surrogate update. Raw calibration ablation uses a normal residual CDF and 1.645*sigma interval, with the same trained tree surrogate. Term ablations retain other visible features and settings.

GP baseline uses all known training and revealed labels, frozen training-only PCA8 coordinates, CHGNet as the prior mean, constant kernel amplitude0.05^2 times unit RBF and noise variance0.05^2. No test hyperparameter tuning. Incumbent comes from revealed pool candidates, not unrelated train chemistry. Log EI includes a stable negative-tail numerical expansion to prevent all-zero scores. GP is fitted once per batch. It is a fixed-kernel baseline, not a claim of optimized BoTorch performance.

## Execution

The first full invocation completed development fitting. Frozen policy SHA256: f0985a1234f0ffcbcb2a60e25e0cccf0b3504bcd5a997b87cd39a24ea72bda70. Development wall interval between initial-model write and frozen-policy write436.108s. It completed three test episodes, then was interrupted without outcome inspection to cache repeated candidate predictions and within-batch novelty distances. The exact-equivalent implementation passes a regression test against direct sequential score recomputation. All110 test episodes restarted under the byte-identical frozen policy, with no retuning. Original log and freeze timing are retained in materialmind/artifacts/execution/development.json and materialmind/artifacts/execution/benchmark.log. Final invocation uses --frozen-policy; its runtime excludes prior development fitting. Timing describes this shared simulator implementation, not intrinsic algorithm cost or DFT speed.
