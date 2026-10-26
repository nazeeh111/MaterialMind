# MATERIALMIND 0.1 model card

## Model and intended use

This model ranks existing inorganic crystal candidates for **retrospective** reference-label
evaluation. It is an empirical adaptation of a frozen CHGNet prior. It does not predict
synthesizability, kinetic stability, safety, useful functional properties, or experimental yield.

The pretrained foundation is CHGNet **0.3.0**, loaded through `chgnet==0.4.2`. Its 412,525
parameters are frozen. Its published relaxed formation-energy predictions are used as the
energy prior; locally computed 64-dimensional crystal embeddings use the **initial** geometry.
The local computation extracts features and does not perform a new structural relaxation.

The adaptation model is a 40-member ExtraTrees regressor with minimum leaf size 3,
`max_features=0.8`, one CPU worker and a declared random seed. It learns the residual between
reference signed hull distance and the pretrained estimate. Inputs are 64 graph features,
20 initial structure/composition descriptors, pretrained signed hull distance and log raw
cost proxy. A training-only standardizer and 12-component PCA supply diversity coordinates;
the regressor uses the original features. See `materialmind/learning.py`.

## Training and reference target

The 3,072-row WBM subset is selected by an ID hash after input-only eligibility and geometry
deduplication. Chemical-system hash thresholds allocate 1,360 training, 540 calibration,
531 development and 641 final evaluation candidates. Known labels include train and
calibration references. The policy is fitted on development rollouts and frozen before test
trajectories. During a campaign the regression model can append only revealed pool labels.

The target is **signed distance to the fixed MP2020-corrected Materials Project DFT hull**,
in eV/atom. A value <= 0 is reference-stable. Negative values are retained. This is a
composition-aware reference calculation:

```text
hull_reference = reference_formation_energy − reference_signed_hull_distance
prior_signed_hull_distance = published_CHGNet_formation_energy − hull_reference
```

The candidate reference label is never an acquisition feature. The difference above is the
fixed composition reference state supplied by the benchmark. This does not reconstruct a
convex hull from the subset. Model formation energies already include the relevant MP2020
correction convention; applying the correction again would be incorrect.

## Uncertainty and probability

Raw tree disagreement is `sqrt(variance(tree residual predictions) + 0.01²)` in eV/atom.
It is not itself a calibrated physical error bar. On the held-out calibration split,
standardized residuals are `(reference − predicted_mean) / disagreement`. The nominal
90% interval uses the finite-sample order statistic of their absolute values at
`ceil((n_calibration + 1) × 0.90)`.

Stable probabilities use an empirical CDF of the **signed** standardized calibration
residuals with half-count smoothing at the threshold `−mean/disagreement`. This is an
empirical residual-distribution assumption, not a Bayesian posterior probability. It can
be inaccurate for unusual chemistry, systematic potential errors or distribution shift.

Chemical-system holdout and adaptive selection weaken exchangeability, the assumption
under which split-conformal intervals have a coverage guarantee. The release therefore
reports **observed** test coverage, width, Brier score, calibration error and reliability bins.
No guarantee of 90% coverage for an individual crystal or a selected subset is asserted.

## Acquisition model

The fitted model is a small transparent policy combining expected stability, calibrated
interval exploration and clipped nearest-neighbor distance in graph-feature PCA space,
divided by relative proxy cost raised to an exponent. The coefficient search and its
development rewards are retained in `materialmind/artifacts/policy.json`.

The 12 configurations use exploration and diversity in `{0, 0.2}`, and cost exponent in
`{0, 0.5, 1}`. Two development-only campaigns with seeds 811 and 812 select stable yield
at cost budget 30, with declared deterministic tie-breaking. A zero coefficient is a
valid learned result. No component is claimed beneficial unless its ablation supports it.
The method is an original implementation and research study built from established ideas;
algorithmic novelty or universal superiority is not established.

## Data and contamination limits

- No chemical systems overlap the four adaptation partitions, but **213 anonymous initial
  prototypes overlap training and final evaluation**. This is not prototype holdout.
- CHGNet's MPtrj pretraining contains prototypes overlapping WBM. Pretraining contamination
  has not been excluded, so this study cannot establish independent backbone generalization.
- WBM structures were enumerated through element substitution and already evaluated using
  DFT. This software adapts on part of that official benchmark's test data. Its results
  must not be submitted or described as official blind Matbench Discovery performance.
- Input validity checks reject disorder, nonfinite cells and short periodic contacts; they
  do not establish physical synthesizability, charge neutrality or complete chemical plausibility.
- Arbitrary new CIFs do not inherit valid stability estimates from visual similarity alone.
  Compatible formation-energy and hull reference states are required.

## Artifacts and reproducibility

The release includes source features, separate reference labels, source-file checksums,
fitted policy, predictions, complete reveal traces, metrics and a serialized training-only
surrogate. The application fits that surrogate from included data instead of loading
untrusted serialized input. The CPU workflow requires no separately billed API or account.
Actual performance and measured compute are in [REPORT.md](REPORT.md).
