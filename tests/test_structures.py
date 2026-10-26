import numpy as np
import pytest
from pymatgen.core import Lattice, Structure
from materialmind.structures import describe, geometric_features, parse_cif, to_cif, validate_structure


def nacl():
    return Structure(Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [.5, .5, .5]])


def test_cif_roundtrip_preserves_periodic_structure():
    source = nacl()
    actual = parse_cif(to_cif(source))
    assert actual.composition == source.composition
    assert actual.volume == pytest.approx(source.volume, rel=1e-6)
    assert sorted(actual.distance_matrix.flatten()) == pytest.approx(sorted(source.distance_matrix.flatten()))


def test_periodic_overlap_and_disorder_rejected():
    with pytest.raises(ValueError, match="overlap"):
        validate_structure(Structure(Lattice.cubic(5), ["Na", "Cl"], [[0, 0, 0], [.9999, 0, 0]]))
    with pytest.raises(ValueError, match="occupancies"):
        validate_structure(Structure(Lattice.cubic(5), [{"Na": .5, "K": .5}], [[0, 0, 0]]))


def test_features_are_initial_geometry_only_and_finite():
    features = geometric_features(nacl())
    assert len(features) == 20 and np.isfinite(features).all()
    meta = describe(nacl())
    assert meta["chemistry_group"] == "Cl-Na"
    assert meta["cost"] == pytest.approx(1 + (2 / 16) ** 3)
    assert not {"reference_hull", "stable", "reference"} & meta.keys()


def test_bad_cif_fails_explicitly():
    with pytest.raises(Exception):
        parse_cif("this is not a CIF")


def test_skew_cell_periodic_self_images_rejected():
    lattice = Lattice([[5, 0, 0], [4.9, .1, 0], [0, 0, 5]])
    with pytest.raises(ValueError, match="overlap"):
        validate_structure(Structure(lattice, ["Si"], [[0, 0, 0]]))
