"""Unit tests for the VLC harness — no VLC binary required.

These exercise the pure-Python core (job spec, session undo/redo, --sout chain
construction, stats parsing) and the Click command wiring for the mutation commands.
They run in CI / anywhere with only Python + click installed.
"""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli_anything.vlc import vlc_cli
from cli_anything.vlc.core import project as proj
from cli_anything.vlc.core import session as sess_mod
from cli_anything.vlc.core import transcode
from cli_anything.vlc.core import media


# ── core.project ───────────────────────────────────────────────────────

def test_new_job_defaults():
    j = proj.new_job()
    assert j["software"] == "vlc"
    assert j["inputs"] == []
    assert j["transcode"]["vcodec"] == "h264"


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "job.json"
    meta = proj.save_job(proj.new_job(), p)
    assert p.is_file()
    assert meta["size_bytes"] > 0
    loaded = proj.load_job(p)
    assert loaded["software"] == "vlc"


def test_validate_job():
    j = proj.new_job()
    errs = proj.validate_job(j)
    assert any("input" in e for e in errs)
    j["inputs"].append("a.mp4")
    j["output"]["path"] = "o.mp4"
    assert proj.validate_job(j) == []


# ── core.session ───────────────────────────────────────────────────────

def test_session_undo_redo():
    s = sess_mod.Session()
    s.mutate("add", lambda j: j["inputs"].append("x.mp4"))
    assert s.job["inputs"] == ["x.mp4"]
    s.undo()
    assert s.job["inputs"] == []
    assert s.can_redo()
    s.redo()
    assert s.job["inputs"] == ["x.mp4"]


def test_session_history_labels():
    s = sess_mod.Session()
    s.mutate("a", lambda j: j["inputs"].append("1"))
    s.mutate("b", lambda j: j["inputs"].append("2"))
    assert s.history() == ["a", "b"]
    s.undo()
    assert s.history() == ["a"]


# ── core.transcode ─────────────────────────────────────────────────────

def test_build_transcode_sout_basic():
    j = proj.new_job()
    j["inputs"].append("in.mp4")
    j["output"] = {"path": "out.mp4", "format": "mp4"}
    j["transcode"]["vbitrate"] = 1000
    s = transcode.build_transcode_sout(j)
    assert s.startswith("#transcode{")
    assert "vcodec=h264" in s
    assert "vb=1000" in s
    assert "std{access=file,mux=mp4,dst='out.mp4'}" in s


def test_build_transcode_sout_windows_path_normalized():
    j = proj.new_job()
    j["output"] = {"path": "C:\\out.mp4", "format": "mkv"}
    s = transcode.build_transcode_sout(j)
    assert "\\\\" not in s
    assert "dst='C:/out.mp4'" in s


def test_build_stream_sout_rtp():
    j = proj.new_job()
    j["stream"] = {"protocol": "rtp", "dst": "127.0.0.1", "port": 5004, "mux": "ts"}
    s = transcode.build_stream_sout(j)
    assert "rtp{dst=127.0.0.1,port=5004,mux=ts}" in s


def test_build_snapshot_args():
    j = proj.new_job()
    j["snapshot"] = {"path": "/tmp/shots", "time": 2.0, "ratio": 1}
    args = transcode.build_snapshot_args(j)
    assert "--video-filter=scene" in args
    assert "--scene-path=/tmp/shots" in args
    assert "--start-time=2.0" in args


# ── core.media ─────────────────────────────────────────────────────────

def test_parse_vlc_stats_synthetic():
    text = (
        "decoder: using h264 codec\n"
        "resolution 1920x1080\n"
        "duration: 12.5 s\n"
        "bitrate: 1234"
    )
    info = media.parse_vlc_stats(text)
    assert info["video_codec"] == "H264"
    assert info["width"] == 1920
    assert info["height"] == 1080
    assert info["duration_seconds"] == 12.5
    assert info["bitrate_kbps"] == 1234


# ── CLI wiring (no backend) ────────────────────────────────────────────

def test_cli_version_and_help():
    runner = CliRunner()
    assert runner.invoke(vlc_cli.cli, ["--version"]).exit_code == 0
    assert runner.invoke(vlc_cli.cli, ["--help"]).exit_code == 0


def test_cli_project_new_and_mutate(tmp_path):
    runner = CliRunner()
    job = tmp_path / "job.json"
    r = runner.invoke(vlc_cli.cli, ["--json", "project", "new", "-o", str(job)])
    assert r.exit_code == 0, r.output

    # add-input records a real (existing) media path
    media_file = tmp_path / "in.mp4"
    media_file.write_text("dummy", encoding="utf-8")
    r = runner.invoke(vlc_cli.cli, ["--json", "--project", str(job), "add-input", str(media_file)])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["input_count"] == 1

    r = runner.invoke(vlc_cli.cli, ["--json", "--project", str(job), "set-option", "vbitrate", "900"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["transcode"]["vbitrate"] == 900

    # persisted to disk
    saved = json.loads(job.read_text(encoding="utf-8"))
    assert saved["transcode"]["vbitrate"] == 900


def test_cli_set_output_and_stream(tmp_path):
    runner = CliRunner()
    job = tmp_path / "job.json"
    runner.invoke(vlc_cli.cli, ["project", "new", "-o", str(job)])
    runner.invoke(vlc_cli.cli, ["--project", str(job), "set-output", "out.mp4", "--format", "mkv"])
    runner.invoke(vlc_cli.cli, ["--project", str(job), "set-stream", "--protocol", "udp",
                                "--dst", "127.0.0.1", "--port", "6000", "--mux", "ts"])
    saved = json.loads(job.read_text(encoding="utf-8"))
    assert saved["output"]["format"] == "mkv"
    assert saved["stream"]["protocol"] == "udp"


def test_cli_transcode_requires_project(tmp_path):
    runner = CliRunner()
    r = runner.invoke(vlc_cli.cli, ["transcode"])
    assert r.exit_code != 0
    assert "project" in r.output.lower()


def test_cli_doctor_without_vlc(monkeypatch):
    # doctor imports find_vlc by name, so patch the reference it actually calls.
    def _raise(*_a, **_k):
        raise RuntimeError("VLC not found")

    monkeypatch.setattr(vlc_cli, "find_vlc", _raise)
    runner = CliRunner()
    r = runner.invoke(vlc_cli.cli, ["--json", "doctor"])
    assert r.exit_code == 1
    assert json.loads(r.output)["ready"] is False
