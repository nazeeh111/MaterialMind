"""Frozen-artifact integrity controls; no fitting or study rerun."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from materialmind.benchmark import METHODS, audit_results

ROOT = Path(__file__).resolve().parents[1] / "materialmind"
FIELDS = ("stable_at_budget", "stable_at_cost_budget")


class SummaryAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidates = json.loads((ROOT / "data/candidates.json").read_text())["candidates"]
        cls.labels = json.loads((ROOT / "data/oracle.json").read_text())
        cls.labels = cls.labels.get("labels", cls.labels)
        cls.files = {name: (ROOT / "artifacts" / name).read_bytes()
                     for name in ("summary.json", "traces.json", "policy.json", "model.joblib")}

    def refuse_without_writes(self, mutate, message):
        with tempfile.TemporaryDirectory(prefix="materialmind-summary-test-") as directory:
            output = Path(directory)
            for name, data in self.files.items():
                (output / name).write_bytes(data)
            (output / "audit.json").write_text('{"prior_receipt":"keep exact bytes"}\n')
            summary = json.loads((output / "summary.json").read_text())
            traces = json.loads((output / "traces.json").read_text())
            mutate(summary, traces)
            (output / "summary.json").write_text(json.dumps(summary) + "\n")
            (output / "traces.json").write_text(json.dumps(traces) + "\n")
            def fingerprints():
                return {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in output.rglob("*") if p.is_file()}
            before = fingerprints()
            with self.assertRaisesRegex(ValueError, message):
                audit_results(self.candidates, self.labels, output)
            self.assertEqual(fingerprints(), before)

    def test_every_method_axis_mean_and_interval_endpoint(self):
        for method in METHODS:
            for field in FIELDS:
                for component in ("mean", 0, 1):
                    with self.subTest(method=method, field=field, component=component):
                        def mutate(summary, _traces):
                            metric = summary["methods"][method][field]
                            if component == "mean":
                                metric["mean"] += 1
                            else:
                                metric["ci95"][component] += 1
                        self.refuse_without_writes(mutate, f"{method}.{field}")

    def test_original_summary_passes_without_replacing_discovery_values(self):
        with tempfile.TemporaryDirectory(prefix="materialmind-valid-summary-") as directory:
            output = Path(directory)
            for name, data in self.files.items():
                (output / name).write_bytes(data)
            before = json.loads(self.files["summary.json"])["methods"]
            with patch("materialmind.benchmark.plot_results"):
                audit = audit_results(self.candidates, self.labels, output)
            self.assertTrue(audit["passed"])
            self.assertEqual(json.loads((output / "summary.json").read_text())["methods"], before)

    def test_finite_large_json_integers_have_metric_specific_refusals(self):
        for value in (2 ** 64 - 1, 2 ** 64, 2 ** 64 + 1):
            for field in FIELDS:
                for component in ("mean", 0, 1):
                    with self.subTest(value=value, field=field, component=component):
                        def mutate(summary, _traces):
                            metric = summary["methods"]["random"][field]
                            if component == "mean":
                                metric["mean"] = value
                            else:
                                metric["ci95"][component] = value
                        self.refuse_without_writes(mutate, f"random.{field}")

    def test_malformed_and_nonfinite_headlines(self):
        invalid = [None, [], {"mean": 1, "ci95": [0]}, {"mean": 1, "ci95": [0, 1, 2]},
                   {"mean": True, "ci95": [0, 1]}, {"mean": 10 ** 1000, "ci95": [0, 1]},
                   {"mean": 1, "ci95": [False, 1]}, {"mean": "1", "ci95": [0, 1]},
                   {"mean": float("nan"), "ci95": [0, 1]},
                   {"mean": 1, "ci95": [float("inf"), 1]},
                   {"mean": 1, "ci95": [0, None]}, {"ci95": [0, 1]}]
        for metric in invalid:
            with self.subTest(metric=metric):
                self.refuse_without_writes(
                    lambda summary, _traces: summary["methods"]["random"].__setitem__(FIELDS[0], metric),
                    "Invalid summary metric: random.stable_at_budget")

    def test_missing_extra_or_malformed_method_coverage(self):
        for action in (lambda s: s.pop("methods"),
                       lambda s: s["methods"].pop("random"),
                       lambda s: s["methods"].__setitem__("invented", {}),
                       lambda s: s.__setitem__("methods", [])):
            self.refuse_without_writes(lambda summary, _traces: action(summary), "method coverage")

    def test_observation_and_cost_refusals_still_precede_summary_verification(self):
        for key in ("reference_hull", "cumulative_cost"):
            def mutate(_summary, traces):
                traces["episodes"][0]["history"][0][key] += 1
            self.refuse_without_writes(mutate, "source reference|budgets")


if __name__ == "__main__":
    unittest.main()
