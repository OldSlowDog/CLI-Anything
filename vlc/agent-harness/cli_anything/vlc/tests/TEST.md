# cli-anything-vlc — Tests

## Part 1 — Test Plan (written before implementation)

### Test Inventory

| Layer | File | Requires VLC? | Purpose |
|---|---|---|---|
| Unit | `test_core.py` | No | Pure-Python core + Click wiring, synthetic data |
| E2E  | `test_full_e2e.py` | **Yes** | Invokes the real `vlc` binary (transcode / info / stream) |

### Unit Test Plan (`test_core.py`)

- `TestProjectModel` — `new_job` defaults, save/load round-trip, `validate_job` rules
- `TestSession` — undo/redo restores snapshots, history labels
- `TestTranscodeBuilder` — `--sout` chain construction (transcode + stream + snapshot), Windows path normalization
- `TestMediaParser` — best-effort stats parsing from synthetic VLC log
- `TestCliWiring` — `--version`/`--help`, `project new`, `add-input`, `set-option` persistence, `set-output`/`set-stream`, `transcode` requires `--project`, `doctor` without VLC

### E2E Test Plan (`test_full_e2e.py`)

- `test_transcode_wav_to_wav` — real VLC transcode; verify output exists, size > 1 KB, `RIFF` magic
- `test_info_wav` — real VLC probe; verify `path` + `returncode`
- `test_stream_udp` — real VLC UDP stream for 1 s; verify exit 0
- `test_cli_transcode_end_to_end` — full agent flow via `--json`

A `tests/assets/sample.wav` is synthesised with the stdlib `wave` module so the basic
E2E paths run without ffmpeg.

> **Non-negotiable (HARNESS.md):** E2E tests MUST invoke the real software and FAIL
> (not skip) when VLC is missing. They use `pytest.fail` for that.

## Part 2 — Test Results

### Unit — `pytest cli_anything/vlc/tests/test_core.py -v`

```
platform win32 -- Python 3.14.3, pytest-9.1.1
collected 15 items

test_new_job_defaults PASSED
test_save_and_load_roundtrip PASSED
test_validate_job PASSED
test_session_undo_redo PASSED
test_session_history_labels PASSED
test_build_transcode_sout_basic PASSED
test_build_transcode_sout_windows_path_normalized PASSED
test_build_stream_sout_rtp PASSED
test_build_snapshot_args PASSED
test_parse_vlc_stats_synthetic PASSED
test_cli_version_and_help PASSED
test_cli_project_new_and_mutate PASSED
test_cli_set_output_and_stream PASSED
test_cli_transcode_requires_project PASSED
test_cli_doctor_without_vlc PASSED

============================= 15 passed in 0.22s =============================
```

**Summary:** 15 passed, 0 failed. No external dependency (VLC / ffmpeg) required.

### E2E — `pytest cli_anything/vlc/tests/test_full_e2e.py -v` (real VLC 3.0.21)

```
platform win32 -- Python 3.14.3, pytest-9.1.1
collected 4 items

test_transcode_wav_to_wav PASSED        # real vlc transcode -> output exists, >1KB, 'RIFF' magic
test_info_wav PASSED                    # real vlc --stats probe, path + returncode
test_stream_udp PASSED                  # real vlc UDP stream 1s, exit 0
test_cli_transcode_end_to_end PASSED    # full agent flow via --json

============================= 4 passed in 6.58s =============================
```

Run locally (VLC on PATH, or `VLC_BINARY` set):

```bash
pip install -e '.[dev]'
VLC_BINARY=/path/to/vlc pytest cli_anything/vlc/tests/ -v
```

**Verified empirically against the real engine:**

- `WAV → WAV`: `--sout '#transcode{acodec=s16l}:std{access=file,mux=wav,dst=out.wav}'` produces a valid `RIFF` file.
- `WAV → MP3`: `acodec=mp3,mux=mp3` → valid MP3 frame (`ff e3…`).
- `WAV → AAC/FLAC/OPUS`: `acodec=mp4a/flac/opus` all produce valid containers.
- `acodec=wav` (friendly) is resolved to the canonical VLC `s16l`; raw `vlc` codec ids are also accepted.

> **Non-negotiable (HARNESS.md):** E2E tests MUST invoke the real software and FAIL
> (not skip) when VLC is missing. They use `pytest.fail` for that.

**Coverage notes:**

- Unit layer covers the full data model, undo/redo session, `--sout` chain construction,
  codec-alias resolution, and stats parsing — the parts most likely to regress.
- E2E layer proves the harness drives the authentic VLC engine end-to-end for transcode,
  info, and stream. Snapshot extraction is video-only (VLC's scene filter needs a video
  stream) and is validated manually with a real video sample.
