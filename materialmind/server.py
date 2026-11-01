"""Local laboratory. The retrospective oracle is never served as a static file."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import secrets
import threading
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from materialmind import __version__
from materialmind.structures import describe, parse_cif, structure_from_record, to_cif

ROOT = Path(__file__).parent


class RevealRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=20)


class ImportRequest(BaseModel):
    cif: str = Field(min_length=1, max_length=2_000_000)


@lru_cache
def load_dataset():
    payload = json.loads((ROOT / "data/candidates.json").read_text())
    oracle = json.loads((ROOT / "data/oracle.json").read_text())
    return payload, oracle


def create_app() -> FastAPI:
    app = FastAPI(title="MATERIALMIND LAB", version=__version__, docs_url="/api/docs")
    app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")
    sessions: dict[str, dict] = {}
    lock = threading.RLock()

    def session(request: Request, response: Response):
        key = request.cookies.get("materialmind_session")
        with lock:
            if key not in sessions:
                if len(sessions) >= 128:
                    oldest = min(sessions, key=lambda k: sessions[k]["created"])
                    del sessions[oldest]
                key = secrets.token_urlsafe(24)
                sessions[key] = {"created": time.time(), "revealed": {}, "imports": {}, "model": None, "history": [], "model_revision": 0}
                response.set_cookie("materialmind_session", key, httponly=True, samesite="strict")
            return sessions[key]

    def initial_model():
        from materialmind.learning import fit_model
        payload, oracle = load_dataset()
        records = payload["candidates"]
        return fit_model(sorted([r for r in records if r["split"] == "train"], key=lambda r: r["id"]),
                         sorted([r for r in records if r["split"] == "calibration"], key=lambda r: r["id"]), oracle, seed=0)

    model_cache = {}

    def get_model(state):
        with lock:
            if state["model"] is None:
                if "initial" not in model_cache:
                    model_cache["initial"] = initial_model()
                state["model"] = model_cache["initial"]
            return state["model"]

    def catalog(state):
        from materialmind.learning import predict
        from materialmind.acquisition import rank_candidates
        payload, _ = load_dataset()
        pool = [r for r in payload["candidates"] if r["split"] == "test"]
        model = get_model(state)
        policy_path = ROOT / "artifacts/policy.json"
        policy = json.loads(policy_path.read_text()) if policy_path.exists() else {}
        known = [r for r in payload["candidates"] if r["split"] == "train" or r["id"] in state["revealed"]]
        predictions = rank_candidates(model, pool, known, policy if policy else None)
        pred_by_id = {p["id"]: p for p in predictions}
        result = []
        for record in pool:
            item = {k: deepcopy(v) for k, v in record.items() if k not in {"features", "initial_prototype"}}
            p = pred_by_id[item["id"]]
            mean = float(p.get("mean", p.get("predicted_hull")))
            sigma = float(p.get("sigma", p.get("uncertainty")))
            probability = float(p.get("p_stable", p.get("stable_probability")))
            item["prediction"] = {"mean": mean, "sigma": sigma,
                "lower": float(p.get("lower", p.get("interval_low", mean-1.645*sigma))),
                "upper": float(p.get("upper", p.get("interval_high", mean+1.645*sigma))),
                "p_stable": probability, "cost": p["relative_cost"], "raw_cost": item["cost"], "novelty": p["novelty"],
                "acquisition": p["acquisition"], "exploration": p["exploration"],
                "relative_cost": p["relative_cost"], "acquisition_weights": p["acquisition_weights"],
                "acquisition_note": p["reason"]}
            if item["id"] in state["revealed"]:
                item["reference"] = state["revealed"][item["id"]]
            result.append(item)
        # Imports that did not match a reference record have geometry only.
        result.extend(state["imports"].values())
        return {"metadata": {**payload["metadata"], "session_reveals": len(state["revealed"]),
                            "model_revision": state["model_revision"],
                            "evidence": "retrospective DFT labels; no new DFT or synthesis", "policy": policy},
                "candidates": result, "history": state["history"]}

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web/index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "evidence": "retrospective"}

    @app.get("/api/catalog")
    def get_catalog(request: Request, response: Response):
        state = session(request, response)
        with lock:
            return deepcopy(catalog(state))

    @app.get("/api/session")
    def export_session(request: Request, response: Response):
        """A consistent portable snapshot, including geometry for new imports."""
        state = session(request, response)
        with lock:
            snapshot = deepcopy(catalog(state))
            return {"application": "MATERIALMIND LAB", "application_version": __version__,
                    "schema_version": 2, "exported_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "retrospective_reference_replay", "metadata": snapshot["metadata"],
                    "candidates": snapshot["candidates"],
                    "predictions": [{k: row[k] for k in ("id", "formula", "split", "prediction")}
                                    for row in snapshot["candidates"]],
                    "revealed_references": snapshot["history"]}

    @app.get("/api/benchmark")
    def benchmark():
        path = ROOT / "artifacts/summary.json"
        if not path.exists():
            return {"metadata": {"status": "not_run"}, "curves": [], "summary": []}
        return json.loads(path.read_text())

    @app.get("/api/report")
    def analysis_report():
        from materialmind.reporting import render_report
        path = ROOT / "artifacts/summary.json"
        if not path.exists():
            raise HTTPException(404, "No saved experiment report is available")
        return PlainTextResponse(render_report(json.loads(path.read_text()), load_dataset()[0]["metadata"]),
                                 media_type="text/markdown",
                                 headers={"Content-Disposition": 'attachment; filename="materialmind-analysis.md"'})

    @app.post("/api/reveal")
    def reveal(value: RevealRequest, request: Request, response: Response):
        from materialmind.learning import fit_model
        from materialmind.acquisition import rank_candidates
        state = session(request, response)
        payload, oracle = load_dataset()
        by_id = {r["id"]: r for r in payload["candidates"]}
        # Validate the full batch before mutating the session.
        if any(sid not in by_id or by_id[sid]["split"] != "test" for sid in value.ids):
            raise HTTPException(400, "Only held-out catalog candidates have revealable retrospective labels")
        results = []
        with lock:
            selected = [by_id[sid] for sid in dict.fromkeys(value.ids) if sid not in state["revealed"]]
            known = [r for r in payload["candidates"] if r["split"] == "train" or r["id"] in state["revealed"]]
            policy_path = ROOT / "artifacts/policy.json"
            policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
            before = {r["id"]: r for r in rank_candidates(get_model(state), selected, known, policy)}
            # Prepare everything before publishing any new label or history entry.
            # A failed fit must leave the session exactly as it was.
            revealed = deepcopy(state["revealed"])
            history = deepcopy(state["history"])
            for sid in dict.fromkeys(value.ids):
                if sid not in revealed:
                    label = oracle[sid]
                    revealed[sid] = {"id": sid, "e_above_hull": label, "stable": label <= 0,
                                              "source": "previously computed WBM DFT"}
                    p = before[sid]
                    history.append({**revealed[sid], "step": len(history) + 1,
                        "cost": p["relative_cost"], "timestamp_unix": time.time(),
                        "model_revision_at_selection": state["model_revision"],
                        "prediction_at_selection": {k: p[k] for k in ("predicted_hull", "uncertainty", "interval_low", "interval_high",
                            "stable_probability", "acquisition", "novelty", "relative_cost", "acquisition_weights")}})
                results.append(revealed[sid])
            if selected:
                train = sorted([r for r in payload["candidates"] if r["split"] == "train"], key=lambda r: r["id"])
                train += [by_id[h["id"]] for h in history]
                calibration = sorted([r for r in payload["candidates"] if r["split"] == "calibration"], key=lambda r: r["id"])
                updated_model = fit_model(train, calibration, oracle, seed=0)
                state.update({"revealed": revealed, "history": history, "model": updated_model,
                              "model_revision": state["model_revision"] + 1})
            return {"results": deepcopy(results), "history": deepcopy(state["history"]),
                    "model_updated": bool(selected), "model_revision": state["model_revision"]}

    @app.post("/api/reset")
    def reset(request: Request, response: Response):
        state = session(request, response)
        with lock:
            state.update({"revealed": {}, "imports": {}, "model": None, "history": [], "model_revision": 0})
        return {"reset": True}

    @app.post("/api/import")
    def import_structure(value: ImportRequest, request: Request, response: Response):
        from pymatgen.analysis.structure_matcher import StructureMatcher
        state = session(request, response)
        try:
            struct = parse_cif(value.cif)
            meta = describe(struct)
        except Exception as error:
            raise HTTPException(422, f"Invalid CIF: {str(error)[:240]}") from error
        payload, _ = load_dataset()
        # Reuse cached evidence only for equivalent periodic geometry. Loose
        # prototype matching (especially volume scaling) is not sufficient.
        matcher = StructureMatcher(ltol=1e-4, stol=1e-4, angle_tol=0.01, scale=False)
        for record in payload["candidates"]:
            if record["split"] == "test" and record["formula"] == meta["formula"]:
                if matcher.fit(struct, structure_from_record(record)):
                    with lock:
                        candidate = next(r for r in catalog(state)["candidates"] if r["id"] == record["id"])
                    return {"candidate": candidate, "matched": True}
        sid = "import-" + secrets.token_hex(6)
        candidate = {"id": sid, **meta, "split": "import", "prediction": None,
                     "prediction_status": "Geometry validated. Stability unavailable: no compatible cached relaxed prediction and DFT reference hull. Use the Python adapter for a documented reference workflow."}
        with lock:
            state["imports"][sid] = candidate
        return {"candidate": candidate, "matched": False}

    @app.get("/api/cif/{sid}")
    def export_cif(sid: str, request: Request, response: Response):
        state = session(request, response)
        payload, _ = load_dataset()
        record = next((r for r in payload["candidates"] if r["id"] == sid and r["split"] == "test"), None)
        record = record or state["imports"].get(sid)
        if record is None:
            raise HTTPException(404, "Candidate not found")
        return PlainTextResponse(to_cif(structure_from_record(record)), media_type="chemical/x-cif",
                                 headers={"Content-Disposition": f'attachment; filename="{sid}.cif"'})

    return app
