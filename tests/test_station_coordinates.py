"""Covers the name matching that joins our station names to TfL's.

This is the fiddly part of the coordinate pipeline: the two sources spell the
same station quite differently, and a silent mismatch means a station simply
vanishes from the map.
"""
from scripts.fetch_station_coordinates import match, normalise


def test_normalise_strips_the_underground_station_boilerplate():
    assert normalise("Blackhorse Road Underground Station") == "BLACKHORSE ROAD"


def test_normalise_drops_apostrophes_and_periods():
    assert normalise("King's Cross St. Pancras Underground Station") == "KINGS CROSS ST PANCRAS"
    assert normalise("St Paul's Underground Station") == "ST PAULS"


def test_normalise_spells_out_ampersands():
    assert normalise("Harrow & Wealdstone") == "HARROW AND WEALDSTONE"
    assert normalise("HARROW & WEALDSTONE") == normalise("Harrow & Wealdstone")


def test_normalise_removes_parenthetical_qualifiers():
    # Our graph models both Edgware Road stations as one node, so the
    # qualifiers have to collapse onto a single key.
    assert normalise("Edgware Road (Circle Line)") == "EDGWARE ROAD"
    assert normalise("Edgware Road (Bakerloo)") == "EDGWARE ROAD"


def test_normalise_matches_both_sides_of_the_join():
    assert normalise("HAMMERSMITH") == normalise("Hammersmith (Dist&Picc Line)")


def test_match_pairs_stations_with_their_position():
    stops = {"ACTON TOWN": {"tfl_name": "Acton Town", "lat": 51.5, "lon": -0.28, "zone": "3"}}
    matched, unmatched = match(["ACTON TOWN"], stops)

    assert unmatched == []
    assert matched == {"ACTON TOWN": {"lat": 51.5, "lon": -0.28, "zone": "3"}}


def test_match_applies_the_curated_aliases():
    """Renamed stations only resolve through the hand-built alias table."""
    stops = {
        "WALTHAMSTOW CENTRAL": {
            "tfl_name": "Walthamstow Central",
            "lat": 51.58,
            "lon": -0.02,
            "zone": "3",
        }
    }
    matched, unmatched = match(["WALTHAMSTOW"], stops)

    assert unmatched == []
    assert matched["WALTHAMSTOW"]["lat"] == 51.58


def test_match_reports_stations_it_cannot_place():
    matched, unmatched = match(["NOWHERE PARTICULAR"], {})
    assert matched == {}
    assert unmatched == ["NOWHERE PARTICULAR"]
