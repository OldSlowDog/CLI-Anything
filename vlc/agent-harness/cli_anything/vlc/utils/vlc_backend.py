"""Backend bridge to the real VLC binary.

This module NEVER reimplements media processing in Python. It only locates the VLC
binary and invokes it with command lines built by ``core/transcode.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from ..core.transcode import (
    build_transcode_sout,
    build_stream_sout,
    build_snapshot_args,
)
from ..core.media import parse_vlc_stats


def find_vlc() -> Path:
    """Locate the VLC binary.

    Honours ``VLC_BINARY`` (absolute path). Otherwise searches ``PATH`` for
    ``vlc`` / ``cvlc`` / ``vlc.exe``. Raises ``RuntimeError`` with install
    instructions when not found — this is a hard dependency, never skipped.
    """
    env = os.environ.get("VLC_BINARY")
    if env and Path(env).exists():
        return Path(env)
    for name in ("vlc", "cvlc", "vlc.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise RuntimeError(
        "VLC not found on PATH. Install VLC (https://www.videolan.org/vlc/) and ensure "
        "'vlc' is on PATH, or set VLC_BINARY to the absolute binary path."
    )


def run_transcode(job: Dict[str, Any], timeout: int = 600) -> Dict[str, Any]:
    """Transcode the first input to the job's output using the real VLC engine."""
    vlc = find_vlc()
    chain = build_transcode_sout(job)
    inputs = job.get("inputs") or []
    if not inputs:
        raise ValueError("job has no inputs")
    out = job["output"]["path"]
    cmd: List[str] = [
        str(vlc), "-I", "dummy", "--play-and-exit", "--quiet",
        "--sout", chain, str(inputs[0]),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"vlc exited {result.returncode}: {result.stderr[-800:]}")
    p = Path(out)
    if not p.exists():
        raise RuntimeError(f"VLC produced no output at {out}\n{result.stderr[-800:]}")
    return {
        "output": str(p),
        "format": job["output"].get("format"),
        "file_size": p.stat().st_size,
        "method": "vlc-transcode",
        "returncode": result.returncode,
    }


def run_stream(job: Dict[str, Any], run_time: int = 2, timeout: int = 120) -> Dict[str, Any]:
    """Stream the first input over the network using the real VLC engine.

    ``run_time`` keeps the process bounded so it exits (used by tests / demos). Real
    streaming sessions would omit it.

    The subprocess timeout is scaled with ``run_time`` so a long requested stream is
    not killed mid-run by the default 120s ceiling.
    """
    vlc = find_vlc()
    chain = build_stream_sout(job)
    inputs = job.get("inputs") or []
    if not inputs:
        raise ValueError("job has no inputs")
    s = job.get("stream") or {}
    cmd: List[str] = [
        str(vlc), "-I", "dummy", "--play-and-exit", "--quiet",
        f"--run-time={run_time}",
        "--sout", chain, str(inputs[0]),
    ]
    # Always allow the process to outlive its requested run time by a margin.
    effective_timeout = max(int(timeout), int(run_time) + 30)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=effective_timeout)
    if result.returncode != 0:
        raise RuntimeError(f"vlc exited {result.returncode}: {result.stderr[-800:]}")
    return {
        "protocol": s.get("protocol", "rtp"),
        "destination": f"{s.get('dst', '127.0.0.1')}:{s.get('port', 1234)}",
        "method": "vlc-stream",
        "returncode": result.returncode,
        "note": f"streamed for {run_time}s then exited",
    }


def run_snapshot(job: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
    """Extract a still frame from the first input using VLC's scene video filter."""
    vlc = find_vlc()
    snap = job.get("snapshot") or {}
    out_dir = snap.get("path")
    if not out_dir:
        raise ValueError("snapshot.path (output directory) is required")
    inputs = job.get("inputs") or []
    if not inputs:
        raise ValueError("job has no inputs")
    scene_dir = Path(out_dir)
    scene_dir.mkdir(parents=True, exist_ok=True)
    # Record pre-existing PNGs so a reused directory never leaks stale files into
    # the result (and the lexicographically-last file is not an unrelated old one).
    pre_existing = set(scene_dir.glob("*.png"))
    args = build_snapshot_args(job)
    cmd: List[str] = [str(vlc), "-I", "dummy", "--play-and-exit", *args, str(inputs[0])]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"vlc exited {result.returncode}: {result.stderr[-800:]}")
    produced = [p for p in scene_dir.glob("*.png") if p not in pre_existing]
    if not produced:
        raise RuntimeError(f"VLC produced no new snapshot in {out_dir}\n{result.stderr[-800:]}")
    # Most recent file this run produced (robust against naming/sort quirks).
    last = max(produced, key=lambda p: p.stat().st_mtime)
    return {
        "snapshot": str(last),
        "count": len(produced),
        "file_size": last.stat().st_size,
        "method": "vlc-scene",
    }


def run_info(input_path, timeout: int = 120) -> Dict[str, Any]:
    """Probe a media file via VLC dummy-mode stats (best-effort parse)."""
    vlc = find_vlc()
    cmd: List[str] = [
        str(vlc), "-I", "dummy", "--play-and-exit", "--stats",
        "--no-video-title-show", str(input_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"VLC exited {result.returncode} while probing {input_path}\n"
            f"{result.stderr[-800:]}"
        )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    info = parse_vlc_stats(combined)
    info["path"] = str(input_path)
    info["returncode"] = result.returncode
    try:
        info["size_bytes"] = Path(input_path).stat().st_size
    except OSError:
        pass
    return info
