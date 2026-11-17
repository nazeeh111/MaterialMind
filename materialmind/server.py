"""Local laboratory. The retrospective oracle is never served as a static file."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
import json
import hashlib
from pathlib import Path
import secrets
import threading

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.concurrency import run_in_threadpool

from materialmind import __version__
from materialmind.sessions import MAX_SESSION_BYTES, ReplayError, Session, SessionEngine, new_state
from materialmind.structures import parse_cif, structure_from_record, to_cif

ROOT = Path(__file__).parent


class RevealRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=20)


class BatchRevealRequest(BaseModel):
    count: int = Field(strict=True, ge=1, le=20)
    snapshot: str = Field(pattern=r'^[0-9a-f]{64}$')


class ImportRequest(BaseModel):
    cif: str = Field(min_length=1, max_length=2_000_000)


class BodyLimit:
    """Bound actual bytes before FastAPI parses JSON, including chunked requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        limits = {"/api/session": MAX_SESSION_BYTES, "/api/session/replay": MAX_SESSION_BYTES, "/api/import": 2_100_000,
                  "/api/reveal": 4096, "/api/recommendations/reveal": 4096, "/api/reset": 1024}
        limit = limits.get(scope.get("path"))
        if scope["type"] != "http" or scope.get("method") != "POST" or limit is None:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                return await JSONResponse({"detail": f"Request exceeds the {limit}-byte limit."},
                                          status_code=413)(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        consumed = False

        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


@lru_cache
def load_dataset():
    payload = json.loads((ROOT / "data/candidates.json").read_text())
    oracle = json.loads((ROOT / "data/oracle.json").read_text())
    return payload, oracle


def create_app() -> FastAPI:
    app = FastAPI(title="MATERIALMIND LAB", version=__version__, docs_url="/api/docs")
    app.add_middleware(BodyLimit)
    app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")
    sessions: dict[str, Session] = {}
    registry_lock = threading.Lock()
    fitting_slots = threading.BoundedSemaphore(2)
    engine = SessionEngine(ROOT, load_dataset())

    @app.exception_handler(ReplayError)
    async def replay_error(request, error):
        return error_response(request, str(error), error.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        return error_response(request, error.detail, error.status_code)

    def error_response(request, detail, status):
        response = JSONResponse({"detail": detail}, status_code=status)
        if key := getattr(request.state, "new_session_key", None):
            response.set_cookie("materialmind_session", key, httponly=True, samesite="strict")
        return response

    def session(request: Request, response: Response):
        key = request.cookies.get("materialmind_session")
        with registry_lock:
            if key not in sessions:
                if len(sessions) >= 128:
                    raise HTTPException(503, "Local session capacity reached. Export existing work before restarting the server.")
                key = secrets.token_urlsafe(24)
                sessions[key] = Session()
                request.state.new_session_key = key
                response.set_cookie("materialmind_session", key, httponly=True, samesite="strict")
            return sessions[key]

    @contextmanager
    def fitting():
        if not fitting_slots.acquire(blocking=False):
            raise HTTPException(503, "Two model updates are already running. Try again when one finishes.")
        try:
            yield
        except ReplayError:
            raise
        except Exception as error:
            raise HTTPException(503, "Model reconstruction failed. The current session is unchanged; retry or use another record.") from error
        finally:
            fitting_slots.release()

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web/index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "evidence": "retrospective"}

    @app.get("/api/catalog")
    def get_catalog(request: Request, response: Response):
        owner = session(request, response)
        with owner.lock:
            return engine.catalog(owner.state)

    @app.get('/api/recommendations')
    def recommendations(request: Request, response: Response, count: int = Query(default=5, ge=1, le=20)):
        owner = session(request, response)
        with owner.lock, fitting():
            return engine.recommend(owner.state, count)

    @app.post('/api/recommendations/reveal')
    def reveal_recommendation(value: BatchRevealRequest, request: Request, response: Response):
        owner = session(request, response)
        with owner.lock, fitting():
            ids = engine.reveal_recommendation(owner.state, value.count, value.snapshot)
            return {'results': [deepcopy(owner.state['revealed'][sid]) for sid in ids],
                    'history': deepcopy(owner.state['history']), 'model_updated': True,
                    'model_revision': owner.state['model_revision']}

    @app.get("/api/session")
    def export_session(request: Request, response: Response):
        owner = session(request, response)
        with owner.lock:
            return engine.export(owner.state)

    @app.post("/api/session")
    def restore_session(value: dict, request: Request, response: Response):
        """Replace only this browser's session after complete schema-3 reconstruction."""
        owner = session(request, response)
        with owner.lock, fitting():
            restored = engine.restore(value)
            snapshot = engine.catalog(restored)
            owner.state = restored
            return {"restored": True, **snapshot}

    @app.post("/api/session/replay")
    async def replay_session(value: dict, request: Request, response: Response):
        """Explicitly reconstruct choices with the current model and publish once."""
        source_sha256 = hashlib.sha256(await request.body()).hexdigest()
        owner = session(request, response)
        def reconstruct():
            with owner.lock, fitting():
                restored = engine.restore(value, replay_as_new=True, source_sha256=source_sha256)
                snapshot = engine.catalog(restored)
                owner.state = restored
                return {"replayed": True, **snapshot}
        return await run_in_threadpool(reconstruct)

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
        owner = session(request, response)
        with owner.lock, fitting():
            updated = engine.reveal(owner.state, value.ids)
            return {"results": [owner.state["revealed"][sid].copy() for sid in dict.fromkeys(value.ids)],
                    "history": deepcopy(owner.state["history"]),
                    "model_updated": updated, "model_revision": owner.state["model_revision"]}

    @app.post("/api/reset")
    def reset(request: Request, response: Response):
        owner = session(request, response)
        with owner.lock:
            owner.state = new_state()
        return {"reset": True}

    @app.post("/api/import")
    def import_structure(value: ImportRequest, request: Request, response: Response):
        owner = session(request, response)
        try:
            structure = parse_cif(value.cif)
        except Exception as error:
            raise HTTPException(422, f"Invalid CIF: {str(error)[:240]}") from error
        with owner.lock:
            return engine.import_structure(owner.state, structure)

    @app.get("/api/cif/{sid}")
    def export_cif(sid: str, request: Request, response: Response):
        owner = session(request, response)
        with owner.lock:
            record = next((r for r in engine.pool if r["id"] == sid), None) or owner.state["imports"].get(sid)
            if record is None:
                raise HTTPException(404, "Candidate not found")
            return PlainTextResponse(to_cif(structure_from_record(record)), media_type="chemical/x-cif",
                                     headers={"Content-Disposition": f'attachment; filename="{sid}.cif"'})

    return app
