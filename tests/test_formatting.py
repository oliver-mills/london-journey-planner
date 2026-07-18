from tube_planner.formatting import display_name


def test_simple_station_name():
    assert display_name("OXFORD CIRCUS") == "Oxford Circus"


def test_hyphenated_station_name():
    assert display_name("HARROW-ON-THE-HILL") == "Harrow-on-the-Hill"


def test_ampersand_line_name():
    assert display_name("WATERLOO & CITY") == "Waterloo & City"


def test_curated_apostrophe_override():
    assert display_name("KINGS CROSS ST PANCRAS") == "King's Cross St. Pancras"
    assert display_name("ST PAULS") == "St. Paul's"


def test_parenthetical_station_name():
    assert display_name("KENSINGTON (OLYMPIA)") == "Kensington (Olympia)"
