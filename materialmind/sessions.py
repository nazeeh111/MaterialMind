"""Server-owned session transitions and portable, non-executable replay records."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import re
import secrets
import threading
import time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from materialmind import __version__
from materialmind.structures import describe, structure_from_record

MAX_SESSION_BYTES = 16 * 1024 * 1024
MAX_BATCHES = 1024
MAX_IMPORTS = 32
MAX_SAVED_CANDIDATES = 10_000
IMPORT_STATUS = ("Geometry validated. Stability unavailable: no compatible cached relaxed prediction "
                 "and DFT reference hull. Use the Python adapter for a documented reference workflow.")
MODE = "retrospective_reference_replay"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


class ReplayError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1_000_000, le=1_000_000)]
Vector = Annotated[list[Coordinate], Field(min_length=3, max_length=3)]
Timestamp = Annotated[float, Field(allow_inf_nan=False, ge=0, le=4_102_444_800)]


class Site(StrictRecord):
    element: str = Field(min_length=1, max_length=3, pattern=r"^[A-Z][a-z]?$")
    frac: Vector


class Geometry(StrictRecord):
    lattice: Annotated[list[Vector], Field(min_length=3, max_length=3)]
    sites: Annotated[list[Site], Field(min_length=1, max_length=256)]


class ImportedGeometry(StrictRecord):
    id: str = Field(pattern=r"^import-[0-9a-f]{12}$")
    structure: Geometry


class RevealBatch(StrictRecord):
    selection_mode: Literal["static", "sequential"] = "static"
    ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=128)]],
                   Field(min_length=1, max_length=20)]
    timestamps_unix: Annotated[list[Timestamp], Field(min_length=1, max_length=20)]


class ReplayOrigin(StrictRecord):
    kind: str = Field(pattern=r"^replayed_as_new$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_schema: int = Field(ge=2, le=3)
    source_contract_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    replayed_at: Timestamp


class Replay(StrictRecord):
    contract: dict
    batches: Annotated[list[RevealBatch], Field(max_length=MAX_BATCHES)]
    imports: Annotated[list[ImportedGeometry], Field(max_length=MAX_IMPORTS)]
    origin: ReplayOrigin | None = None


def validate_source_contract(contract):
    """Admit a complete source identity, without claiming its compatibility."""
    required = {"protocol", "dataset_sha256", "policy_sha256", "source_sha256",
                "dependencies", "runtime", "seed", "fingerprint"}
    if type(contract) is not dict or not required.issubset(contract):
        raise ReplayError("Source compatibility contract is incomplete.")
    if contract["protocol"] != "materialmind-session-replay-1":
        raise ReplayError("Unsupported source compatibility protocol.")
    def is_digest(value):
        return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    if not all(is_digest(contract[key]) for key in ("dataset_sha256", "policy_sha256", "fingerprint")):
        raise ReplayError("Invalid source dataset, policy or compatibility identity.")
    source = contract["source_sha256"]
    names = {"__init__.py", "learning.py", "acquisition.py", "structures.py", "sessions.py", "server.py"}
    if type(source) is not dict or not names.issubset(source) or not all(is_digest(v) for v in source.values()):
        raise ReplayError("Source application identities are incomplete.")
    dependencies = contract["dependencies"]
    required_dependencies = {"numpy", "scipy", "scikit-learn", "pymatgen", "spglib", "joblib", "pydantic"}
    def version_string(value):
        return type(value) is str and 0 < len(value) <= 256
    if (type(dependencies) is not dict or not required_dependencies.issubset(dependencies)
            or not all(version_string(value) or (name == "pymatgen-core" and value is None)
                       for name, value in dependencies.items())):
        raise ReplayError("Source dependency identities are incomplete.")
    runtime = contract["runtime"]
    if (type(runtime) is not dict or not {"python", "implementation", "system", "machine"}.issubset(runtime)
            or not all(version_string(value) for value in runtime.values())):
        raise ReplayError("Source runtime identities are incomplete.")
    if type(contract["seed"]) is not int or not 0 <= contract["seed"] < 2**63:
        raise ReplayError("Invalid source model seed.")
    body = {key: value for key, value in contract.items() if key != "fingerprint"}
    if contract["fingerprint"] != digest(body):
        raise ReplayError("Source compatibility fingerprint is invalid.")


def new_state() -> dict:
    return {"revealed": {}, "imports": {}, "model": None, "history": [],
            "model_revision": 0, "batches": [], "origin": None}


class Session:
    def __init__(self):
        self.state = new_state()
        self.lock = threading.RLock()


class SessionEngine:
    """Transitions run under their owner's session lock, never a global fit lock."""

    def __init__(self, root: Path, dataset: tuple[dict, dict]):
        self.payload, self.oracle = deepcopy(dataset)
        self.records = self.payload["candidates"]
        self.by_id = {r["id"]: r for r in self.records}
        self.pool = [r for r in self.records if r["split"] == "test"]
        self.train = sorted([r for r in self.records if r["split"] == "train"], key=lambda r: r["id"])
        self.calibration = sorted([r for r in self.records if r["split"] == "calibration"], key=lambda r: r["id"])
        policy_path = root / "artifacts/policy.json"
        self.policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
        try:
            geometry_core_version = version("pymatgen-core")
        except PackageNotFoundError:
            geometry_core_version = None  # Older pymatgen releases include core in the main distribution.
        self.contract = {
            "protocol": "materialmind-session-replay-1",
            "dataset_sha256": digest({"candidates": self.payload, "oracle": self.oracle}),
            "policy_sha256": digest(self.policy),
            "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                              for name in ("__init__.py", "learning.py", "acquisition.py",
                                           "structures.py", "sessions.py", "server.py")},
            "dependencies": {name: version(name) for name in
                             ("numpy", "scipy", "scikit-learn", "pymatgen", "spglib", "joblib", "pydantic")}
                            | {"pymatgen-core": geometry_core_version},
            "runtime": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                        "system": platform.system(), "machine": platform.machine()},
            "seed": 0,
        }
        self.contract["fingerprint"] = digest(self.contract)
        self._initial = None
        self._initial_lock = threading.Lock()

    def model(self, state):
        from materialmind.learning import fit_model
        if state["model"] is None:
            with self._initial_lock:
                if self._initial is None:
                    self._initial = fit_model(self.train, self.calibration, self.oracle, seed=0)
            return self._initial
        return state["model"]

    def recommendation_snapshot(self, state):
        return digest({'contract': self.contract['fingerprint'], 'batches': state['batches'],
                       'imports': state['imports'], 'origin': state['origin']})

    def reveal_recommendation(self, state, count, snapshot):
        if snapshot != self.recommendation_snapshot(state):
            raise ReplayError('This batch preview is stale. Refresh candidates and preview a new batch.', 409)
        rows = self.recommend(state, count)['recommendations']
        if not rows:
            raise ReplayError('All held-out references have already been revealed.', 409)
        ids = [row['id'] for row in rows]
        self.reveal(state, ids, sequential=True)
        return ids

    def recommend(self, state, count=5):
        from materialmind.acquisition import recommend_batch
        known = self.train + [r for r in self.pool if r['id'] in state['revealed']]
        available = [r for r in self.pool if r['id'] not in state['revealed']]
        batch = recommend_batch(self.model(state), available, known, count, self.policy)
        fields = ('id', 'formula', 'predicted_hull', 'interval_low', 'interval_high',
                  'stable_probability', 'acquisition', 'relative_cost', 'novelty',
                  'exploration', 'acquisition_weights', 'batch_position', 'reason')
        return {'model_revision': state['model_revision'], 'snapshot': self.recommendation_snapshot(state),
                'requested_count': count,
                'recommendations': [{k: r[k] for k in fields} for r in batch],
                'note': 'Suggestions only. No references revealed or session changes. Reveal a chosen batch together to refit once.'}

    def catalog(self, state):
        from materialmind.acquisition import rank_candidates
        known = [r for r in self.records if r["split"] == "train" or r["id"] in state["revealed"]]
        predictions = rank_candidates(self.model(state), self.pool, known, self.policy)
        pred_by_id = {p["id"]: p for p in predictions}
        result = []
        for record in self.pool:
            item = {k: deepcopy(v) for k, v in record.items() if k not in {"features", "initial_prototype"}}
            p = pred_by_id[item["id"]]
            item["prediction"] = {
                "mean": p["predicted_hull"], "sigma": p["uncertainty"],
                "lower": p["interval_low"], "upper": p["interval_high"],
                "p_stable": p["stable_probability"], "cost": p["relative_cost"],
                "raw_cost": item["cost"], "novelty": p["novelty"],
                "acquisition": p["acquisition"], "exploration": p["exploration"],
                "relative_cost": p["relative_cost"], "acquisition_weights": p["acquisition_weights"],
                "acquisition_note": p["reason"],
            }
            if item["id"] in state["revealed"]:
                item["reference"] = deepcopy(state["revealed"][item["id"]])
            result.append(item)
        result.extend(deepcopy(list(state["imports"].values())))
        return {"metadata": {**deepcopy(self.payload["metadata"]),
                             "session_reveals": len(state["revealed"]),
                             "model_revision": state["model_revision"],
                             "evidence": "retrospective DFT labels; no new DFT or synthesis",
                             "policy": deepcopy(self.policy or {}),
                             "replay_origin": deepcopy(state["origin"])},
                "candidates": result, "history": deepcopy(state["history"])}

    def reveal(self, state, ids, timestamps=None, *, sequential=False):
        from materialmind.learning import fit_model
        from materialmind.acquisition import rank_candidates
        if any(sid not in self.by_id or self.by_id[sid]["split"] != "test" for sid in ids):
            raise ReplayError("Only held-out catalog candidates have revealable retrospective labels", 400)
        selected_ids = [sid for sid in dict.fromkeys(ids) if sid not in state["revealed"]]
        if not selected_ids:
            return False
        if len(state["batches"]) >= min(MAX_BATCHES, len(self.pool)):
            raise ReplayError("Session refit limit reached. Export this record and start a new session.", 409)
        selected = [self.by_id[sid] for sid in selected_ids]
        known = [r for r in self.records if r["split"] == "train" or r["id"] in state["revealed"]]
        if sequential:
            model = self.model(state)
            before = {row['id']: rank_candidates(model, [row], known + selected[:i], self.policy)[0]
                      for i, row in enumerate(selected)}
        else:
            before = {r["id"]: r for r in rank_candidates(self.model(state), selected, known, self.policy)}
        revealed, history = deepcopy(state["revealed"]), deepcopy(state["history"])
        timestamps = timestamps if timestamps is not None else [time.time() for _ in selected_ids]
        for sid, timestamp in zip(selected_ids, timestamps, strict=True):
            label, p = self.oracle[sid], before[sid]
            revealed[sid] = {"id": sid, "e_above_hull": label, "stable": label <= 0,
                             "source": "previously computed WBM DFT"}
            history.append({**revealed[sid], "step": len(history) + 1,
                            "cost": p["relative_cost"], "timestamp_unix": timestamp,
                            "model_revision_at_selection": state["model_revision"],
                            "prediction_at_selection": {k: p[k] for k in
                                ("predicted_hull", "uncertainty", "interval_low", "interval_high",
                                 "stable_probability", "acquisition", "novelty", "relative_cost",
                                 "acquisition_weights")}})
        model = fit_model(self.train + [self.by_id[h["id"]] for h in history],
                          self.calibration, self.oracle, seed=0)
        state.update({"revealed": revealed, "history": history, "model": model,
                      "model_revision": state["model_revision"] + 1,
                      "batches": state["batches"] + [{"ids": selected_ids, "timestamps_unix": timestamps,
                                                   **({"selection_mode": "sequential"} if sequential else {})}]})
        return True

    @staticmethod
    def imported(sid, structure):
        return {"id": sid, **describe(structure), "split": "import", "prediction": None,
                "prediction_status": IMPORT_STATUS}

    def import_structure(self, state, structure):
        from pymatgen.analysis.structure_matcher import StructureMatcher
        meta = describe(structure)
        matcher = StructureMatcher(ltol=1e-4, stol=1e-4, angle_tol=0.01, scale=False)
        for record in self.pool:
            if record["formula"] == meta["formula"] and matcher.fit(structure, structure_from_record(record)):
                candidate = next(r for r in self.catalog(state)["candidates"] if r["id"] == record["id"])
                return {"candidate": candidate, "matched": True}
        if len(state["imports"]) >= MAX_IMPORTS:
            raise ReplayError(f"A portable session supports at most {MAX_IMPORTS} imported structures.", 409)
        sid = "import-" + secrets.token_hex(6)
        candidate = self.imported(sid, structure)
        state["imports"][sid] = candidate
        return {"candidate": deepcopy(candidate), "matched": False}

    def export(self, state):
        snapshot = self.catalog(state)
        replay = {"contract": deepcopy(self.contract), "batches": deepcopy(state["batches"]),
                  "imports": [{"id": row["id"], "structure": deepcopy(row["structure"])}
                              for row in state["imports"].values()]}
        if state["origin"] is not None:
            replay["origin"] = deepcopy(state["origin"])
        return {"application": "MATERIALMIND LAB", "application_version": __version__,
                "schema_version": 3, "exported_at": datetime.now(timezone.utc).isoformat(),
                "mode": MODE, "metadata": snapshot["metadata"], "candidates": snapshot["candidates"],
                "predictions": [{k: row[k] for k in ("id", "formula", "split", "prediction")}
                                for row in snapshot["candidates"]],
                "revealed_references": snapshot["history"],
                "replay": replay, "replay_sha256": digest(replay)}

    def restore(self, record, *, replay_as_new=False, source_sha256=None):
        schema = record.get("schema_version")
        if type(schema) is not int or schema not in (2, 3):
            raise ReplayError("Unsupported session schema.")
        if not replay_as_new and schema != 3:
            raise ReplayError("Restore requires a schema-3 record. Schema 2 lacks the complete dataset, "
                              "code and runtime compatibility contract needed for exact restoration.")
        if record.get("application") != "MATERIALMIND LAB" or record.get("mode") != MODE:
            raise ReplayError("This is not a MaterialMind retrospective session record.")
        if schema == 3:
            try:
                replay = Replay.model_validate(record.get("replay"))
                actual_digest = digest(record["replay"])
            except (ValidationError, ValueError, TypeError, OverflowError) as error:
                raise ReplayError("Invalid replay manifest: check batches, finite timestamps and bounded geometry.") from error
            if record.get("replay_sha256") != actual_digest:
                raise ReplayError("Replay checksum mismatch. Choose the original unedited export.")
            if replay_as_new:
                validate_source_contract(replay.contract)
            if not replay_as_new and digest(replay.contract) != digest(self.contract):
                raise ReplayError("Replay contract differs from this dataset, policy, code or environment. "
                                  "Use the original compatible installation; the current session is unchanged.", 409)
        else:
            replay = self._legacy_instructions(record)
        if replay_as_new:
            self._validate_record_geometry(record, replay.batches)
            fingerprint = replay.contract.get("fingerprint") if schema == 3 else None
            try:
                origin = ReplayOrigin(kind="replayed_as_new", source_sha256=source_sha256,
                                      source_schema=schema, source_contract_fingerprint=fingerprint,
                                      replayed_at=time.time()).model_dump()
            except ValidationError as error:
                raise ReplayError("Invalid source identity or compatibility fingerprint.") from error
        else:
            origin = replay.origin.model_dump() if replay.origin else None
        seen = set()
        if len(replay.batches) > min(MAX_BATCHES, len(self.pool)):
            raise ReplayError("Replay exceeds the session refit limit.")
        for batch in replay.batches:
            if len(batch.ids) != len(batch.timestamps_unix):
                raise ReplayError("Every reveal needs one original timestamp.")
            for sid in batch.ids:
                if sid in seen or sid not in self.by_id or self.by_id[sid]["split"] != "test":
                    raise ReplayError("Replay IDs must be unique held-out catalog candidates.")
                seen.add(sid)
        restored = new_state()
        restored["origin"] = origin
        for row in replay.imports:
            if row.id in restored["imports"]:
                raise ReplayError("Imported structure IDs must be unique.")
            try:
                structure = structure_from_record({"structure": row.structure.model_dump()})
                restored["imports"][row.id] = self.imported(row.id, structure)
            except Exception as error:
                raise ReplayError("Invalid imported periodic geometry; current session is unchanged.") from error
        for batch in replay.batches:
            self.reveal(restored, batch.ids, batch.timestamps_unix, sequential=batch.selection_mode == "sequential")
        return restored

    def _validate_record_geometry(self, record, batches):
        candidates = record.get("candidates")
        if type(candidates) is not list or len(candidates) > MAX_SAVED_CANDIDATES:
            raise ReplayError("Missing or oversized saved catalog.")
        rows = {}
        for row in candidates:
            if type(row) is not dict or type(row.get("id")) is not str or row["id"] in rows:
                raise ReplayError("Saved catalog IDs must be unique.")
            rows[row["id"]] = row
        for batch in batches:
            for sid in batch.ids:
                current = self.by_id.get(sid)
                if not current or current.get("split") != "test" or sid not in rows:
                    raise ReplayError("A saved candidate is missing from the current held-out catalog.")
                try:
                    if digest(rows[sid].get("structure")) != digest(current["structure"]):
                        raise ReplayError("Saved candidate geometry differs from the current catalog.")
                except (ValueError, TypeError, OverflowError) as error:
                    raise ReplayError("Invalid saved candidate geometry.") from error

    def _legacy_instructions(self, record):
        history = record.get("revealed_references")
        metadata = record.get("metadata")
        candidates = record.get("candidates")
        if type(history) is not list or len(history) > len(self.pool) or type(metadata) is not dict or type(candidates) is not list:
            raise ReplayError("Malformed legacy history or catalog.")
        batches = []
        for step, event in enumerate(history, 1):
            if type(event) is not dict or type(event.get("step")) is not int or event["step"] != step:
                raise ReplayError("Legacy steps must be consecutive.")
            rev = event.get("model_revision_at_selection")
            if type(rev) is not int or rev < 0 or rev > len(batches):
                raise ReplayError("Legacy revision sequence has a gap or decrease.")
            if rev == len(batches): batches.append({"ids": [], "timestamps_unix": []})
            if rev != len(batches)-1: raise ReplayError("Legacy revision sequence has a gap or decrease.")
            batches[-1]["ids"].append(event.get("id"))
            batches[-1]["timestamps_unix"].append(event.get("timestamp_unix"))
        if type(metadata.get("model_revision")) is not int or metadata["model_revision"] != len(batches):
            raise ReplayError("Legacy revision count disagrees with history.")
        imports=[{"id": row.get("id"), "structure": row.get("structure")}
                 for row in candidates if type(row) is dict and row.get("split") == "import"]
        if any(type(row) is not dict or row.get("split") not in ("test", "import") for row in candidates):
            raise ReplayError("Legacy catalog entries need an explicit test or import partition.")
        try:
            return Replay.model_validate({"contract": {}, "batches": batches, "imports": imports})
        except (ValidationError, ValueError, TypeError) as error:
            raise ReplayError("Invalid legacy batches, timestamps or import geometry.") from error
