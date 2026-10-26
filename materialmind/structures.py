"""Initial-geometry validation and features. No reference outcomes enter here."""
from __future__ import annotations

import hashlib
import json
import warnings

import numpy as np
from pymatgen.core import Structure
from pymatgen.io.cif import CifParser, CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


def validate_structure(structure: Structure, *, max_sites: int = 256) -> None:
    if not 1 <= len(structure) <= max_sites:
        raise ValueError(f"Structure must have 1–{max_sites} sites")
    if not structure.is_ordered:
        raise ValueError("Partial occupancies are unsupported; supply an ordered structure")
    if not np.isfinite(structure.lattice.matrix).all() or not np.isfinite(structure.frac_coords).all():
        raise ValueError("Lattice and coordinates must be finite")
    if structure.volume < 1 or abs(np.linalg.det(structure.lattice.matrix)) < 1e-5:
        raise ValueError("Cell is singular or has implausibly small volume")
    if structure.volume / len(structure) > 1000:
        raise ValueError("Cell exceeds 1,000 Å³ per atom; check units")
    if np.linalg.cond(structure.lattice.matrix) > 1e6:
        raise ValueError("Lattice is numerically ill-conditioned; check cell vectors")
    # A skew cell can have a short a-b translation even if every basis vector
    # is long. Include periodic self-images, not only distinct site pairs.
    shortest_translation = min(structure.lattice.get_niggli_reduced_lattice().abc)
    distances = structure.distance_matrix.copy()
    np.fill_diagonal(distances, np.inf)
    if np.min(distances) < 0.55 or shortest_translation < 0.55:
        raise ValueError("Periodic sites overlap (<0.55 Å); check cell and coordinates")
    if any(not getattr(site.specie, "Z", None) for site in structure):
        raise ValueError("Every site must be a chemical element")


def parse_cif(text: str) -> Structure:
    if len(text.encode()) > 2_000_000:
        raise ValueError("CIF exceeds the 2 MB limit")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        structures = CifParser.from_str(text).parse_structures(primitive=False)
    if len(structures) != 1:
        raise ValueError("Import exactly one structure per CIF")
    structure = structures[0]
    validate_structure(structure)
    return structure


def to_cif(structure: Structure) -> str:
    return str(CifWriter(structure))


def structure_from_record(record: dict) -> Structure:
    value = record["structure"]
    if "@module" in value:
        return Structure.from_dict(value)
    return Structure(value["lattice"], [site["element"] for site in value["sites"]],
                     [site["frac"] for site in value["sites"]])


def describe(structure: Structure) -> dict:
    validate_structure(structure)
    symmetry = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5)
    elements = sorted(str(e) for e in structure.composition.elements)
    return {
        "formula": structure.composition.reduced_formula,
        "nsites": len(structure), "elements": elements,
        "chemistry_group": "-".join(elements),
        "spacegroup": symmetry.get_space_group_symbol(),
        "spacegroup_number": symmetry.get_space_group_number(),
        "crystal_system": symmetry.get_crystal_system(),
        "volume": float(structure.volume), "density": float(structure.density),
        "cost": float(1 + (len(structure) / 16) ** 3),
        "structure": {"lattice": structure.lattice.matrix.tolist(),
                      "sites": [{"element": str(site.specie), "frac": (site.frac_coords % 1).tolist()} for site in structure]},
    }


def fingerprint(structure: Structure) -> str:
    """Invariant coarse key for exact-distance duplicates; StructureMatcher confirms."""
    distances = np.sort(structure.distance_matrix[np.triu_indices(len(structure), 1)])
    payload = [structure.composition.reduced_formula, len(structure),
               round(structure.volume, 3), np.round(distances, 3).tolist()]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def geometric_features(structure: Structure) -> list[float]:
    """20 initial-only cell/composition/periodic-neighbor descriptors."""
    atoms = [site.specie for site in structure]
    z = np.array([e.Z for e in atoms], dtype=float)
    chi = np.array([e.X if e.X is not None else 0 for e in atoms], dtype=float)
    radii = np.array([float(e.atomic_radius or 1.5) for e in atoms])
    dist = structure.distance_matrix.copy()
    np.fill_diagonal(dist, np.inf)
    nearest = np.min(dist, axis=1) if len(structure) > 1 else np.array(structure.lattice.abc)
    fractions = np.array(list(structure.composition.fractional_composition.values()))
    abc = np.array(structure.lattice.abc)
    return [float(v) for v in [len(structure), len(fractions), structure.volume / len(structure),
            structure.density, z.mean(), z.std(), z.min(), z.max(), chi.mean(), chi.std(),
            radii.mean(), radii.std(), nearest.mean(), nearest.std(), nearest.min(),
            np.max(abc) / np.min(abc), *np.array(structure.lattice.angles) / 180,
            -np.sum(fractions * np.log(fractions))]]
