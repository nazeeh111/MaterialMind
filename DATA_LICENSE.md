# Data and model attribution

Code in this repository is MIT licensed. Upstream data retain their separate licenses.

The WBM initial structures, reference labels, and published CHGNet benchmark predictions
are subsetted from the **Matbench Discovery** data collection by Janosh Riebesell and
contributors, licensed **Creative Commons Attribution 4.0 International**:
https://creativecommons.org/licenses/by/4.0/ . The source collection and exact file IDs,
checksums, and transformations are in `materialmind/data/provenance.json`.

Source: https://doi.org/10.6084/m9.figshare.22715158
Benchmark: Riebesell et al., *Matbench Discovery: A framework to evaluate machine learning
crystal stability predictions*, Nature Machine Intelligence (2025),
https://doi.org/10.1038/s42256-025-01055-1 .
Original WBM: Wang, Botti and Marques, *Predicting stable crystalline compounds using
chemical similarity*, npj Computational Materials 7, 12 (2021),
https://doi.org/10.1038/s41524-020-00481-6 .

Changes: deterministic input-only subsetting and geometry validation; initial-structure
deduplication; chemical-system partitioning; CHGNet crystal embeddings; reference-state
conversion to signed hull distance; learned residual adaptation and uncertainty calibration.
WBM is synthetic candidate enumeration followed by historical DFT; it is not a synthesis database.

CHGNet 0.3.0 is used as a frozen pretrained foundation. Its source and checkpoint are
BSD-3-Clause licensed by the Ceder Group / The Regents of the University of California.
The checkpoint is installed by the optional `chgnet` package and is not copied here.
Frozen features derived from it and the source structures are included for CPU-only replay.
Deng et al., *CHGNet as a pretrained universal neural network potential for charge-informed
atomistic modelling*, Nature Machine Intelligence 5, 1031–1041 (2023),
https://doi.org/10.1038/s42256-023-00716-3 . Source/license:
https://github.com/CederGroupHub/chgnet/blob/main/LICENSE .

Bundled Three.js retains its MIT license in `materialmind/web/vendor/THREE-LICENSE.txt`.
The dependency licenses are owned by their respective authors. See `docs/FOUNDATIONS.md`
for investigated alternatives and their provenance. No claims of endorsement are implied.
