import pytest

from tube_planner.geo import Position, haversine_km, mercator, project


def test_haversine_matches_known_distance():
    # Bank to Waterloo is about 2.1 km as the crow flies.
    bank = Position(lat=51.5133, lon=-0.0886)
    waterloo = Position(lat=51.5036, lon=-0.1143)
    assert haversine_km(bank, waterloo) == pytest.approx(2.1, abs=0.15)


def test_haversine_is_zero_for_the_same_point():
    point = Position(lat=51.5, lon=-0.1)
    assert haversine_km(point, point) == 0.0


def test_haversine_is_symmetric():
    a = Position(lat=51.5, lon=-0.1)
    b = Position(lat=51.6, lon=-0.3)
    assert haversine_km(a, b) == pytest.approx(haversine_km(b, a))


def test_mercator_puts_the_origin_at_zero():
    x, y = mercator(0.0, 0.0)
    assert x == pytest.approx(0.0, abs=1e-12)
    assert y == pytest.approx(0.0, abs=1e-12)


def test_mercator_y_grows_northward():
    _, south = mercator(51.0, 0.0)
    _, north = mercator(52.0, 0.0)
    assert north > south


def test_project_fits_within_the_padded_box():
    positions = {
        "A": Position(lat=51.4, lon=-0.5),
        "B": Position(lat=51.7, lon=0.2),
        "C": Position(lat=51.5, lon=-0.1),
    }
    network = project(positions, width=1000.0, padding=40.0)

    assert network.width == 1000.0
    for point in network.points.values():
        assert 40.0 - 0.01 <= point.x <= 960.0 + 0.01
        assert 40.0 - 0.01 <= point.y <= network.height - 40.0 + 0.01


def test_project_spans_the_full_width():
    positions = {
        "west": Position(lat=51.5, lon=-0.5),
        "east": Position(lat=51.5, lon=0.2),
    }
    network = project(positions, width=1000.0, padding=40.0)

    assert network.points["west"].x == pytest.approx(40.0)
    assert network.points["east"].x == pytest.approx(960.0)


def test_project_flips_the_y_axis_so_north_is_up():
    positions = {
        "north": Position(lat=51.7, lon=-0.2),
        "south": Position(lat=51.4, lon=0.1),
    }
    network = project(positions)
    assert network.points["north"].y < network.points["south"].y


def test_project_scales_both_axes_equally():
    """The map must not be stretched: one scale factor for x and for y."""
    positions = {
        "sw": Position(lat=51.3, lon=-0.5),
        "ne": Position(lat=51.7, lon=0.3),
    }
    network = project(positions, width=1000.0, padding=0.0)

    (raw_x1, raw_y1) = mercator(51.3, -0.5)
    (raw_x2, raw_y2) = mercator(51.7, 0.3)

    drawn = network.points
    scale_x = abs(drawn["ne"].x - drawn["sw"].x) / abs(raw_x2 - raw_x1)
    scale_y = abs(drawn["ne"].y - drawn["sw"].y) / abs(raw_y2 - raw_y1)
    assert scale_x == pytest.approx(scale_y, rel=1e-3)


def test_project_handles_an_empty_network():
    network = project({})
    assert network.points == {}
    assert network.width > 0


def test_project_handles_a_single_station():
    network = project({"only": Position(lat=51.5, lon=-0.1)})
    assert list(network.points) == ["only"]
