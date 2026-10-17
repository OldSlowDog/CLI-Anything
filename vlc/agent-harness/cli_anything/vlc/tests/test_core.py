"""Unit tests for the VLC harness — no VLC binary required.

These exercise the pure-Python core (job spec, session undo/redo, --sout chain
construction, stats parsing) and the Click command wiring for the mutation commands.
They run in CI / anywhere with only Python + click installed.
"""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import wave
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli_anything.vlc import vlc_cli
from cli_anything.vlc.core import project as proj
from cli_anything.vlc.core import session as sess_mod
from cli_anything.vlc.core import transcode
from cli_anything.vlc.core import media
from cli_anything.vlc.utils import vlc_backend


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


def test_cli_transcode_missing_project_is_structured_json(tmp_path):
    # P2 fix: a missing project must surface as a structured --json error, not a traceback.
    runner = CliRunner()
    missing = tmp_path / "nope.json"
    r = runner.invoke(vlc_cli.cli, ["--json", "--project", str(missing), "transcode"])
    assert r.exit_code == 1
    payload = json.loads(r.output)
    assert payload.get("error")
    assert "project" in payload.get("detail", "").lower()


# ── P1/P2 review fixes ─────────────────────────────────────────────────

def test_transcode_copy_and_none_codecs_omitted():
    # copy / none resolve to None -> must NOT emit the literal "vcodec=None".
    j = proj.new_job()
    j["inputs"].append("in.mp4")
    j["output"] = {"path": "out.mkv", "format": "mkv"}
    j["transcode"]["vcodec"] = "copy"
    j["transcode"]["acodec"] = "none"
    s = transcode.build_transcode_sout(j)
    assert "vcodec=None" not in s
    assert "acodec=None" not in s
    assert "vcodec=copy" not in s
    assert "acodec=none" not in s


def test_run_stream_timeout_scales_with_run_time(monkeypatch):
    # P1 fix: a long --run-time must not be killed by the fixed 120s subprocess timeout.
    captured = {}

    monkeypatch.setattr(vlc_backend, "find_vlc", lambda: Path("vlc-stub"))

    def _fake_run(cmd, **kw):
        captured["timeout"] = kw.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(vlc_backend.subprocess, "run", _fake_run)

    j = proj.new_job()
    j["inputs"].append("in.mp4")
    j["stream"] = {"protocol": "rtp", "dst": "127.0.0.1", "port": 1234, "mux": "ts"}
    vlc_backend.run_stream(j, run_time=300)
    assert captured["timeout"] >= 300

    # short run keeps the historical 120s floor
    captured.clear()
    vlc_backend.run_stream(j, run_time=1)
    assert captured["timeout"] >= 120


def test_run_snapshot_ignores_stale_files(monkeypatch, tmp_path):
    # P1 fix: a reused directory must not leak pre-existing PNGs into the result,
    # and the lexicographically-last stale file must not be returned.
    shot = tmp_path / "shots"
    shot.mkdir()
    stale = shot / "zzzz_old.png"  # would win a naive sorted()[-1]
    stale.write_bytes(b"\x89PNG-stale")

    def _fake_run(cmd, **kw):
        (shot / "scene00001.png").write_bytes(b"\x89PNG-new")  # VLC's real output
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(vlc_backend, "find_vlc", lambda: Path("vlc-stub"))
    monkeypatch.setattr(vlc_backend.subprocess, "run", _fake_run)

    j = proj.new_job()
    j["inputs"].append("in.mp4")
    j["snapshot"] = {"path": str(shot), "time": 1.0, "ratio": 1}
    result = vlc_backend.run_snapshot(j)
    assert Path(result["snapshot"]).name == "scene00001.png"
    assert result["count"] == 1  # only the file produced by this run


def test_run_info_propagates_nonzero_exit(monkeypatch):
    # P2 fix: a failing VLC probe must surface as an error (not a silent dict).

    def _fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(vlc_backend, "find_vlc", lambda: Path("vlc-stub"))
    monkeypatch.setattr(vlc_backend.subprocess, "run", _fake_run)
    with pytest.raises(RuntimeError):
        vlc_backend.run_info("/dev/null")


def test_registry_names_not_in_both_files():
    # P2 fix: CLI-Hub concatenates registry.json + public_registry.json without
    # dedup, so a name must not appear in both. Runs only in the monorepo checkout.
    root = Path(__file__).resolve().parents[5]
    local = root / "registry.json"
    public = root / "public_registry.json"
    if not (local.is_file() and public.is_file()):
        pytest.skip("registry files not present (standalone install)")

    def _names(path):
        with open(path, encoding="utf-8") as fh:
            return {c["name"] for c in json.load(fh).get("clis", [])}

    dup = _names(local) & _names(public)
    assert not dup, f"names present in both registries: {sorted(dup)}"


# ── second-round review fixes ──────────────────────────────────────────

def test_transcode_rejects_output_equal_to_input(monkeypatch):
    # P1: output that aliases the input would clobber the source being read.
    monkeypatch.setattr(vlc_backend, "find_vlc", lambda: Path("vlc-stub"))
    j = proj.new_job()
    j["inputs"].append("/media/clip.mp4")
    j["output"] = {"path": "/media/clip.mp4", "format": "mp4"}
    with pytest.raises(ValueError):
        vlc_backend.run_transcode(j)


def test_run_stream_persistent_omits_run_time(monkeypatch):
    # P1: omitting run-time must yield a persistent stream (no --run-time, no
    # bounded subprocess timeout).
    captured = {}
    monkeypatch.setattr(vlc_backend, "find_vlc", lambda: Path("vlc-stub"))

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["timeout"] = kw.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(vlc_backend.subprocess, "run", _fake_run)
    j = proj.new_job()
    j["inputs"].append("in.mp4")
    j["stream"] = {"protocol": "udp", "dst": "127.0.0.1", "port": 6004, "mux": "ts"}
    res = vlc_backend.run_stream(j)  # run_time omitted -> persistent
    assert not any(a.startswith("--run-time") for a in captured["cmd"])
    assert captured["timeout"] is None
    assert "persistent" in res["note"]


def test_find_vlc_rejects_directory_binary(monkeypatch, tmp_path):
    # P2: VLC_BINARY pointing at a directory (not a file) must fail loudly on
    # every platform, rather than making `doctor` report ready.
    a_dir = tmp_path / "vlc_dir"
    a_dir.mkdir()
    monkeypatch.setenv("VLC_BINARY", str(a_dir))
    with pytest.raises(RuntimeError):
        vlc_backend.find_vlc()


@pytest.mark.skipif(os.name != "posix", reason="the exec-bit check is POSIX-only")
def test_find_vlc_rejects_non_executable_file(monkeypatch, tmp_path):
    # P2: a regular non-executable file must fail (POSIX exec-bit check).
    not_exe = tmp_path / "not_vlc"
    not_exe.write_text("hello", encoding="utf-8")
    not_exe.chmod(0o644)  # readable, not executable
    monkeypatch.setenv("VLC_BINARY", str(not_exe))
    with pytest.raises(RuntimeError):
        vlc_backend.find_vlc()


def test_cli_mutation_malformed_project_structured(tmp_path):
    # P2: mutation commands must emit a structured --json error on malformed JSON,
    # not a traceback.
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    media_file = tmp_path / "in.mp4"
    media_file.write_text("x", encoding="utf-8")
    runner = CliRunner()
    r = runner.invoke(vlc_cli.cli, ["--json", "--project", str(bad), "add-input", str(media_file)])
    assert r.exit_code == 1
    assert json.loads(r.output).get("error")


def test_repl_shlex_handles_spaces_and_backslashes():
    # P2: the REPL tokenizer must keep Windows backslashes literal while still
    # respecting quotes around paths containing spaces.
    import shlex as _shlex
    line = r'add-input "C:\Users\me\my clip.mp4"'
    lexer = _shlex.shlex(line, posix=False)
    lexer.whitespace_split = True
    parts = [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in lexer]
    assert parts == ["add-input", r"C:\Users\me\my clip.mp4"]
