"""Job spec model for the VLC harness.

A "job" is a JSON document describing a reproducible media operation (transcode /
stream / snapshot). It is the harness's notion of project state.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_JOB: Dict[str, Any] = {
    "version": "1.0.0",
    "software": "vlc",
    "inputs": [],
    "output": {"path": None, "format": "mp4"},
    "transcode": {
        "vcodec": "h264",
        "acodec": "mp3",
        "vbitrate": 800,
        "abitrate": 128,
        "scale": 1.0,
        "width": None,
        "height": None,
        "fps": None,
        "channels": 2,
        "samplerate": 44100,
        "extra": [],
    },
    "stream": None,
    "snapshot": None,
}


def new_job() -> Dict[str, Any]:
    """Return a fresh job spec (deep copy of the default)."""
    return copy.deepcopy(DEFAULT_JOB)


_LIST_KEYS = ("inputs",)
_DICT_KEYS = ("output", "transcode", "stream", "snapshot")
_NUMERIC_OPTIONS = ("vbitrate", "abitrate", "width", "height", "fps", "channels",
                    "samplerate", "scale")


def _schema_problems(job: Any) -> List[str]:
    """Return type-level problems in a job spec (empty == well-formed).

    ``load_job`` used to check only ``software``, so a spec such as
    ``{"software": "vlc", "output": []}`` loaded successfully and then exploded inside
    a mutator — outside the CLI's structured-error guard, leaving ``--json`` callers
    with a traceback and nothing parseable on stdout. Validating field *types* at load
    time turns that into an actionable error instead of an ``AttributeError``.
    """
    if not isinstance(job, dict):
        return ["job must be a JSON object"]
    problems: List[str] = []
    if job.get("software") != "vlc":
        problems.append("software must be 'vlc'")
    if job.get("version") is not None and not isinstance(job["version"], str):
        problems.append("version must be a string")
    for key in _LIST_KEYS:
        value = job.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            problems.append(f"{key} must be a list")
        elif not all(isinstance(item, str) for item in value):
            problems.append(f"{key} must contain only strings")
    for key in _DICT_KEYS:
        value = job.get(key)
        if value is not None and not isinstance(value, dict):
            problems.append(f"{key} must be an object")
    out = job.get("output")
    if isinstance(out, dict):
        if out.get("path") not in (None, "") and not isinstance(out.get("path"), str):
            problems.append("output.path must be a string")
        if out.get("format") is not None and not isinstance(out.get("format"), str):
            problems.append("output.format must be a string")
    trans = job.get("transcode")
    if isinstance(trans, dict):
        for key in _NUMERIC_OPTIONS:
            value = trans.get(key)
            if value is not None and not isinstance(value, (int, float)):
                problems.append(f"transcode.{key} must be a number")
    return problems


def load_job(path) -> Dict[str, Any]:
    """Load a job spec from a JSON file.

    Rejects specs with the wrong *shape* as well as ones that are simply not VLC
    jobs, so no caller ever receives a half-valid dict it cannot safely use.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"job file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("software") != "vlc":
        raise ValueError("not a valid VLC job spec")
    problems = _schema_problems(data)
    if problems:
        raise ValueError("invalid VLC job spec: " + "; ".join(problems))
    return data


def save_job(job: Dict[str, Any], path) -> Dict[str, Any]:
    """Persist a job spec to a JSON file; return metadata about the written file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"path": str(p), "size_bytes": p.stat().st_size}


def job_summary(job: Dict[str, Any]) -> Dict[str, Any]:
    """Return a display-friendly summary of a job spec."""
    out = job.get("output", {}) or {}
    t = job.get("transcode", {}) or {}
    stream = job.get("stream")
    snapshot = job.get("snapshot")
    return {
        "software": job.get("software"),
        "inputs": list(job.get("inputs", [])),
        "input_count": len(job.get("inputs", [])),
        "output_path": out.get("path"),
        "output_format": out.get("format"),
        "transcode": {
            "vcodec": t.get("vcodec"),
            "acodec": t.get("acodec"),
            "vbitrate": t.get("vbitrate"),
            "abitrate": t.get("abitrate"),
        },
        "has_stream": stream is not None,
        "has_snapshot": snapshot is not None,
    }


def validate_job(job: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable problems (empty == valid).

    Does not require VLC; only validates the spec is internally consistent.
    """
    errors = _schema_problems(job)
    inputs = job.get("inputs") if isinstance(job, dict) else None
    if not isinstance(inputs, list) or len(inputs) == 0:
        errors.append("at least one input is required")
    out = job.get("output") or {}
    if isinstance(out, dict) and out.get("path") in (None, ""):
        errors.append("output.path is required for transcode/stream")
    return errors
