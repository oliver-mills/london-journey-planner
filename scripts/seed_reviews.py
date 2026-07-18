"""Seeds a handful of demo reviews so the app isn't empty on first run.

Run with: python scripts/seed_reviews.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tube_planner import reviews  # noqa: E402
from tube_planner.graph import load_graph  # noqa: E402

DEMO_REVIEWS = [
    ("CANARY WHARF", "Zoe", 5, "Skyline views from the platform are unbeatable."),
    ("CANARY WHARF", "Ethan", 4, "Modern station, always feels a bit corporate."),
    ("KINGS CROSS ST PANCRAS", "Alex", 4, "Huge interchange, great connections, can get busy."),
    ("VICTORIA", "Sarah", 3, "Efficient but crowded during rush hour."),
    ("PICCADILLY CIRCUS", "Tom", 5, "Central, vibrant, always buzzing."),
    ("WATERLOO", "Emily", 3, "Busy but efficient transport hub."),
    ("PADDINGTON", "James", 4, "Convenient, well-organised, great connections."),
    ("BANK", "Lisa", 3, "Complex layout, but a vital financial district stop."),
    ("OXFORD CIRCUS", "Jake", 4, "Crowded, vibrant, central shopping paradise."),
    ("BAKER STREET", "Emma", 4, "Sherlock vibes, calm, good transport links."),
    ("WESTMINSTER", "Daniel", 4, "Iconic, touristy, close to all the big attractions."),
    ("EUSTON", "Sophie", 3, "Fast-paced major interchange, often crowded."),
    ("HOLBORN", "Mike", 4, "Historic, well-connected, bustling business district."),
    ("LONDON BRIDGE", "Olivia", 4, "Scenic, historic, excellent river views nearby."),
    ("LIVERPOOL STREET", "Henry", 3, "Busy major hub with lots of shops."),
    ("HAMMERSMITH", "Megan", 4, "Riverside charm, lively, diverse neighbourhood."),
    ("FARRINGDON", "Liam", 4, "Trendy, historic, good for nightlife."),
    ("ANGEL", "Jack", 4, "Quirky, lively, great for shopping."),
    ("SOUTH KENSINGTON", "Grace", 4, "Cultural, museum hub, elegant surroundings."),
    ("BRIXTON", "Lucy", 4, "Vibrant, diverse, cool street markets."),
    ("STRATFORD", "Ethan", 3, "Olympic legacy, shopping paradise, always busy."),
    ("CAMDEN TOWN", "Oliver", 4, "Eclectic, alternative, vibrant music scene."),
    ("GREENWICH", "Mia", 4, "Maritime history, scenic, great market."),
    ("HAMPSTEAD", "Noah", 4, "Charming, village feel, great parks nearby."),
]


def main() -> None:
    graph = load_graph()
    added, skipped = 0, 0
    for station, author, rating, comment in DEMO_REVIEWS:
        if station not in graph:
            skipped += 1
            continue
        reviews.add_review(station, author, rating, comment)
        added += 1
    print(f"Seeded {added} reviews ({skipped} skipped, station not found)")


if __name__ == "__main__":
    main()
