# Copyright (c) Metriq Foundation, Inc.
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
"""Toolkit-neutral time bookmarks and regions for a loaded source.

A bookmark marks one moment (``end is None``) or a time range on the source
timeline. Bookmarks are plain values: they are clamped to the source duration,
kept in start order, serialized as JSON-safe dictionaries inside the project
session, and exported to CSV or JSON through transactional local writes.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from metriq_visualizer_atomic import atomic_write_text

BOOKMARK_SCHEMA = "metriq.visualizer-bookmarks"
BOOKMARK_SCHEMA_VERSION = 1
BOOKMARK_COLORS = ("#e9bd55", "#5fa6f7", "#4ce3ad", "#c48bf2", "#ef7f7f")
MAX_LABEL_LENGTH = 120
MAX_NOTE_LENGTH = 2000
# Regions shorter than this collapse to a point; it avoids zero-width spans
# from a double key press and keeps hit-testing meaningful.
MIN_REGION_SECONDS = 0.01


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _text(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _color(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
        except ValueError:
            return fallback
        return text.lower()
    return fallback


@dataclass(frozen=True, slots=True)
class Bookmark:
    """One labelled moment or time range, in source seconds."""

    start: float
    end: float | None = None
    label: str = ""
    note: str = ""
    color: str = BOOKMARK_COLORS[0]

    @property
    def is_region(self) -> bool:
        return self.end is not None

    @property
    def duration(self) -> float:
        return 0.0 if self.end is None else max(0.0, self.end - self.start)

    def contains(self, seconds: float) -> bool:
        if self.end is None:
            return math.isclose(seconds, self.start, abs_tol=1e-9)
        return self.start <= seconds <= self.end

    def normalized(self, duration: float | None = None) -> Bookmark:
        """Return a copy with ordered, finite, duration-clamped times."""

        start = max(0.0, _finite(self.start))
        end = None if self.end is None else max(0.0, _finite(self.end, start))
        if end is not None and end < start:
            start, end = end, start
        if duration is not None and duration >= 0.0:
            start = min(start, duration)
            end = None if end is None else min(end, duration)
        if end is not None and end - start < MIN_REGION_SECONDS:
            end = None
        return replace(
            self,
            start=start,
            end=end,
            label=_text(self.label, MAX_LABEL_LENGTH),
            note=_text(self.note, MAX_NOTE_LENGTH),
            color=_color(self.color, BOOKMARK_COLORS[0]),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"start": round(self.start, 6), "label": self.label, "color": self.color}
        if self.end is not None:
            payload["end"] = round(self.end, 6)
        if self.note:
            payload["note"] = self.note
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, index: int = 0) -> Bookmark:
        end = payload.get("end")
        return cls(
            start=_finite(payload.get("start")),
            end=None if end is None else _finite(end),
            label=_text(payload.get("label"), MAX_LABEL_LENGTH),
            note=_text(payload.get("note"), MAX_NOTE_LENGTH),
            color=_color(payload.get("color"), color_for_index(index)),
        ).normalized()


def color_for_index(index: int) -> str:
    return BOOKMARK_COLORS[int(index) % len(BOOKMARK_COLORS)]


def sort_bookmarks(bookmarks: Iterable[Bookmark]) -> list[Bookmark]:
    return sorted(bookmarks, key=lambda item: (item.start, item.end if item.end is not None else item.start, item.label))


def normalize_bookmarks(bookmarks: Iterable[Bookmark], duration: float | None = None) -> list[Bookmark]:
    return sort_bookmarks(item.normalized(duration) for item in bookmarks)


def bookmarks_from_payload(payload: Any, duration: float | None = None) -> list[Bookmark]:
    """Read bookmarks from a project session list, skipping invalid entries."""

    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        return []
    items: list[Bookmark] = []
    for index, entry in enumerate(payload):
        if isinstance(entry, Mapping) and "start" in entry:
            items.append(Bookmark.from_dict(entry, index=index))
    return normalize_bookmarks(items, duration)


def bookmarks_to_payload(bookmarks: Iterable[Bookmark]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in sort_bookmarks(bookmarks)]


def next_label(bookmarks: Sequence[Bookmark], *, region: bool = False) -> str:
    prefix = "Region" if region else "Mark"
    used = {item.label for item in bookmarks}
    number = 1
    while f"{prefix} {number}" in used:
        number += 1
    return f"{prefix} {number}"


def add_bookmark(
    bookmarks: Sequence[Bookmark],
    start: float,
    end: float | None = None,
    *,
    label: str = "",
    note: str = "",
    duration: float | None = None,
) -> tuple[list[Bookmark], Bookmark]:
    """Return the new ordered list and the bookmark that was added."""

    candidate = Bookmark(start=start, end=end, note=note, color=color_for_index(len(bookmarks))).normalized(duration)
    candidate = replace(candidate, label=_text(label, MAX_LABEL_LENGTH) or next_label(bookmarks, region=candidate.is_region))
    return sort_bookmarks([*bookmarks, candidate]), candidate


def close_region(
    bookmarks: Sequence[Bookmark],
    target: Bookmark,
    end: float,
    *,
    duration: float | None = None,
) -> tuple[list[Bookmark], Bookmark]:
    """Turn the point *target* into a region ending at *end*.

    A default ``Mark N`` label becomes ``Region N`` so the list reads
    naturally; a label the user typed is kept.
    """

    items = list(bookmarks)
    index = items.index(target)
    label = target.label
    if label.startswith("Mark ") and label[5:].isdigit():
        label = next_label([item for item in items if item is not target], region=True)
    updated = replace(target, end=end, label=label).normalized(duration)
    items[index] = updated
    return sort_bookmarks(items), updated


def bookmark_at(
    bookmarks: Sequence[Bookmark],
    seconds: float,
    *,
    tolerance: float = 0.0,
) -> Bookmark | None:
    """Return the bookmark under *seconds*: the nearest point, else the shortest region."""

    points = [item for item in bookmarks if item.end is None and abs(item.start - seconds) <= tolerance]
    if points:
        return min(points, key=lambda item: abs(item.start - seconds))
    regions = [
        item for item in bookmarks
        if item.end is not None and item.start - tolerance <= seconds <= item.end + tolerance
    ]
    return min(regions, key=lambda item: item.duration) if regions else None


def _csv_text(bookmarks: Sequence[Bookmark]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["start_seconds", "end_seconds", "duration_seconds", "label", "note", "color"])
    for item in sort_bookmarks(bookmarks):
        writer.writerow(
            [
                f"{item.start:.6f}",
                "" if item.end is None else f"{item.end:.6f}",
                f"{item.duration:.6f}",
                item.label,
                item.note,
                item.color,
            ]
        )
    return buffer.getvalue()


def export_bookmarks(
    path: str | Path,
    bookmarks: Sequence[Bookmark],
    *,
    source_path: str | Path | None = None,
) -> Path:
    """Write bookmarks as ``.csv`` or ``.json`` depending on the suffix."""

    output = Path(path).expanduser()
    if output.suffix.lower() not in {".csv", ".json"}:
        output = output.with_suffix(".csv")
    if output.suffix.lower() == ".json":
        payload = {
            "schema": BOOKMARK_SCHEMA,
            "schema_version": BOOKMARK_SCHEMA_VERSION,
            "source": str(source_path) if source_path else "",
            "bookmarks": bookmarks_to_payload(bookmarks),
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    else:
        text = _csv_text(bookmarks)
    atomic_write_text(output, text)
    return output.resolve()


__all__ = [
    "BOOKMARK_COLORS",
    "BOOKMARK_SCHEMA",
    "BOOKMARK_SCHEMA_VERSION",
    "Bookmark",
    "add_bookmark",
    "bookmark_at",
    "bookmarks_from_payload",
    "bookmarks_to_payload",
    "close_region",
    "color_for_index",
    "export_bookmarks",
    "next_label",
    "normalize_bookmarks",
    "sort_bookmarks",
]
