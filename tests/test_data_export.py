from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from metriq_visualizer_bookmarks import Bookmark
from metriq_visualizer_core import analysis_from_table_file, build_geometry
from metriq_visualizer_data_export import export_analysis_csv, export_analysis_npz


class DataExportTests(unittest.TestCase):
    def test_csv_and_npz_include_mapped_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.csv"
            source.write_text("time,a,b\n0,1,4\n1,2,3\n2,4,2\n3,8,1\n", encoding="utf-8")
            analysis = analysis_from_table_file(source)
            geometry = build_geometry(analysis, "a", "b", "pc1", "a+b", "a", max_points=3)

            csv_path = export_analysis_csv(root / "analysis", analysis, geometry)
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(len(rows), analysis.times.size + 1)
            self.assertIn("mapped_x", rows[0])
            self.assertIn("included_in_geometry", rows[0])

            npz_path = export_analysis_npz(root / "analysis_arrays", analysis, geometry)
            with np.load(npz_path, allow_pickle=False) as archive:
                metadata = json.loads(str(archive["__metadata__"].item()))
                self.assertEqual(metadata["schema"], "metriq.analysis-data")
                self.assertIn("mapped_z", metadata["columns"])
                self.assertEqual(metadata["mapping_formulas"]["x"], "a")
                self.assertEqual(archive["column_0000"].size, analysis.times.size)


    def test_time_range_and_bookmark_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.csv"
            source.write_text(
                "time,a,b\n" + "\n".join(f"{index},{index * 2},{10 - index}" for index in range(10)),
                encoding="utf-8",
            )
            analysis = analysis_from_table_file(source)
            geometry = build_geometry(analysis, "a", "b", "a", "a", "b")
            marks = [Bookmark(start=2.0, end=4.0, label="Rise"), Bookmark(start=3.2, label="Peak")]

            csv_path = export_analysis_csv(root / "region", analysis, geometry, time_range=(2.0, 4.0), bookmarks=marks)
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([float(row["time_seconds"]) for row in rows], [2.0, 3.0, 4.0])
            self.assertEqual([row["bookmark"] for row in rows], ["Rise", "Rise; Peak", "Rise"])

            plain_path = export_analysis_csv(root / "plain", analysis, geometry, bookmarks=[])
            with plain_path.open(newline="", encoding="utf-8") as handle:
                header = next(csv.reader(handle))
            self.assertNotIn("bookmark", header)

            npz_path = export_analysis_npz(root / "region", analysis, geometry, time_range=(4.0, 2.0), bookmarks=marks)
            with np.load(npz_path, allow_pickle=False) as archive:
                metadata = json.loads(str(archive["__metadata__"].item()))
                self.assertEqual(archive["column_0000"].tolist(), [2.0, 3.0, 4.0])
                self.assertEqual(metadata["time_range"], [4.0, 2.0])
                self.assertEqual([item["label"] for item in metadata["bookmarks"]], ["Rise", "Peak"])


if __name__ == "__main__":
    unittest.main()
