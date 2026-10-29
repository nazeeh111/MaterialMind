# Reproducing MATERIALMIND

The release contains a bounded real-data experiment, not a synthetic benchmark. Unit tests
use synthetic fixtures where explicitly labeled. Those fixture results are not research evidence.

## Included-data CPU replay

Use Python 3.11–3.13. The release was run with Python 3.12.14. From a clean checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,research]'
pytest -q
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 materialmind benchmark \
  --seeds 10 --budget 40 --out local-runs/reproduction
materialmind serve
```

No GPU or CHGNet installation is required for replay: source predictions and computed graph
features are included. Do not overwrite the release's `materialmind/artifacts` with exploratory
runs. A small execution check can use two seeds and budget ten; label it as such.

The exact original resolved environment is in `requirements-research.lock`:

```bash
pip install -r requirements-research.lock
pip install -e . --no-deps
```

This full environment includes optional feature-extraction and plotting dependencies.
For deterministic numerical resource use, set `OPENBLAS_NUM_THREADS=1` and
`OMP_NUM_THREADS=1`. On restricted macOS environments, set `MPL_IGNORE_SYSTEM_FONTS=1`
and `MPLCONFIGDIR` to a task-local writable directory. Bundled fonts are enough.

## Rebuild from pinned upstream bytes

```bash
pip install -e '.[atomistic,research]'
python scripts/download_sources.py .cache/raw
python scripts/prepare_data.py --raw .cache/raw --size 3072 --output local-runs/rebuilt-data
```

The downloader verifies the three pinned file MD5s before accepting the bytes. The data
manifest additionally records SHA256. The preparation script freezes input-only sample IDs
and partitions before reading energy labels, then computes real CHGNet features on CPU.
Model graph and geometry features are derived from initial cells. Relaxed volume, band gap,
reference energies, relaxation shifts, and outcome-dependent prototype flags are excluded.

Do not use `unique_prototype` from the upstream summary for input-only sample selection:
it can retain representatives using reference stability. Do not filter by prediction error
against reference labels. Both operations would read the outcomes being evaluated.

## Larger studies and optional acceleration

The preparation command accepts `--size` and `--device cpu|cuda|mps`. CPU is the tested
release default. On suitable hardware an exploratory larger feature extraction can use:

```bash
python scripts/prepare_data.py --raw .cache/raw --size 6144 --device cuda \
  --output local-runs/expanded-data
python scripts/run_benchmark.py --data local-runs/expanded-data/candidates.json \
  --oracle local-runs/expanded-data/oracle.json --output local-runs/expanded-study \
  --seeds 10 --budget 80
```

Use `--device mps` for a compatible Apple GPU or keep `cpu`. Device selection accelerates
graph features only; the residual ensemble and exact GP baseline remain CPU calculations.
GPU performance and the expanded experiment above were not benchmarked for this release.
Exact GP memory and fitting cost grow quickly with the number of known structures; scale
gradually and measure before committing to a large campaign.

The larger hash-selected sample contains released candidates, so this is an exploratory
expansion, not a new untouched validation set. A confirmatory follow-up must reserve new
chemistry/structures, audit released-ID/prototype overlap and freeze decisions before
viewing the new final labels. Keep all larger-run artifacts separate from the release.

## Artifact contracts

| File | Meaning |
|---|---|
| `data/candidates.json` | Metadata plus initial structures, graph features, prior predictions, fixed reference states, input-only split |
| `data/oracle.json` | Candidate ID → previously computed signed DFT hull distance; no acquisition features |
| `data/selection.json` | Frozen selected IDs and input validation/deduplication exclusions |
| `data/provenance.json` | Original URLs, licenses, checksums, transformations, split counts, overlap and failures |
| `artifacts/policy.json` | Development trials and frozen acquisition coefficients |
| `artifacts/summary.json` | Actual mean metrics, bootstrap intervals, count/cost curves and calibration |
| `artifacts/metrics.csv` | One row per final method/seed |
| `artifacts/traces.json` | Every selected ID, reveal, prediction at selection and cumulative budget |
| `artifacts/predictions.json` | Training-only surrogate predictions for analysis, not oracle labels |
| `artifacts/model.joblib` | Training-only model; load only trusted local artifacts |
| `artifacts/figures/*` | Quantitative plots generated from the real traces and calibration measurements |

The policy file is saved and hashed before test trajectories. Full-pool test metrics are
computed after all trajectories have been selected. The package is openly retrospective:
reference labels are distributed locally, so hiding is an auditable interface convention,
not cryptography or a remote blind evaluation service.

## Check a reproduction

Compare `dataset_sha256`, `policy_sha256`, split counts, coefficients, and selected ID sequences.
Means and curves should agree under the same dependency versions, seeds and inputs.
Wall-clock times, platform floating-point details and plotting metadata may differ. Bootstrap
intervals use a fixed analysis RNG; they describe initialization variability on the same pool.

The test suite checks finite-sample quantiles, oracle access, partition separation,
calibration and acquisition behavior, extreme-tail GP numerics, frozen-surrogate ablation,
periodic geometry, CIF roundtrips, API input handling, label hiding and reveal idempotence.
GitHub CI checks multiple Python versions and wheel creation; it does not spend CI time
rerunning the complete research experiment on every source change.

## Reproducible media

Brand, architecture and method figures retain editable SVG sources in `docs/media`.
Quantitative figures retain their Python plotting code and machine-readable measurements.
Launch composition source and original score-generation script are in `docs/launch`.
The movie illustrates real interface operations and saved experiment outputs, not a new
physical calculation or discovery.

## Portable laboratory sessions

Use **Export record** or `GET /api/session` for an atomic snapshot of the current
laboratory. Schema 2 includes `application_version`, `metadata.model_revision`, complete
`candidates` (lattice and fractional sites included), the compatibility `predictions`
list, and `revealed_references` with preselection evidence. Unmatched imports retain
`prediction: null` and an explanation rather than an invented stability estimate.
The UI adds its inspected budget, filters, selected candidate and saved benchmark data.
No unrevealed oracle labels or internal training features are included.

Session state is stored only in server memory. The JSON file remains useful after a reset
or restart, but is not a session-restore upload format. Recover an imported CIF from a
saved candidate using the existing Python adapter:

```python
import json
from pathlib import Path
from materialmind.structures import structure_from_record, to_cif

record = json.loads(Path("materialmind-research-record.json").read_text())
candidate = next(c for c in record["candidates"] if c["split"] == "import")
Path("recovered.cif").write_text(to_cif(structure_from_record(candidate)))
```

Reference-reveal batches are atomic: a failed surrogate fit commits neither labels nor
history. Retrying a successful reveal is idempotent. Catalog reads and session exports
are serialized with reveals and resets so their predictions, history and revision agree.
