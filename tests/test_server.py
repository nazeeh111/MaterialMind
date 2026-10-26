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
