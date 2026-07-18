import sqlite3

import pytest

from tube_planner import reviews


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE stations (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY,
            station_id INTEGER NOT NULL REFERENCES stations(id),
            author TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("INSERT INTO stations (name) VALUES ('OXFORD CIRCUS')")
    conn.commit()
    conn.close()
    return path


def test_add_and_fetch_review(db_path):
    reviews.add_review("OXFORD CIRCUS", "Alex", 5, "Great interchange", db_path=db_path)

    result = reviews.reviews_for_station("OXFORD CIRCUS", db_path=db_path)

    assert len(result) == 1
    assert result[0].author == "Alex"
    assert result[0].rating == 5
    assert result[0].comment == "Great interchange"


def test_blank_author_defaults_to_anonymous(db_path):
    reviews.add_review("OXFORD CIRCUS", "  ", 3, "It's fine", db_path=db_path)

    result = reviews.reviews_for_station("OXFORD CIRCUS", db_path=db_path)

    assert result[0].author == "Anonymous"


def test_rejects_out_of_range_rating(db_path):
    with pytest.raises(ValueError):
        reviews.add_review("OXFORD CIRCUS", "Alex", 6, "Too high", db_path=db_path)


def test_rejects_empty_comment(db_path):
    with pytest.raises(ValueError):
        reviews.add_review("OXFORD CIRCUS", "Alex", 4, "   ", db_path=db_path)


def test_unknown_station_raises(db_path):
    with pytest.raises(reviews.UnknownStationError):
        reviews.add_review("NOWHERE", "Alex", 4, "Nice", db_path=db_path)


def test_most_recent_review_first(db_path):
    reviews.add_review("OXFORD CIRCUS", "Alex", 3, "First", db_path=db_path)
    reviews.add_review("OXFORD CIRCUS", "Sam", 4, "Second", db_path=db_path)

    result = reviews.reviews_for_station("OXFORD CIRCUS", db_path=db_path)

    assert [r.comment for r in result] == ["Second", "First"]
