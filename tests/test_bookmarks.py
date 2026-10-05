from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from metriq_visualizer_bookmarks import (
    BOOKMARK_SCHEMA,
    Bookmark,
    add_bookmark,
    bookmark_at,
    bookmarks_from_payload,
    bookmarks_to_payload,
    close_region,
    export_bookmarks,
)


class BookmarkTests(unittest.TestCase):
    def test_normalized_orders_clamps_and_collapses_tiny_regions(self) -> None:
        swapped = Bookmark(start=8.0, end=2.0).normalized(duration=5.0)
        self.assertEqual((swapped.start, swapped.end), (2.0, 5.0))
        beyond = Bookmark(start=12.0).normalized(duration=5.0)
        self.assertEqual(beyond.start, 5.0)
        tiny = Bookmark(start=1.0, end=1.001).normalized()
        self.assertIsNone(tiny.end)
        negative = Bookmark(start=-3.0, end=float("nan")).normalized()
        self.assertEqual(negative.start, 0.0)
        self.assertIsNone(negative.end)

    def test_add_bookmark_keeps_start_order_and_numbers_default_labels(self) -> None:
        items, first = add_bookmark([], 4.0)
        items, second = add_bookmark(items, 1.0, 2.5)
        items, third = add_bookmark(items, 3.0, label="Chorus")
        self.assertEqual([item.start for item in items], [1.0, 3.0, 4.0])
        self.assertEqual(first.label, "Mark 1")
        self.assertEqual(second.label, "Region 1")
        self.assertEqual(third.label, "Chorus")
        self.assertNotEqual(first.color, second.color)

    def test_close_region_turns_point_into_region_and_renames_default_label(self) -> None:
        items, point = add_bookmark([], 2.0)
        items, named = add_bookmark(items, 6.0, label="Call")
        items, region = close_region(items, point, 3.5)
        self.assertEqual((region.start, region.end, region.label), (2.0, 3.5, "Region 1"))
        items, named_region = close_region(items, named, 5.0)
        self.assertEqual((named_region.start, named_region.end, named_region.label), (5.0, 6.0, "Call"))
        self.assertEqual(len(items), 2)

    def test_bookmark_at_prefers_points_then_shortest_region(self) -> None:
        wide = Bookmark(start=0.0, end=10.0, label="wide")
        narrow = Bookmark(start=4.0, end=6.0, label="narrow")
        point = Bookmark(start=5.1, label="point")
        items = [wide, narrow, point]
        self.assertIs(bookmark_at(items, 5.0, tolerance=0.2), point)
        self.assertIs(bookmark_at(items, 4.5, tolerance=0.2), narrow)
        self.assertIs(bookmark_at(items, 1.0), wide)
        self.assertIsNone(bookmark_at(items, 11.0))

    def test_payload_round_trip_skips_invalid_entries(self) -> None:
        items, _ = add_bookmark([], 1.25, 2.5, label="Intro", note="first call")
        items, _ = add_bookmark(items, 0.5)
        payload = bookmarks_to_payload(items)
        json.dumps(payload)
        restored = bookmarks_from_payload([*payload, {"label": "no start"}, "junk", None])
        self.assertEqual(restored, items)
        self.assertEqual(bookmarks_from_payload("not a list"), [])
        clamped = bookmarks_from_payload(payload, duration=1.0)
        self.assertEqual([(item.start, item.end) for item in clamped], [(0.5, None), (1.0, None)])

    def test_export_csv_and_json(self) -> None:
        items, _ = add_bookmark([], 1.0, 3.0, label="Song, part 1", note='says "hi"')
        items, _ = add_bookmark(items, 4.0)
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = export_bookmarks(Path(temp_dir) / "marks.csv", items)
            with csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["label"], "Song, part 1")
            self.assertEqual(rows[0]["note"], 'says "hi"')
            self.assertEqual(rows[0]["duration_seconds"], "2.000000")
            self.assertEqual(rows[1]["end_seconds"], "")

            json_path = export_bookmarks(Path(temp_dir) / "marks.json", items, source_path="/media/a.wav")
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], BOOKMARK_SCHEMA)
            self.assertEqual(payload["source"], "/media/a.wav")
            self.assertEqual(bookmarks_from_payload(payload["bookmarks"]), items)

            default_path = export_bookmarks(Path(temp_dir) / "marks", items)
            self.assertEqual(default_path.suffix, ".csv")


if __name__ == "__main__":
    unittest.main()
