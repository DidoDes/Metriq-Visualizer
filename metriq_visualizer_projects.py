# Copyright (c) Metriq Foundation, Inc.
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
"""Portable Metriq Visualizer project persistence."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metriq_visualizer_atomic import atomic_write_text

PROJECT_EXTENSION = ".mvproj"
LEGACY_PROJECT_EXTENSIONS = (".bgl",)
PROJECT_SCHEMA = "metriq.visualizer-project"
PROJECT_SCHEMA_VERSION = 2


def _json_write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def build_project_payload(name: str, state: Mapping[str, Any], *, project_path: str | Path | None = None) -> dict[str, Any]:
    clean_state = deepcopy(dict(state))
    relative_source = ""
    relative_compare = ""
    if project_path:
        project = Path(project_path).expanduser().resolve()
        session = clean_state.get("session")
        if isinstance(session, dict):
            relative_source = _relative_to_project(session.get("file_path"), project)
            compare = session.get("compare")
            if isinstance(compare, dict):
                relative_compare = _relative_to_project(compare.get("file_path"), project)
    payload = {
        "schema": PROJECT_SCHEMA,
        "schema_version": PROJECT_SCHEMA_VERSION,
        "name": str(name or "Metriq Visualizer Project").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "relative_source": relative_source,
        "state": clean_state,
    }
    if relative_compare:
        payload["relative_compare_source"] = relative_compare
    return payload


def _relative_to_project(source_text: Any, project: Path) -> str:
    text = str(source_text or "").strip()
    if not text:
        return ""
    source = Path(text).expanduser().resolve()
    try:
        # ``relative_to`` only works for descendants. ``relpath``
        # also preserves sibling layouts such as ../media/source.wav.
        return os.path.relpath(source, project.parent)
    except ValueError:
        # Different Windows drives cannot be represented as one
        # relative path; retain the absolute session path instead.
        return ""


def _resolve_relative(relative: str, project_file: Path) -> Path | None:
    text = str(relative or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser() if text.startswith("~") else (project_file.parent / text)
    return candidate.resolve() if candidate.exists() else None


def save_project(path: str | Path, payload: Mapping[str, Any]) -> Path:
    output = Path(path).expanduser()
    if output.suffix.lower() != PROJECT_EXTENSION:
        output = output.with_suffix(PROJECT_EXTENSION)
    _json_write_atomic(output, payload)
    return output.resolve()


def load_project(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("Project file must contain a JSON object.")
    schema = str(payload.get("schema", ""))
    if schema and schema != PROJECT_SCHEMA:
        raise ValueError("This JSON file is not a Metriq Visualizer project.")
    version = int(payload.get("schema_version", 1))
    if version > PROJECT_SCHEMA_VERSION:
        raise ValueError(f"Project schema {version} is newer than this application supports.")
    state = payload.get("state", payload if source.suffix.lower() in LEGACY_PROJECT_EXTENSIONS else None)
    if not isinstance(state, Mapping):
        raise ValueError("Project state is missing or invalid.")
    result = dict(payload)
    result["state"] = deepcopy(dict(state))

    # Resolve a portable source reference before falling back to an absolute path.
    session = result["state"].get("session")
    if isinstance(session, dict):
        resolved = _resolve_relative(payload.get("relative_source", ""), source)
        if resolved is not None:
            session["file_path"] = str(resolved)
        compare = session.get("compare")
        resolved_compare = _resolve_relative(payload.get("relative_compare_source", ""), source)
        if isinstance(compare, dict) and resolved_compare is not None:
            compare["file_path"] = str(resolved_compare)
    return result


__all__ = [
    "LEGACY_PROJECT_EXTENSIONS",
    "PROJECT_EXTENSION",
    "PROJECT_SCHEMA",
    "PROJECT_SCHEMA_VERSION",
    "build_project_payload",
    "load_project",
    "save_project",
]
