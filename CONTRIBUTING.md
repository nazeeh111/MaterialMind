# Contributing

Reproduce the small study before proposing a scientific improvement. Open an issue with
the source revision, data manifest hash, command, environment, expected result and observed
result. Include raw traces for acquisition or calibration changes.

Use Python 3.11–3.13. Install `pip install -e '.[dev,research]'`, then run `pytest`.
The browser interface is buildless; vendor changes need their license and pinned version.
Keep oracle labels out of acquisition inputs and API catalog responses. Do not tune against
the published final test pool and then report the result as untouched evaluation. A revised
scientific claim needs a fresh test partition or a clearly labeled exploratory analysis.

For model changes, document training provenance, energy/reference conventions, data overlap,
CPU cost and failures. For UI changes, inspect the current page at desktop and mobile widths
and verify CIF import/export and retrospective reveals. Preserve calibrated intervals and
the distinction between reference DFT, potential predictions and physical experiments.

Small, focused pull requests with evidence are welcome. Never add credentials or private data.
