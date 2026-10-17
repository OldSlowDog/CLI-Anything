"""Build VLC command-line fragments from a job spec.

Pure functions — no subprocess, no VLC required. These construct the ``--sout``
streaming-output chains and the snapshot arguments that ``utils/vlc_backend.py`` feeds
to the real ``vlc`` binary.

VLC expects its *own* codec identifiers inside ``transcode{...}`` (e.g. ``s16l`` for PCM
WAV, ``mp4a`` for AAC). To keep the agent interface human-friendly, this module maps
common user-facing names (``wav``, ``aac``, ``h264`` …) to the canonical VLC names and
maps an output *format* to the matching ``mux``. Unknown values raise ``ValueError`` so
the agent gets an actionable error instead of a silent empty output file.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Friendly audio codec name -> VLC codec name.
AUDIO_CODEC_ALIASES: Dict[str, Optional[str]] = {
    "wav": "s16l",
    "pcm": "s16l",
    "pcm_s16le": "s16l",
    "mp3": "mp3",
    "aac": "mp4a",
    "ac3": "a52",
    "eac3": "eac3",
    "flac": "flac",
    "opus": "opus",
    "vorbis": "vorbis",
    "ogg": "vorbis",
    "mp2": "mp2",
    "none": None,
    "copy": None,
}

# Friendly video codec name -> VLC codec name.
VIDEO_CODEC_ALIASES: Dict[str, Optional[str]] = {
    "h264": "h264",
    "x264": "h264",
    "hevc": "hevc",
    "h265": "hevc",
    "av1": "av1",
    "mpeg4": "mp4v",
    "mp4v": "mp4v",
    "mp4": "mp4v",
    "mpeg2": "mp2v",
    "mpeg2video": "mp2v",
    "vp8": "VP8",
    "vp9": "VP9",
    "theora": "theora",
    "none": None,
    "copy": None,
}

# Output format -> VLC mux name.
MUX_BY_FORMAT: Dict[str, str] = {
    "wav": "wav",
    "mp3": "mp3",
    "mp2": "ts",
    "aac": "mp4",
    "m4a": "mp4",
    "m4v": "mp4",
    "mp4": "mp4",
    "mov": "mp4",
    "flac": "flac",
    "opus": "ogg",
    "ogg": "ogg",
    "ogv": "ogg",
    "ac3": "ts",
    "eac3": "ts",
    "mkv": "mkv",
    "webm": "webm",
    "avi": "avi",
    "ts": "ts",
    "ps": "ps",
    "flv": "flv",
}

# Raw VLC names we accept verbatim (so advanced users can pass VLC-native ids).
_KNOWN_VLC_AUDIO = {"s16l", "mp3", "mp4a", "a52", "eac3", "flac", "opus", "vorbis", "mp2"}
_KNOWN_VLC_VIDEO = {"h264", "hevc", "av1", "mp4v", "mp2v", "VP8", "VP9", "theora"}


def resolve_audio_codec(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    key = str(name).strip().lower()
    if key in AUDIO_CODEC_ALIASES:
        return AUDIO_CODEC_ALIASES[key]
    if key in _KNOWN_VLC_AUDIO:
        return key
    raise ValueError(
        f"Unknown audio codec '{name}'. Known: "
        + ", ".join(sorted(AUDIO_CODEC_ALIASES))
        + f". (VLC-native ids also allowed: {', '.join(sorted(_KNOWN_VLC_AUDIO))})"
    )


def resolve_video_codec(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    key = str(name).strip().lower()
    if key in VIDEO_CODEC_ALIASES:
        return VIDEO_CODEC_ALIASES[key]
    if key in _KNOWN_VLC_VIDEO:
        return key
    raise ValueError(
        f"Unknown video codec '{name}'. Known: "
        + ", ".join(sorted(VIDEO_CODEC_ALIASES))
        + f". (VLC-native ids also allowed: {', '.join(sorted(_KNOWN_VLC_VIDEO))})"
    )


def resolve_mux(fmt: str) -> str:
    key = str(fmt).strip().lower()
    if key in MUX_BY_FORMAT:
        return MUX_BY_FORMAT[key]
    return key  # allow VLC-native mux names directly


def _transcode_block(job: Dict[str, Any]) -> str:
    """Return the ``transcode{...}`` fragment (possibly empty)."""
    t = job.get("transcode", {}) or {}
    params: List[str] = []
    # ``copy`` / ``none`` resolve to None — drop the param rather than emitting
    # a literal ``vcodec=None`` / ``acodec=None`` that VLC cannot parse.
    vcodec = resolve_video_codec(t["vcodec"]) if t.get("vcodec") else None
    if vcodec:
        params.append(f"vcodec={vcodec}")
    acodec = resolve_audio_codec(t["acodec"]) if t.get("acodec") else None
    if acodec:
        params.append(f"acodec={acodec}")
    if t.get("vbitrate"):
        params.append(f"vb={int(t['vbitrate'])}")
    if t.get("abitrate"):
        params.append(f"ab={int(t['abitrate'])}")
    scale = t.get("scale")
    if scale not in (None, 1.0, 1):
        params.append(f"scale={scale}")
    if t.get("width"):
        params.append(f"width={int(t['width'])}")
    if t.get("height"):
        params.append(f"height={int(t['height'])}")
    if t.get("fps"):
        params.append(f"fps={t['fps']}")
    if t.get("channels"):
        params.append(f"channels={int(t['channels'])}")
    if t.get("samplerate"):
        params.append(f"samplerate={int(t['samplerate'])}")
    params.extend(t.get("extra") or [])
    return "transcode{" + ",".join(params) + "}"


def build_transcode_sout(job: Dict[str, Any]) -> str:
    """Build a file-to-file transcode ``--sout`` chain.

    Example: ``#transcode{vcodec=mp4v,acodec=mp3,vb=800,ab=128}:std{access=file,mux=mp4,dst='out.mp4'}``
    """
    out = job.get("output", {}) or {}
    dst = (out.get("path") or "").replace("\\", "/")
    mux = resolve_mux(out.get("format", "mp4"))
    std = f"std{{access=file,mux={mux},dst='{dst}'}}"
    return f"#{_transcode_block(job)}:{std}"


def build_stream_sout(job: Dict[str, Any]) -> str:
    """Build a network-stream ``--sout`` chain from ``job['stream']``."""
    s = job.get("stream") or {}
    proto = (s.get("protocol") or "rtp").lower()
    dst = s.get("dst", "127.0.0.1")
    port = int(s.get("port", 1234))
    mux = resolve_mux(s.get("mux", "ts"))

    if proto == "rtp":
        dest = f"rtp{{dst={dst},port={port},mux={mux}}}"
    elif proto == "udp":
        dest = f"udp{{dst={dst},port={port},mux={mux}}}"
    elif proto == "http":
        dest = f"standard{{access=http,mux={mux},dst={dst}:{port}}}"
    else:
        dest = f"standard{{access={proto},mux={mux},dst={dst}:{port}}}"

    return f"#{_transcode_block(job)}:{dest}"


def build_snapshot_args(job: Dict[str, Any]) -> List[str]:
    """Build VLC arguments to extract a still frame via the scene video filter."""
    snap = job.get("snapshot") or {}
    path = (snap.get("path") or "").replace("\\", "/")
    ratio = int(snap.get("ratio", 1))
    args = [
        "--video-filter=scene",
        f"--scene-path={path}",
        f"--scene-ratio={ratio}",
        "--scene-format=png",
        "--no-audio",
        "--play-and-exit",
    ]
    if snap.get("time") is not None:
        # Seek to the requested time, then run a tiny window so only ~1 frame is captured.
        args.append(f"--start-time={float(snap['time'])}")
        args.append("--run-time=0.1")
    return args
