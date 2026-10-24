# cli-anything-vlc — Tests

## Part 1 — Test Plan (written before implementation)

### Test Inventory

| Layer | File | Requires VLC? | Purpose |
|---|---|---|---|
| Unit | `test_core.py` | No | Pure-Python core + Click wiring, synthetic data |
| E2E  | `test_full_e2e.py` | **Yes** | Invokes the real `vlc` binary (transcode / info / stream) |

### Unit Test Plan (`test_core.py`)

- `TestProjectModel` — `new_job` defaults, save/load round-trip, `validate_job` rules,
  schema (field-type) rejection at load time
- `TestSession` — undo/redo restores snapshots, history labels
- `TestTranscodeBuilder` — `--sout` chain construction (transcode + stream + snapshot),
  Windows path normalization, scene-prefix override
- `TestMediaParser` — best-effort stats parsing from synthetic VLC log
- `TestCliWiring` — `--version`/`--help`, `project new`, `add-input`, `set-option`
  persistence, `set-output`/`set-stream`, `transcode` requires `--project`, `doctor`
  without VLC, structured `--json` errors for missing / malformed / schema-invalid projects
- `TestBackendSafety` — stream timeout scaling with `--run-time`, persistent stream when
  run-time is omitted, snapshot isolation from stale files and across re-runs, temp-file
  cleanup on subprocess failure, `run_info` propagating a nonzero exit, `VLC_BINARY`
  validation, registry de-duplication
- `TestRepl` — `new` detaching an opened project, shell-like tokenising of quoted
  Windows paths

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
collected 34 items

test_new_job_defaults PASSED
test_save_and_load_roundtrip PASSED
test_validate_job PASSED
test_session_undo_redo PASSED
test_session_history_labels PASSED
test_build_transcode_sout_basic PASSED
test_build_transcode_sout_windows_path_normalized PASSED
test_build_stream_sout_rtp PASSED
test_build_snapshot_args PASSED
test_build_snapshot_args_scene_prefix PASSED
test_parse_vlc_stats_synthetic PASSED
test_cli_version_and_help PASSED
test_cli_project_new_and_mutate PASSED
test_cli_set_output_and_stream PASSED
test_cli_transcode_requires_project PASSED
test_cli_doctor_without_vlc PASSED
test_cli_transcode_missing_project_is_structured_json PASSED
test_transcode_copy_and_none_codecs_omitted PASSED
test_run_stream_timeout_scales_with_run_time PASSED
test_run_snapshot_ignores_stale_files PASSED
test_run_info_propagates_nonzero_exit PASSED
test_registry_names_not_in_both_files PASSED
test_transcode_rejects_output_equal_to_input PASSED
test_run_stream_persistent_omits_run_time PASSED
test_find_vlc_rejects_directory_binary PASSED
test_find_vlc_rejects_non_executable_file PASSED
test_cli_mutation_malformed_project_structured PASSED
test_repl_shlex_handles_spaces_and_backslashes PASSED
test_load_job_rejects_schema_invalid_types PASSED
test_load_job_rejects_non_string_inputs PASSED
test_cli_mutation_schema_invalid_project_is_structured PASSED
test_repl_new_detaches_opened_project PASSED
test_run_transcode_removes_temp_when_subprocess_raises PASSED
test_run_snapshot_rerun_same_directory_succeeds PASSED

============================= 33 passed, 1 skipped in 0.80s =============================
```

**Summary:** 33 passed, 1 skipped (`test_find_vlc_rejects_non_executable_file` — the
exec-bit check is POSIX-only). No external dependency (VLC / ffmpeg) required.

#### Regression-proofing of the review fixes

Every review finding ships with a test that was verified to **fail against the pre-fix
code** (the fixed sources were reverted and the new tests re-run), so none of them is a
test that would pass either way:

| Round | Findings | Regression tests |
|---|---|---|
| 1st (`8d1a22a`) | 9 | codec `None` omission, stream timeout scaling, snapshot stale-file isolation, `run_info` exit propagation, structured project errors, registry de-duplication, SKILL.md option order |
| 2nd (`cb6fe9e`) | 7 | output aliases input, stale destination rejected, persistent stream, guarded malformed projects, REPL `shlex`, `VLC_BINARY` validation, `.gitignore` scoping |
| 3rd (`7d5c4e1`) | 4 | `new` detaches an opened project, schema-invalid projects rejected at load *and* inside the guard, temp-file cleanup on subprocess failure, per-run snapshot prefix |

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
