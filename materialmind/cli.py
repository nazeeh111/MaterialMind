"""Command-line entry point for the laboratory and reproducible experiments."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="materialmind", description="Retrospective crystal discovery laboratory")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Open the local scientific laboratory")
    serve.add_argument("--port", type=int, default=8765)
    bench = sub.add_parser("benchmark", help="Reproduce the frozen retrospective study")
    bench.add_argument("--out", type=Path, default=Path("local-runs/reproduction"))
    bench.add_argument("--seeds", type=int, default=10)
    bench.add_argument("--budget", type=int, default=40)
    inspect = sub.add_parser("inspect", help="Validate a CIF and print initial geometry metadata")
    inspect.add_argument("cif", type=Path)
    rank = sub.add_parser("rank", help="Rank the held-out catalog without revealing reference labels")
    rank.add_argument("--top", type=int, default=20)
    rank.add_argument("--out", type=Path)
    report = sub.add_parser("report", help="Export a measured analysis report from the released study")
    report.add_argument("--out", type=Path)
    sub.add_parser("provenance", help="Print the dataset provenance and limitations")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        from materialmind.server import create_app
        print(f"MATERIALMIND LAB · http://127.0.0.1:{args.port} · retrospective evidence")
        uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)
    elif args.command == "benchmark":
        from materialmind.benchmark import run_study
        from materialmind.server import load_dataset
        payload, oracle = load_dataset()
        result = run_study(payload["candidates"], oracle, args.out, seeds=args.seeds, budget=args.budget)
        print(json.dumps(result.get("metadata", {"output": str(args.out)}), indent=2))
    elif args.command == "inspect":
        from materialmind.structures import describe, parse_cif
        value = describe(parse_cif(args.cif.read_text()))
        value.pop("structure")
        print(json.dumps(value, indent=2))
    elif args.command == "rank":
        from materialmind.server import ROOT, load_dataset
        from materialmind.learning import fit_model
        from materialmind.acquisition import rank_candidates
        payload, oracle = load_dataset()
        records = payload["candidates"]
        train = sorted([r for r in records if r["split"] == "train"], key=lambda r: r["id"])
        calibration = sorted([r for r in records if r["split"] == "calibration"], key=lambda r: r["id"])
        model = fit_model(train, calibration, oracle, seed=0)
        policy = json.loads((ROOT / "artifacts/policy.json").read_text())
        ranked = rank_candidates(model, [r for r in records if r["split"] == "test"], train, policy)
        fields = ("id", "formula", "predicted_hull", "interval_low", "interval_high",
                  "stable_probability", "acquisition", "relative_cost", "novelty")
        result = [{k: row[k] for k in fields} for row in ranked[:max(0, args.top)]]
        text = json.dumps(result, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n")
        else:
            print(text)
    elif args.command == "report":
        from materialmind.reporting import render_report
        from materialmind.server import ROOT, load_dataset
        text = render_report(json.loads((ROOT / "artifacts/summary.json").read_text()), load_dataset()[0]["metadata"])
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text)
        else:
            print(text)
    else:
        from materialmind.server import load_dataset
        print(json.dumps(load_dataset()[0]["metadata"], indent=2))


if __name__ == "__main__":
    main()
