# MATERIALMIND 0.1.1

This maintenance release improves reference-replay consistency, portable records, and
crystal framing. The frozen dataset, model, policy, benchmark trajectories and scientific
results remain the same as 0.1.0.

- Reference reveals commit their labels, decision history and fitted model together.
  A failed refit leaves the session unchanged and can be retried safely.
- Catalog reads and exports take one consistent snapshot across model updates and resets.
- Research records now include all candidate coordinates, imported geometry, prediction
  availability, application version and model revision. The existing `predictions` list
  remains available; `schema_version: 2` adds complete `candidates` records.
- UI mutations are serialized while a reveal, reset or import is pending; export waits
  until the displayed operation completes.
- Camera framing and clipping adapt to the actual cell size and viewport, including
  long valid imported cells. Unit-cell coordinates and physical data are unchanged.
- Regression tests cover failed-refit recovery and export completeness without exposing
  unrevealed reference labels.

Session records are JSON snapshots, not a session-restore upload format. Live session state
is in server memory. Export before clearing a session or shutting down the server.

The launch film on the 0.1.0 release remains the original demonstration. See
`docs/REPORT.md` for the unchanged research findings and `docs/REPRODUCIBILITY.md`
for scientific reproduction.

---

# MATERIALMIND 0.1.0

The first public research release of a local crystal-discovery laboratory and reproducible
retrospective selection study.

## Included

- 3,072 real WBM initial structures with pinned public-data provenance, frozen CHGNet graph
  embeddings, published energy predictions and separately stored prior DFT reference labels.
- A trained residual stability ensemble, held-out uncertainty calibration, and an acquisition
  policy fitted through development-only campaigns and frozen before final evaluation.
- Eleven strategies and ablations across ten paired initialization seeds, with complete
  traces, count/cost comparisons, paired intervals, calibration analysis and quantitative figures.
- A WebGL laboratory with actual periodic geometry, candidate explanations, reference-reveal
  model updates, CIF validation/export, portable research records and analysis reports.
- Python CLI/API, tests, CI, model/data documentation, editable diagrams and a verified
  20-second launch film built from the actual application and experiment outputs.

## What the evidence says

At 40 evaluations on the 641-candidate final pool, the fitted policy recovered 29.6 stable
candidates on average [95% seed-bootstrap interval 29.1–30.1], versus 6.7 for random and
30.6 for adapted greedy. Calibration did not improve discovery yield. The selected diversity
term hurt final performance; online updates showed no endpoint benefit. These negative
results are retained, and the pretest policy remains unchanged.

This is an adapted retrospective WBM study, not an official blind Matbench Discovery result,
a new DFT campaign or a synthesis/discovery claim. Cost is a stated site-count proxy.
Prototype and pretrained-model overlap limit generalization claims. See `docs/REPORT.md`.

## Quickstart

Use Python 3.11–3.13, then install the attached wheel or clone the repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
materialmind serve
```

Open http://127.0.0.1:8765. The CPU demonstration needs no API key, external account,
GPU or PyTorch. An unsupported new CIF is shown as validated geometry without inventing
a stability prediction. The local server is not intended as an authenticated public service.

Code is MIT licensed; source data are CC BY 4.0 with the required scientific attribution.
Release assets include the wheel, source distribution, launch film and SHA256 checksums.
