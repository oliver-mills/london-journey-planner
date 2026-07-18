"""Official TfL line colours, keyed by the same line names used in the
station graph and returned by the TfL status API."""

LINE_COLOURS: dict[str, str] = {
    "Bakerloo": "#B36305",
    "Central": "#E32017",
    "Circle": "#FFD300",
    "District": "#00782A",
    "Hammersmith & City": "#F3A9BB",
    "Jubilee": "#A0A5A9",
    "Metropolitan": "#9B0056",
    "Northern": "#000000",
    "Piccadilly": "#003688",
    "Victoria": "#0098D4",
    "Waterloo & City": "#95CDBA",
    "East London": "#FFA100",
}

DEFAULT_LINE_COLOUR = "#6A6A6A"


def colour_for(line: str) -> str:
    return LINE_COLOURS.get(line, DEFAULT_LINE_COLOUR)
