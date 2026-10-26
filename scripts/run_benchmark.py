"""Run the complete development fit and frozen test benchmark from local data."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from materialmind.benchmark import run_study, audit_results

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("materialmind/data/candidates.json"))
    parser.add_argument("--oracle", type=Path, default=Path("materialmind/data/oracle.json"))
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--budget", type=int, default=40)
    parser.add_argument("--frozen-policy", type=Path, help="Resume with an already-frozen development policy; no coefficient refit")
    parser.add_argument("--audit-only", action="store_true", help="Verify existing result artifacts against local source data")
    args = parser.parse_args()
    dataset = json.loads(args.data.read_text())
    oracle = json.loads(args.oracle.read_text())
    if "labels" in oracle:
        oracle = oracle["labels"]
    if args.audit_only:
        print(json.dumps(audit_results(dataset["candidates"], oracle, args.output), indent=2))
        return
    summary = run_study(dataset["candidates"], oracle, args.output, args.seeds, args.budget,
                        frozen_policy=args.frozen_policy)
    audit_results(dataset["candidates"], oracle, args.output)
    print(json.dumps({"runtime_seconds": summary["runtime_seconds"], "policy": summary["policy"],
                      "materialmind": summary["methods"]["materialmind"]["stable_at_cost_budget"]}, indent=2))

if __name__ == "__main__":
    main()
