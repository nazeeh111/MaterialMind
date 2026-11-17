# Portable research sessions

Export a record before stopping the server. On a compatible installation, choose
**Restore record**, select or paste that JSON, and confirm replacement of the
current browser session. Other browser sessions are unaffected. Existing search,
sort and partition filters are kept. Export current work first if you need both
sessions. The application does not automatically save to disk.

## What is reconstructed

Schema 3 adds a `replay` manifest and `replay_sha256` checksum to the existing
human-readable catalog, predictions and revealed-reference history:

* A compatibility contract fingerprints the complete loaded dataset and private
  oracle together (only a SHA-256 hash is exported), frozen acquisition policy,
  server/replay/learning/acquisition/geometry source files, scientific and validation package versions
  (including the separate `pymatgen-core` distribution where installed),
  Python version, operating-system family and machine architecture.
* Ordered batches contain only the newly revealed held-out IDs, in their original
  order, and their recorded timestamps. Repeated no-op reveal requests do not
  create a batch. Each batch corresponds to exactly one refit.
* Imported IDs and plain periodic geometry are preserved. Metadata is recomputed
  with pymatgen, with at most 256 ordered, non-overlapping elemental sites per cell.
  Imports remain geometry-only: no fabricated prediction or reference is added.

Restore starts from the original training/calibration partitions, regenerates
selection-time predictions, costs and labels from server-owned data, then refits
after **each original batch**. Flattening batches would change the selection
history even when the final training set happened to match. Subsequent reveals
continue from the reconstructed model.

For strict restore, uploaded `candidates`, `predictions`, `revealed_references`, metadata and UI context
are read-only annotations, not restoration inputs. Changing them cannot inject
labels into the model. Timestamps are preserved user-supplied annotations, not
authenticated proof of when an evaluation occurred. The checksum detects
accidental changes to replay inputs, not malicious authorship or provenance:
anyone can author a new valid manifest and checksum. This local research tool
does not claim signed records or prevent users choosing which references to reveal.

The compatibility check is deliberately conservative. A version/code/environment
change is rejected rather than silently approximated. Matching package versions
and platform identity still do not prove bit-identical numerical libraries,
CPU instructions or hardware. Tests establish exact roundtrip behavior in the
tested environment, not cross-platform bitwise reproducibility. Preserve the
original environment for archived sessions.

Schema 2 retains ordered selections and effective batch boundaries through its
selection-time model revisions. It lacks the complete dataset, code and runtime
compatibility contract required for exact restoration. Keep old records as
readable research evidence; this strict restore does not automatically migrate
them or verify their original predictions. No pickle, uploaded model, dynamic
import or uploaded code is used.

## Replay as new

Use the separate **Replay as new** action to reuse eligible schema-2 choices or a
checksum-valid schema-3 record with a stale compatibility contract. Confirm that
this replaces the current browser session. The engine validates the saved held-out
IDs and their current catalog geometries, recovers effective batch order and
imports, and recomputes labels, costs and predictions using the current model and
dataset. Uploaded labels and predictions are not scientific authority. Invalid
or ambiguous revision sequences, changed structures, corrupt checksums and
unsupported geometry are refused without replacing the current session.

The resulting schema-3 export has a checksum-covered `replay.origin`: it records
`replayed_as_new`, the immediate input file's SHA-256, source schema, source
contract fingerprint when present and server-generated replay time. This marker
survives a later strict restore and further reveals. Source selection timestamps
remain annotations; replay time does not certify when the old selections occurred.
Only the immediate source is noted; no original file or recursive ancestry is
embedded. Keep the original export separately. The checksum does not authenticate
its author or establish original-model equivalence.

## API and failure behavior

* `GET /api/session`: export schema-3 JSON.
* `POST /api/session`: send that JSON with `Content-Type: application/json`.
  Success returns `restored: true` plus the authoritative catalog, metadata and
  history. The server publishes the replacement only after validation, all refits
  and catalog generation succeed.
* `POST /api/session/replay`: explicitly replay eligible selections as a new current-contract session. Success returns `replayed: true` plus the current catalog.
* `POST /api/reset`: clear only this browser session.

HTTP 422 means invalid schema/IDs/geometry/checksum; 409 means an incompatible
contract or session limit; 413 means the request body is too large; 503 means
the fitting capacity is busy, reconstruction failed, or session capacity is full.
These restore failures leave existing session data unchanged. The UI retains
input for correction/retry and prevents conflicting mutations during restoration.
After a lost connection, reload to discover whether the restore committed before
retrying. Reapplying the same valid export replaces the session with the same
reconstructed state, not duplicate reveals.

## Resource and ownership bounds

* Restore and replay: at most **16 MiB actual request bytes**, checked before JSON parsing,
  including requests without a Content-Length header.
* Reveals: at most 20 IDs per batch, no duplicate restored IDs within/across
  batches, and at most `min(1024, held-out pool size)` refits per session. In the
  shipped 641-candidate pool every candidate can be revealed separately.
* Imports: at most 32 structures and 256 sites each. Live import enforces the same
  count bound; CIF request bodies are limited to 2,100,000 bytes.
* Two concurrent update/reconstruction jobs per server process. Excess jobs
  receive 503 and can be retried; jobs are not queued without bound.
* Up to 128 in-memory sessions. Capacity errors replace the old behavior of
  silently evicting the oldest session. Export work before restarting to clear
  capacity. Each session serializes its own reads/mutations; the registry lock is
  never held during model fitting. The initial model is computed once and shared
  read-only, protected by its own initialization lock.

A maximum-length replay still takes many model fits. There is no hard wall-clock
timeout or cancellation of an already running fit. This is a loopback local
research server, not an authenticated or rate-limited multi-user service. Restart
with a single worker: independent worker processes do not share these sessions.

## Why not a new workflow framework?

The existing [foundation review](FOUNDATIONS.md) and current primary documentation
were compared on 2026-11-15:

* [ASE trajectories](https://ase-lib.org/ase/io/trajectory.html) preserve atomic
  configurations and calculator properties. They do not supply MaterialMind's
  reveal/refit/acquisition semantics. Existing pymatgen geometry is already adequate.
* [AiiDA archives](https://aiida.readthedocs.io/projects/aiida-core/en/stable/howto/share_data.html)
  preserve full provenance graphs with database/object-store storage. They are a
  stronger foundation for executed calculation workflows, but disproportionate
  to this finite-pool local replay.
* Strict plain JSON plus content hashes and the existing deterministic fit path
  solves resumability without adding services, dependencies or model serialization.

This engineering change does not rerun, retune or alter the frozen scientific study.
The existing transitive Pydantic dependency is now explicitly constrained to v2,
whose strict validation API implements the manifest. No new package is introduced.

## Input identity and changing catalogs

An unchanged selected JSON file is submitted as its captured original bytes,
including UTF-8 BOM and CRLF endings. Its replay origin identifies those exact
bytes. Editing the displayed JSON instead submits and identifies the edited
UTF-8 text. The original file is retained in either case.

Replay validates a complete source compatibility identity and its fingerprint;
an empty self-consistent object is not a complete identity. This is consistency
validation, not authentication or proof of the old installation's execution.
Strict restore still requires the current exact compatibility contract.

A saved catalog may contain up to 10,000 rows within the existing 16 MiB request
limit. Unselected old catalog rows need not exist in the current catalog. Every
replayed selection must retain its current held-out identity and geometry, and
each imported structure must have an explicit import partition and valid geometry.
Malformed imports are refused, rather than silently omitted. Current model results
are recalculated. A confirmed session reset removes its replay-origin status.

