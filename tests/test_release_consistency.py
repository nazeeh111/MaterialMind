"""Verify that the live laboratory starts from the released research model."""
import json
import numpy as np
from fastapi.testclient import TestClient
from materialmind.server import ROOT, create_app


def test_live_initial_predictions_match_frozen_research_outputs():
    frozen = json.loads((ROOT / "artifacts/predictions.json").read_text())["predictions"]
    by_id = {r["id"]: r for r in frozen}
    with TestClient(create_app()) as client:
        response = client.get("/api/catalog")
        assert response.status_code == 200
        for candidate in response.json()["candidates"]:
            actual, expected = candidate["prediction"], by_id[candidate["id"]]
            assert np.allclose([actual["mean"], actual["lower"], actual["upper"], actual["p_stable"]],
                               [expected["predicted_hull"], expected["interval_low"], expected["interval_high"], expected["stable_probability"]],
                               rtol=0, atol=1e-12)
        report = client.get("/api/report")
        assert report.status_code == 200 and "29.6 [29.1, 30.1]" in report.text
