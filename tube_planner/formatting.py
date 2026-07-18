"""Turns the ALL-CAPS station names used internally (and by the raw source
data, which strips punctuation) into their proper display form."""

_LOWERCASE_WORDS = {"on", "the", "of", "and"}

# The source spreadsheet strips all punctuation, so names that officially
# carry an apostrophe or a period can't be recovered generically. Curated
# by hand against TfL's official station names.
_DISPLAY_OVERRIDES = {
    "EARLS COURT": "Earl's Court",
    "KINGS CROSS ST PANCRAS": "King's Cross St. Pancras",
    "QUEENS PARK": "Queen's Park",
    "REGENTS PARK": "Regent's Park",
    "SHEPHERDS BUSH": "Shepherd's Bush",
    "ST JAMES PARK": "St. James's Park",
    "ST JOHNS WOOD": "St. John's Wood",
    "ST PAULS": "St. Paul's",
}


def _format_word(word: str, index: int) -> str:
    if word == "&":
        return "&"
    if index > 0 and word.lower() in _LOWERCASE_WORDS:
        return word.lower()
    if "-" in word:
        parts = word.split("-")
        return "-".join(
            part.lower() if i > 0 and part.lower() in _LOWERCASE_WORDS else part.capitalize()
            for i, part in enumerate(parts)
        )
    if word.startswith("(") and word.endswith(")"):
        return "(" + word[1:-1].capitalize() + ")"
    return word.capitalize()


def display_name(raw: str) -> str:
    if raw in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[raw]
    return " ".join(_format_word(word, i) for i, word in enumerate(raw.split(" ")))
