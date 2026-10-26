"""Build the pinned label-blind WBM study and frozen CHGNet embeddings.

Run from repository root: python scripts/prepare_data.py --raw ../../work/research
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

INPUTS = {
    "wbm-initial.jsonl.gz": ("53161835", "b809f101dd42a745ec2baabe7eb16f11"),
    "wbm-summary.csv.gz": ("64706751", "1555268d3aa59d20262cb9d01ce0994b"),
    "chgnet.csv.gz": ("66646268", "fd7cd3781a24be465aaeadf97663ce58"),
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--size", type=int, default=3072)
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], default="cpu")
    parser.add_argument("--output", type=Path, default=Path("materialmind/data"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, (file_id, md5) in INPUTS.items():
        data = (args.raw / name).read_bytes()
        if hashlib.md5(data).hexdigest() != md5:
            raise ValueError(f"Checksum mismatch: {name}")
        manifest[name] = {"url": f"https://ndownloader.figshare.com/files/{file_id}",
                          "md5": md5, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    print("Pinned source checksums verified", flush=True)

    import numpy as np
    import pandas as pd
    import torch
    from chgnet.model.model import CHGNet
    from pymatgen.core import Structure
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from materialmind.structures import describe, geometric_features, validate_structure

    torch.set_num_threads(2)
    # Deterministic input-only eligibility and hash ordering. Label columns are not read yet.
    eligible = []
    with gzip.open(args.raw / "wbm-initial.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            value = row.get("initial_structure", row.get("structure"))
            if not value or not 2 <= len(value.get("sites", [])) <= 24:
                continue
            elements = {sp["element"] for site in value["sites"] for sp in site["species"]}
            if 2 <= len(elements) <= 4:
                eligible.append((digest("materialmind-v1:" + row["material_id"]), row))
    eligible.sort(key=lambda item: item[0])
    print(f"Input-only eligible structures: {len(eligible)}", flush=True)
    records, structures, rejected = [], [], []
    buckets = {}
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=True, scale=True)
    for _, row in eligible:
        if len(records) >= args.size:
            break
        sid = row["material_id"]
        try:
            struct = Structure.from_dict(row["initial_structure"])
            validate_structure(struct, max_sites=24)
            formula = struct.composition.reduced_formula
            # Duplicate decisions depend only on input geometry, never reference labels.
            if any(matcher.fit(struct, previous) for previous in buckets.get(formula, [])):
                rejected.append({"id": sid, "reason": "initial StructureMatcher duplicate"})
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                meta = describe(struct)
            group_score = int(digest("materialmind-split-v1:" + meta["chemistry_group"])[:12], 16) / 16**12
            split = "train" if group_score < 0.45 else "calibration" if group_score < 0.62 else "development" if group_score < 0.80 else "test"
            records.append({"id": sid, **meta, "split": split})
            structures.append(struct)
            buckets.setdefault(formula, []).append(struct)
        except (ValueError, TypeError, KeyError) as error:
            rejected.append({"id": sid, "reason": str(error)})
    print("Frozen subset and chemical-system split", {s: sum(r['split'] == s for r in records) for s in ['train','calibration','development','test']}, flush=True)
    selected_ids = {r["id"] for r in records}
    (args.output / "selection.json").write_text(json.dumps({"ids": sorted(selected_ids), "rejected": rejected}, indent=2))

    # Reference labels enter only after the input-only sample and split are persisted.
    summary = pd.read_csv(args.raw / "wbm-summary.csv.gz").set_index("material_id")
    predictions = pd.read_csv(args.raw / "chgnet.csv.gz").set_index("material_id")
    model = CHGNet.load(model_name="0.3.0", use_device=args.device)
    model.eval()
    embedding_cache = args.output / "embedding-cache.json"
    cache = json.loads(embedding_cache.read_text()) if embedding_cache.exists() else {}
    started = time.perf_counter()
    failures = []
    for idx in range(0, len(records), 16):
        missing = [j for j in range(idx, min(idx + 16, len(records))) if records[j]["id"] not in cache]
        if missing:
            try:
                values = model.predict_structure([structures[j] for j in missing], task="e", return_crystal_feas=True, batch_size=16)
                if isinstance(values, dict): values = [values]
                for j, value in zip(missing, values, strict=True):
                    cache[records[j]["id"]] = np.asarray(value["crystal_fea"], dtype=float).tolist()
            except Exception as error:
                # Failure is retained and excluded explicitly, never replaced with fabricated features.
                for j in missing: failures.append({"id": records[j]["id"], "error": str(error)})
            embedding_cache.write_text(json.dumps(cache))
        if idx % 128 == 0: print(f"Embeddings {idx}/{len(records)}, {time.perf_counter()-started:.1f}s", flush=True)
    oracle, final = {}, []
    for record, structure in zip(records, structures, strict=True):
        sid = record["id"]
        if sid not in cache or sid not in summary.index or sid not in predictions.index:
            failures.append({"id": sid, "error": "embedding or source join missing"})
            continue
        ref = summary.loc[sid]
        label = float(ref["e_above_hull_mp2020_corrected_ppd_mp"])
        hull = float(ref["e_form_per_atom_mp2020_corrected"]) - label
        eform = float(predictions.loc[sid, "e_form_per_atom"])
        if not np.isfinite([label, hull, eform]).all():
            failures.append({"id": sid, "error": "nonfinite source energy"})
            continue
        record.update({"predicted_hull": eform - hull,
                       "reference_hull_formation_energy": hull,
                       "pretrained_formation_energy": eform,
                       "features": cache[sid] + geometric_features(structure),
                       "initial_prototype": str(ref.get("protostructure_spglib_initial_structure", "unavailable"))})
        oracle[sid] = label
        final.append(record)
    split_groups = {s: sorted({r['chemistry_group'] for r in final if r['split'] == s}) for s in ['train','calibration','development','test']}
    prototype_sets = {s: {r['initial_prototype'].split(':', 1)[0] for r in final if r['split'] == s} for s in split_groups}
    metadata = {
        "name": "WBM-3072 input-only small-cell study", "version": "1.0", "license": "CC-BY-4.0",
        "source_article": "https://doi.org/10.6084/m9.figshare.22715158", "inputs": manifest,
        "selection": "sha256(materialmind-v1:ID); ordered initial cells, 2–4 elements, 2–24 sites; input StructureMatcher deduplication",
        "split": "sha256(materialmind-split-v1:chemical-system); 45%/17%/18%/20% thresholds",
        "split_counts": {s: sum(r['split']==s for r in final) for s in split_groups},
        "chemical_systems": split_groups,
        "prototype_train_test_overlap": len(prototype_sets['train'] & prototype_sets['test']),
        "prototype_overlap_scope": "Anonymous initial prototypes (chemical suffix removed); this is chemical-system holdout, not prototype holdout",
        "prototype_overlap_pairs": {f"{a}:{b}": len(prototype_sets[a] & prototype_sets[b])
                                    for a in split_groups for b in split_groups if a < b},
        "pretraining_overlap": "MPtrj contains prototypes overlapping WBM; independent pretraining generalization is not established",
        "embedding_model": f"CHGNet 0.3.0 frozen, {args.device}, 64-dimensional crystal feature from initial structure",
        "features": "64 frozen CHGNet graph features plus 20 initial-only cell/composition descriptors",
        "target": "signed distance to fixed MP2020-corrected DFT hull, eV/atom; stable <= 0",
        "cost": "1 + (initial_nsites/16)^3; synthetic evaluation cost proxy, not measured DFT runtime",
        "feature_seconds": time.perf_counter()-started,
        "failures": failures, "not_official_blind_benchmark": True,
    }
    (args.output / "candidates.json").write_text(json.dumps({"metadata": metadata, "candidates": final}, separators=(",", ":")))
    (args.output / "oracle.json").write_text(json.dumps(oracle, sort_keys=True))
    (args.output / "provenance.json").write_text(json.dumps(metadata, indent=2))
    embedding_cache.unlink()  # embeddings are now persisted in candidates.json
    print(f"Saved {len(final)} candidates, {len(failures)} failures", flush=True)


if __name__ == "__main__":
    main()
