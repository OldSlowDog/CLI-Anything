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


def load_job(path) -> Dict[str, Any]:
    """Load a job spec from a JSON file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"job file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("software") != "vlc":
        raise ValueError("not a valid VLC job spec")
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
    errors: List[str] = []
    if not isinstance(job, dict):
        return ["job must be a JSON object"]
    if job.get("software") != "vlc":
        errors.append("software must be 'vlc'")
    inputs = job.get("inputs")
    if not isinstance(inputs, list) or len(inputs) == 0:
        errors.append("at least one input is required")
    out = job.get("output") or {}
    if out.get("path") in (None, ""):
        errors.append("output.path is required for transcode/stream")
    return errors
