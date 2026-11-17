"""API checks use explicit synthetic fixtures, never scientific benchmark outcomes."""
from copy import deepcopy
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pymatgen.core import Lattice, Structure
import materialmind.server as server
from materialmind.structures import describe, to_cif


@pytest.fixture
def client(monkeypatch):
    records, labels = [], {}
    rng = np.random.default_rng(1)
    for split, size in (("train", 12), ("calibration", 12), ("development", 6), ("test", 6)):
        for i in range(size):
            sid = f"{split}-{i}"
            structure = Structure(Lattice.cubic(5 + i * .2), ["Na", "Cl"], [[0, 0, 0], [.5, .5, .5]])
            row = {"id": sid, **describe(structure), "split": split, "features": rng.normal(size=5).tolist(), "predicted_hull": .02}
            records.append(row)
            labels[sid] = float(i * .01 - .02)
    monkeypatch.setattr(server, "load_dataset", lambda: ({"metadata": {"test_fixture": True}, "candidates": deepcopy(records)}, labels))
    app = server.create_app()
    with TestClient(app) as current:
        yield current


def test_catalog_keeps_labels_hidden_and_assets_bounded(client):
    response = client.get("/api/catalog")
    assert response.status_code == 200
    rows = response.json()["candidates"]
    assert len(rows) == 6
    assert all(r["split"] == "test" for r in rows)
    assert all(not {"reference", "e_above_hull", "stable", "features"} & r.keys() for r in rows)
    assert client.get("/assets/../data/oracle.json").status_code == 404
    assert client.get("/api/cif/train-0").status_code == 404


def test_reveal_refits_and_invalid_batch_does_not_partially_mutate(client):
    client.get("/api/catalog")
    assert client.post("/api/reveal", json={"ids": ["test-0", "train-0"]}).status_code == 400
    assert client.get("/api/catalog").json()["history"] == []
    result = client.post("/api/reveal", json={"ids": ["test-0"]}).json()
    assert result["model_updated"] is True and result["results"][0]["stable"] is True
    after = client.get("/api/catalog").json()
    assert len(after["history"]) == 1
    assert "prediction_at_selection" in after["history"][0]
    assert after["history"][0]["prediction_at_selection"]["acquisition_weights"]
    # Repeating the same reveal is idempotent and cannot inflate discovery counts.
    client.post("/api/reveal", json={"ids": ["test-0"]})
    assert len(client.get("/api/catalog").json()["history"]) == 1
    client.post("/api/reset")
    assert client.get("/api/catalog").json()["history"] == []


def test_cif_matching_and_unknown_composition_evidence(client):
    original = client.get("/api/cif/test-0")
    assert original.status_code == 200
    imported = client.post("/api/import", json={"cif": original.text}).json()
    assert imported["matched"] is True
    scaled = Structure(Lattice.cubic(10), ["Na", "Cl"], [[0, 0, 0], [.5, .5, .5]])
    assert client.post("/api/import", json={"cif": to_cif(scaled)}).json()["matched"] is False
    unknown = Structure(Lattice.cubic(4.0), ["Si"], [[0, 0, 0]])
    imported = client.post("/api/import", json={"cif": to_cif(unknown)}).json()
    assert imported["matched"] is False and imported["candidate"]["prediction"] is None
    sid = imported["candidate"]["id"]
    assert client.get(f"/api/cif/{sid}").status_code == 200
    assert client.post("/api/reveal", json={"ids": [sid]}).status_code == 400
    assert client.post("/api/import", json={"cif": "not a CIF"}).status_code == 422


def test_failed_refit_preserves_model_labels_and_history(client, monkeypatch):
    import materialmind.learning as learning
    initial = client.get("/api/catalog").json()
    fit = learning.fit_model

    def fail(*args, **kwargs):
        raise RuntimeError("simulated fit failure")

    monkeypatch.setattr(learning, "fit_model", fail)
    assert client.post("/api/reveal", json={"ids": ["test-0", "test-1"]}).status_code == 503
    assert client.get("/api/catalog").json() == initial
    monkeypatch.setattr(learning, "fit_model", fit)
    result = client.post("/api/reveal", json={"ids": ["test-0", "test-1"]}).json()
    assert result["model_updated"] and result["model_revision"] == 1
    assert [h["step"] for h in result["history"]] == [1, 2]


def test_session_export_preserves_import_geometry_and_only_revealed_labels(client):
    structure = Structure(Lattice.cubic(4), ["Si"], [[0, 0, 0]])
    imported = client.post("/api/import", json={"cif": to_cif(structure)}).json()["candidate"]
    client.post("/api/reveal", json={"ids": ["test-0"]})
    record = client.get("/api/session").json()
    assert record["schema_version"] == 3
    assert record["metadata"]["model_revision"] == 1
    assert [r["id"] for r in record["revealed_references"]] == ["test-0"]
    by_id = {r["id"]: r for r in record["candidates"]}
    assert by_id[imported["id"]] == imported
    from materialmind.structures import structure_from_record
    assert np.allclose(structure_from_record(by_id[imported["id"]]).lattice.matrix, structure.lattice.matrix)
    assert all("reference" not in row for sid, row in by_id.items() if sid != "test-0")
    assert all("features" not in row for row in by_id.values())
    client.post("/api/reset")
    reset = client.get("/api/session").json()
    assert reset["metadata"]["model_revision"] == 0 and reset["revealed_references"] == []
    assert imported["id"] not in {r["id"] for r in reset["candidates"]}
    # The downloaded record retains all geometry even after the live reset.
    assert by_id[imported["id"]]["structure"] == imported["structure"]


def exported(client):
    response = client.get("/api/session")
    assert response.status_code == 200
    return response.json()


def rehash(record):
    from materialmind.sessions import digest
    record["replay_sha256"] = digest(record["replay"])
    return record


def test_restore_replays_batches_exactly_and_can_continue(client):
    structure = Structure(Lattice.cubic(4), ["Si"], [[0, 0, 0]])
    imported = client.post("/api/import", json={"cif": to_cif(structure)}).json()["candidate"]
    revealed = client.post("/api/reveal", json={"ids": ["test-2", "test-0", "test-2"]}).json()
    assert [r["id"] for r in revealed["results"]] == ["test-2", "test-0"]
    client.post("/api/reveal", json={"ids": ["test-0", "test-3"]})
    before = client.get("/api/catalog").json()
    record = exported(client)
    assert [b["ids"] for b in record["replay"]["batches"]] == [["test-2", "test-0"], ["test-3"]]
    client.post("/api/reveal", json={"ids": ["test-5"]})
    continued = client.get("/api/catalog").json()
    client.post("/api/reset")
    restored = client.post("/api/session", json=record)
    assert restored.status_code == 200
    assert restored.json() == {"restored": True, **before}
    assert client.get(f'/api/cif/{imported["id"]}').status_code == 200
    client.post("/api/reveal", json={"ids": ["test-5"]})
    resumed = client.get("/api/catalog").json()
    # New selections have new wall-clock times, but identical scientific state.
    resumed["history"][-1]["timestamp_unix"] = continued["history"][-1]["timestamp_unix"]
    assert resumed == continued
    assert client.post("/api/session", json=record).status_code == 200
    assert client.get("/api/catalog").json() == before


def test_restore_into_new_session_does_not_affect_original(client):
    client.post("/api/reveal", json={"ids": ["test-1", "test-4"]})
    record, original_cookie = exported(client), client.cookies.get("materialmind_session")
    client.cookies.clear()
    assert client.get("/api/catalog").json()["history"] == []
    assert client.post("/api/session", json=record).status_code == 200
    assert client.cookies.get("materialmind_session") != original_cookie
    assert len(client.get("/api/catalog").json()["history"]) == 2
    client.post("/api/reset")
    client.cookies.set("materialmind_session", original_cookie)
    assert len(client.get("/api/catalog").json()["history"]) == 2


def test_uploaded_predictions_labels_metadata_and_ui_context_are_not_authority(client):
    client.post("/api/reveal", json={"ids": ["test-1"]})
    before, record = client.get("/api/catalog").json(), exported(client)
    record["revealed_references"] = [{"id": "test-5", "e_above_hull": -999}]
    record["metadata"] = {"model_revision": 8000}
    record["candidates"] = [{"id": "test-5", "reference": {"e_above_hull": -999}}]
    record["predictions"] = [{"id": "test-0", "prediction": {"mean": -999}}]
    record["filters"] = {"search": "<script>not executable</script>"}
    client.post("/api/reset")
    assert client.post("/api/session", json=record).status_code == 200
    assert client.get("/api/catalog").json() == before
    assert all("reference" not in row for row in before["candidates"] if row["id"] != "test-1")


@pytest.mark.parametrize("mutation,status", [
    (lambda r: r.update(schema_version=2), 422),
    (lambda r: r.update(schema_version=True), 422),
    (lambda r: r.update(application="another app"), 422),
    (lambda r: r["replay"]["batches"][0]["ids"].append("test-5"), 422),
    (lambda r: r["replay"]["contract"].update(seed=1), 422),
])
def test_invalid_or_edited_records_do_not_mutate_session(client, mutation, status):
    client.post("/api/reveal", json={"ids": ["test-0"]})
    before, record = client.get("/api/catalog").json(), exported(client)
    mutation(record)
    assert client.post("/api/session", json=record).status_code == status
    assert client.get("/api/catalog").json() == before


@pytest.mark.parametrize("field", ["dataset_sha256", "policy_sha256", "source_sha256", "dependencies", "runtime", "seed"])
def test_stale_contract_is_rejected_even_with_recomputed_checksum(client, field):
    record = exported(client)
    before = client.get("/api/catalog").json()
    record["replay"]["contract"][field] = "different"
    assert client.post("/api/session", json=rehash(record)).status_code == 409
    assert client.get("/api/catalog").json() == before


@pytest.mark.parametrize("ids", [
    ["train-0"], ["calibration-0"], ["development-0"], ["missing"],
    ["test-0", "test-0"], ["test-0"] * 21,
])
def test_invalid_replay_ids_are_rejected_before_any_refit(client, monkeypatch, ids):
    import materialmind.learning as learning
    record, before = exported(client), client.get("/api/catalog").json()
    record["replay"]["batches"] = [{"ids": ids, "timestamps_unix": [1.] * len(ids)}]
    def fail(*args, **kwargs):
        pytest.fail("invalid manifest must be rejected before fitting")
    monkeypatch.setattr(learning, "fit_model", fail)
    assert client.post("/api/session", json=rehash(record)).status_code == 422
    assert client.get("/api/catalog").json() == before


def test_repeated_ids_across_batches_and_malformed_imports_are_atomic(client):
    client.post("/api/reveal", json={"ids": ["test-0"]})
    before, original = client.get("/api/catalog").json(), exported(client)
    duplicate = deepcopy(original)
    duplicate["replay"]["batches"] *= 2
    assert client.post("/api/session", json=rehash(duplicate)).status_code == 422
    for structure in (
        {"lattice": [[0., 0., 0.]] * 3, "sites": [{"element": "Si", "frac": [0., 0., 0.]}]},
        {"@module": "os", "@class": "system", "command": "never execute"},
        {"lattice": np.eye(3).tolist(), "sites": [{"element": "NotAnElement", "frac": [0., 0., 0.]}]},
        {"lattice": np.eye(3).tolist(), "sites": [{"element": "Si", "frac": [0., 0., 0.]}] * 257},
    ):
        record = deepcopy(original)
        record["replay"]["imports"] = [{"id": "import-abcdef012345", "structure": structure}]
        assert client.post("/api/session", json=rehash(record)).status_code == 422
        assert client.get("/api/catalog").json() == before


def test_failed_second_restore_refit_preserves_entire_existing_session(client, monkeypatch):
    import materialmind.learning as learning
    client.post("/api/reveal", json={"ids": ["test-0", "test-1"]})
    client.post("/api/reveal", json={"ids": ["test-2"]})
    record = exported(client)
    client.post("/api/reset")
    client.post("/api/reveal", json={"ids": ["test-5"]})
    structure = Structure(Lattice.cubic(4), ["Si"], [[0, 0, 0]])
    client.post("/api/import", json={"cif": to_cif(structure)})
    before, fit, calls = client.get("/api/catalog").json(), learning.fit_model, []
    def fail_second(*args, **kwargs):
        calls.append([r["id"] for r in args[0]])
        if len(calls) == 2:
            raise RuntimeError("fault injection")
        return fit(*args, **kwargs)
    monkeypatch.setattr(learning, "fit_model", fail_second)
    assert client.post("/api/session", json=record).status_code == 503
    assert [ids[-2:] for ids in calls] == [["test-0", "test-1"], ["test-1", "test-2"]]
    assert client.get("/api/catalog").json() == before
    monkeypatch.setattr(learning, "fit_model", fit)
    assert client.post("/api/session", json=record).status_code == 200


def test_byte_limits_cover_chunked_requests_and_preserve_state(client, monkeypatch):
    before = client.get("/api/catalog").json()
    monkeypatch.setattr(server, "MAX_SESSION_BYTES", 1024)
    # The middleware resolves limits per request, so the test need not allocate 16 MiB.
    response = client.post("/api/session", content=iter([b" " * 700, b" " * 700]),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert client.post("/api/reveal", content=b" " * 4097).status_code == 413
    assert client.post("/api/import", content=b" " * 2_100_001).status_code == 413
    assert client.get("/api/catalog").json() == before


def test_sessions_do_not_share_fit_lock_and_same_session_remains_serial(client, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import materialmind.learning as learning
    client.get("/api/catalog")
    first_cookie = client.cookies.get("materialmind_session")
    client.cookies.clear()
    client.get("/api/catalog")
    second_cookie = client.cookies.get("materialmind_session")
    fit, entered, release = learning.fit_model, threading.Event(), threading.Event()
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10), "test did not release fit"
        return fit(*args, **kwargs)
    monkeypatch.setattr(learning, "fit_model", blocked)
    with ThreadPoolExecutor(max_workers=3) as pool:
        future = pool.submit(client.post, "/api/reveal", json={"ids": ["test-0"]},
                             headers={"cookie": f"materialmind_session={first_cookie}"})
        assert entered.wait(10)
        try:
            unrelated = pool.submit(client.get, "/api/catalog",
                                    headers={"cookie": f"materialmind_session={second_cookie}"})
            assert unrelated.result(timeout=5).json()["history"] == []
            pending = threading.Event()
            def reset_first():
                pending.set()
                return client.post("/api/reset", headers={"cookie": f"materialmind_session={first_cookie}"})
            reset = pool.submit(reset_first)
            assert pending.wait(5)
            assert not reset.done()
        finally:
            release.set()
        assert future.result(timeout=10).status_code == 200
        assert reset.result(timeout=10).status_code == 200
    assert client.get("/api/catalog", headers={"cookie": f"materialmind_session={first_cookie}"}).json()["history"] == []


def test_busy_fitting_capacity_rejects_third_update_without_mutation(client, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import materialmind.learning as learning
    cookies = []
    for _ in range(3):
        client.cookies.clear()
        client.get("/api/catalog")
        cookies.append({"cookie": f'materialmind_session={client.cookies.get("materialmind_session")}'})
    fit, release, both_entered = learning.fit_model, threading.Event(), threading.Barrier(3)
    def blocked(*args, **kwargs):
        both_entered.wait(timeout=10)
        assert release.wait(10)
        return fit(*args, **kwargs)
    monkeypatch.setattr(learning, "fit_model", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, "/api/reveal", json={"ids": ["test-0"]}, headers=cookie)
                   for cookie in cookies[:2]]
        try:
            both_entered.wait(timeout=10)
            result = client.post("/api/reveal", json={"ids": ["test-1"]}, headers=cookies[2])
            assert result.status_code == 503 and "already running" in result.json()["detail"]
            assert client.get("/api/catalog", headers=cookies[2]).json()["history"] == []
        finally:
            release.set()
        assert all(f.result(timeout=10).status_code == 200 for f in futures)


def test_replay_resource_bounds_and_annotations_are_validated(client):
    import json
    before, original = client.get("/api/catalog").json(), exported(client)
    geometry = describe(Structure(Lattice.cubic(4), ["Si"], [[0, 0, 0]]))["structure"]
    cases = [
        {"batches": [{"ids": ["test-0"], "timestamps_unix": [1.]}] * 7},
        {"batches": [{"ids": ["test-0"], "timestamps_unix": [1., 2.]}]},
        {"batches": [{"ids": ["test-0"], "timestamps_unix": [-1.]}]},
        {"batches": [{"ids": ["test-0"], "timestamps_unix": [float("nan")]}]},
        {"batches": [{"ids": ["test-0"], "timestamps_unix": [float("inf")]}]},
        {"batches": [{"ids": ["test-0"], "timestamps_unix": [True]}]},
        {"batches": [{"ids": ["test-0"], "timestamps_unix": [1.], "label": -999}]},
        {"imports": [{"id": f"import-{i:012x}", "structure": geometry} for i in range(33)]},
        {"imports": [{"id": "import-000000000001", "structure": geometry}] * 2},
        {"imports": [{"id": "../../data/oracle", "structure": geometry}]},
    ]
    for update in cases:
        record = deepcopy(original)
        record["replay"].update(update)
        # Nonfinite JSON must fail validation even before checksum verification.
        try:
            rehash(record)
        except ValueError:
            pass
        response = client.post("/api/session", content=json.dumps(record), headers={"content-type": "application/json"})
        assert response.status_code == 422
        assert client.get("/api/catalog").json() == before


def test_import_capacity_is_enforced_on_live_sessions(client, monkeypatch):
    import materialmind.sessions as sessions
    monkeypatch.setattr(sessions, "MAX_IMPORTS", 1)
    cif = to_cif(Structure(Lattice.cubic(4), ["Si"], [[0, 0, 0]]))
    assert client.post("/api/import", json={"cif": cif}).status_code == 200
    before = client.get("/api/catalog").json()
    assert client.post("/api/import", json={"cif": cif}).status_code == 409
    assert client.get("/api/catalog").json() == before


def test_invalid_first_restore_retains_new_session_cookie_and_empty_restore_works(client):
    assert client.post("/api/session", json={}).status_code == 422
    cookie = client.cookies.get("materialmind_session")
    assert cookie
    record, before = exported(client), client.get("/api/catalog").json()
    assert client.post("/api/session", json=record).status_code == 200
    assert client.cookies.get("materialmind_session") == cookie
    assert client.get("/api/catalog").json() == before


def test_restore_catalog_generation_failure_does_not_publish_rebuilt_state(client, monkeypatch):
    import materialmind.acquisition as acquisition
    client.post("/api/reveal", json={"ids": ["test-0", "test-1"]})
    record = exported(client)
    client.post("/api/reset")
    before, rank = client.get("/api/catalog").json(), acquisition.rank_candidates
    def fail_final_catalog(model, pool, *args, **kwargs):
        if len(pool) == 6:
            raise RuntimeError("final response generation failed")
        return rank(model, pool, *args, **kwargs)
    monkeypatch.setattr(acquisition, "rank_candidates", fail_final_catalog)
    assert client.post("/api/session", json=record).status_code == 503
    monkeypatch.setattr(acquisition, "rank_candidates", rank)
    assert client.get("/api/catalog").json() == before


def test_session_capacity_never_evicts_existing_research(client):
    client.post("/api/reveal", json={"ids": ["test-0"]})
    cookie, before = client.cookies.get("materialmind_session"), client.get("/api/catalog").json()
    for _ in range(127):
        client.cookies.clear()
        assert client.post("/api/reset").status_code == 200
    client.cookies.clear()
    assert client.post("/api/reset").status_code == 503
    client.cookies.set("materialmind_session", cookie)
    assert client.get("/api/catalog").json() == before


def _legacy_from_current(record):
    result=deepcopy(record)
    result['schema_version']=2
    result.pop('replay');result.pop('replay_sha256')
    return result


def test_explicit_legacy_replay_recomputes_and_persists_origin(client):
    import hashlib,json
    structure=Structure(Lattice.cubic(4),['Si'],[[0,0,0]])
    imported=client.post('/api/import',json={'cif':to_cif(structure)}).json()['candidate']
    client.post('/api/reveal',json={'ids':['test-3','test-1','test-3']})
    client.post('/api/reveal',json={'ids':['test-1']})
    client.post('/api/reveal',json={'ids':['test-1','test-4']})
    fresh=client.get('/api/catalog').json();legacy=_legacy_from_current(client.get('/api/session').json())
    assert client.post('/api/reset').status_code==200
    before=client.get('/api/catalog').json()
    assert client.post('/api/session',json=legacy).status_code==422
    assert client.get('/api/catalog').json()==before
    for row in legacy['revealed_references']:
        row['e_above_hull']=999;row['cost']=999;row['prediction_at_selection']={'forged':True}
    for row in legacy['candidates']:row['prediction']={'forged':True}
    raw=json.dumps(legacy,separators=(',',':')).encode()
    response=client.post('/api/session/replay',content=raw,headers={'content-type':'application/json'})
    assert response.status_code==200,response.text
    replayed=response.json();assert replayed['candidates']==fresh['candidates']
    assert replayed['history']==fresh['history']
    origin=replayed['metadata']['replay_origin'];assert origin['kind']=='replayed_as_new' and origin['source_schema']==2
    assert origin['source_sha256']==hashlib.sha256(raw).hexdigest() and origin['source_contract_fingerprint'] is None
    assert any(r['id']==imported['id'] and r['structure']==imported['structure'] for r in replayed['candidates'])
    exported=client.get('/api/session').json();assert [x['ids'] for x in exported['replay']['batches']]==[['test-3','test-1'],['test-4']]
    assert client.post('/api/reset').status_code==200
    assert client.post('/api/session',json=exported).status_code==200
    assert client.post('/api/reveal',json={'ids':['test-5']}).status_code==200
    assert client.get('/api/session').json()['replay']['origin']==origin


def test_stale_current_replay_and_atomic_refusals(client,monkeypatch):
    from materialmind.sessions import digest,SessionEngine
    import materialmind.learning as learning
    client.get('/api/catalog');client.post('/api/reveal',json={'ids':['test-0']})
    record=client.get('/api/session').json();record['replay']['contract']['runtime']['python']='0.0.0';contract=record['replay']['contract'];contract['fingerprint']=digest({k:v for k,v in contract.items() if k!='fingerprint'});record['replay_sha256']=digest(record['replay'])
    before=client.get('/api/catalog').json()
    assert client.post('/api/session',json=record).status_code==409
    assert client.get('/api/catalog').json()==before
    assert client.post('/api/session/replay',json=record).status_code==200
    replayed=client.get('/api/catalog').json();assert replayed['metadata']['replay_origin']['source_schema']==3
    corrupt=deepcopy(record);corrupt['replay_sha256']='0'*64
    assert client.post('/api/session/replay',json=corrupt).status_code==422
    assert client.get('/api/catalog').json()==replayed
    bad=deepcopy(record);bad['candidates'][0]['structure']['lattice'][0][0]+=1
    assert client.post('/api/session/replay',json=bad).status_code==422
    assert client.get('/api/catalog').json()==replayed
    original_fit=learning.fit_model
    def fail(*args,**kwargs):raise RuntimeError('synthetic failure')
    monkeypatch.setattr(learning,'fit_model',fail)
    assert client.post('/api/session/replay',json=record).status_code==503
    monkeypatch.setattr(learning,'fit_model',original_fit)
    assert client.get('/api/catalog').json()==replayed
    original_catalog=SessionEngine.catalog
    def fail_catalog(self,state):raise RuntimeError('synthetic catalog failure')
    monkeypatch.setattr(SessionEngine,'catalog',fail_catalog)
    assert client.post('/api/session/replay',json=record).status_code==503
    monkeypatch.setattr(SessionEngine,'catalog',original_catalog)
    assert client.get('/api/catalog').json()==replayed
    assert client.post('/api/session/replay',json=record).status_code==200


@pytest.mark.parametrize('kind',['gap','decrease','step','duplicate','missing','timestamp','import'])
def test_legacy_malformed_replay_is_atomic(client,kind):
    client.get('/api/catalog');client.post('/api/reveal',json={'ids':['test-0']});client.post('/api/reveal',json={'ids':['test-1']})
    record=_legacy_from_current(client.get('/api/session').json());history=record['revealed_references']
    if kind=='gap':history[1]['model_revision_at_selection']=3
    if kind=='decrease':history[1]['model_revision_at_selection']=0
    if kind=='step':history[1]['step']=3
    if kind=='duplicate':history[1]['id']=history[0]['id']
    if kind=='missing':history[1]['id']='not-in-catalog'
    if kind=='timestamp':history[1]['timestamp_unix']=-1
    if kind=='import':record['candidates'].append({'id':'import-aaaaaaaaaaaa','split':'import','structure':{'lattice':[],'sites':[]}})
    before=client.get('/api/catalog').json();response=client.post('/api/session/replay',json=record)
    assert response.status_code==422,(kind,response.text)
    assert client.get('/api/catalog').json()==before


def test_middle_refit_failure_keeps_prior_session_and_retry_succeeds(client,monkeypatch):
    import materialmind.learning as learning
    client.get('/api/catalog');client.post('/api/reveal',json={'ids':['test-0']});client.post('/api/reveal',json={'ids':['test-1']})
    legacy=_legacy_from_current(client.get('/api/session').json());before=client.get('/api/catalog').json()
    actual=learning.fit_model;count=0
    def fail_second(*args,**kwargs):
        nonlocal count
        count+=1
        if count==2:raise RuntimeError('middle replay refit failed')
        return actual(*args,**kwargs)
    monkeypatch.setattr(learning,'fit_model',fail_second)
    assert client.post('/api/session/replay',json=legacy).status_code==503 and count==2
    monkeypatch.setattr(learning,'fit_model',actual)
    assert client.get('/api/catalog').json()==before
    assert client.post('/api/session/replay',json=legacy).status_code==200


def test_replay_body_limit_is_enforced(client):
    from materialmind.sessions import MAX_SESSION_BYTES
    before=client.get('/api/catalog').json()
    response=client.post('/api/session/replay',content=b' '* (MAX_SESSION_BYTES+1),headers={'content-type':'application/json'})
    assert response.status_code==413
    assert client.get('/api/catalog').json()==before


def test_replay_refuses_identifiable_legacy_import_with_missing_partition(client):
    unknown=Structure(Lattice.cubic(4.0),["Si"],[[0,0,0]])
    assert client.post('/api/import',json={'cif':to_cif(unknown)}).status_code==200
    record=_legacy_from_current(client.get('/api/session').json())
    imported=next(row for row in record['candidates'] if row['split']=='import')
    del imported['split']
    before=client.get('/api/catalog').json()
    result=client.post('/api/session/replay',json=record)
    assert result.status_code==422 and client.get('/api/catalog').json()==before


@pytest.mark.parametrize('field',['empty','source','dependencies','runtime','seed'])
def test_stale_replay_requires_complete_compatibility_identity(client,field):
    from materialmind.sessions import digest
    client.post('/api/reveal',json={'ids':['test-0']})
    record=client.get('/api/session').json();contract=record['replay']['contract']
    if field=='empty':contract.clear()
    elif field=='source':contract['source_sha256']={}
    elif field=='dependencies':contract['dependencies']={}
    elif field=='runtime':contract['runtime']={}
    elif field=='seed':contract['seed']=True
    contract['fingerprint']=digest({key:value for key,value in contract.items() if key!='fingerprint'})
    record['replay_sha256']=digest(record['replay'])
    before=client.get('/api/catalog').json()
    assert client.post('/api/session/replay',json=record).status_code==422
    assert client.get('/api/catalog').json()==before


def test_replay_preserves_selected_decisions_when_unselected_old_catalog_rows_are_absent(client):
    client.post('/api/reveal',json={'ids':['test-0','test-2']})
    current=client.get('/api/catalog').json()
    record=_legacy_from_current(client.get('/api/session').json())
    for number in range(40):
        row=deepcopy(record['candidates'][0]);row['id']=f'old-unselected-{number}'
        record['candidates'].append(row)
    assert client.post('/api/reset').status_code==200
    result=client.post('/api/session/replay',json=record)
    assert result.status_code==200,result.text
    assert result.json()['candidates']==current['candidates']
    assert result.json()['history']==current['history']
