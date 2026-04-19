from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class VideoRef:
    path: str | None
    url: str | None
    sha256: str | None


@dataclass(frozen=True)
class TextRef:
    path: str | None
    format: str | None


@dataclass(frozen=True)
class AudioRef:
    path: str | None
    url: str | None
    format: str | None
    sample_rate_hz: int | None


@dataclass(frozen=True)
class Commentary:
    commentary_id: str
    match_id: str
    type: str
    language: str | None
    source: str | None
    text: TextRef | None
    audio: AudioRef | None
    alignment: dict[str, Any] | None


@dataclass(frozen=True)
class Match:
    match_id: str
    title: str | None
    league: str | None
    date: str | None
    length_sec: int | None
    video: VideoRef
    commentaries: list[Commentary]
    meta: dict[str, Any]


@dataclass(frozen=True)
class Manifest:
    version: str | None
    matches: list[Match]
    match_by_id: dict[str, Match]
    commentary_by_id: dict[str, Commentary]


def _require_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"missing or invalid {key}")
    return value


def _opt_str(obj: dict[str, Any], key: str) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"invalid {key}")
    value = value.strip()
    return value if value != "" else None


def _opt_int(obj: dict[str, Any], key: str) -> int | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"invalid {key}")
    return value


def _parse_text_format(fmt: str | None) -> str | None:
    if fmt is None:
        return None
    v = fmt.strip().lower()
    if v == "":
        return None
    if v not in {"json", "txt", "text", "plain"}:
        raise ValueError(f"unsupported text.format: {fmt}")
    return "txt" if v in {"text", "plain"} else v


def _as_rel_to_data_dir(data_dir: Path, p: str | None) -> str | None:
    if p is None or p.strip() == "":
        return None
    path = Path(p)
    if path.is_absolute():
        try:
            rel = path.resolve().relative_to(data_dir.resolve())
        except Exception:
            raise ValueError(f"path must be under data_dir: {p}")
        return rel.as_posix()
    return path.as_posix()


def load_manifest(manifest_path: Path, data_dir: Path) -> Manifest:
    raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("manifest must be a JSON object")
    version = _opt_str(raw, "version")
    matches_raw = raw.get("matches")
    if not isinstance(matches_raw, list):
        raise ValueError("manifest.matches must be a list")

    matches: list[Match] = []
    match_by_id: dict[str, Match] = {}
    commentary_by_id: dict[str, Commentary] = {}

    for m in matches_raw:
        if not isinstance(m, dict):
            raise ValueError("each match must be an object")
        match_id = _require_str(m, "match_id")
        if match_id in match_by_id:
            raise ValueError(f"duplicate match_id: {match_id}")

        video_raw = m.get("video") or {}
        if not isinstance(video_raw, dict):
            raise ValueError(f"match.video must be an object: {match_id}")
        video = VideoRef(
            path=_as_rel_to_data_dir(data_dir, _opt_str(video_raw, "path")),
            url=_opt_str(video_raw, "url"),
            sha256=_opt_str(video_raw, "sha256"),
        )

        commentaries_raw = m.get("commentaries")
        if not isinstance(commentaries_raw, list) or len(commentaries_raw) < 2:
            raise ValueError(f"match.commentaries must be a list with >=2 items: {match_id}")

        commentaries: list[Commentary] = []
        for c in commentaries_raw:
            if not isinstance(c, dict):
                raise ValueError(f"commentary must be an object: {match_id}")
            commentary_id = _require_str(c, "commentary_id")
            if commentary_id in commentary_by_id:
                raise ValueError(f"duplicate commentary_id: {commentary_id}")
            c_type = (_opt_str(c, "type") or "both").lower()
            if c_type not in {"text", "audio", "both", "pair"}:
                raise ValueError(f"invalid commentary.type: {commentary_id}")

            text_ref: TextRef | None = None
            if isinstance(c.get("text"), dict):
                text_ref = TextRef(
                    path=_as_rel_to_data_dir(data_dir, _opt_str(c["text"], "path")),
                    format=_parse_text_format(_opt_str(c["text"], "format")),
                )

            audio_ref: AudioRef | None = None
            if isinstance(c.get("audio"), dict):
                audio_ref = AudioRef(
                    path=_as_rel_to_data_dir(data_dir, _opt_str(c["audio"], "path")),
                    url=_opt_str(c["audio"], "url"),
                    format=_opt_str(c["audio"], "format"),
                    sample_rate_hz=_opt_int(c["audio"], "sample_rate_hz"),
                )

            commentary = Commentary(
                commentary_id=commentary_id,
                match_id=match_id,
                type=("both" if c_type == "pair" else c_type),
                language=_opt_str(c, "language"),
                source=_opt_str(c, "source"),
                text=text_ref,
                audio=audio_ref,
                alignment=c.get("alignment") if isinstance(c.get("alignment"), dict) else None,
            )
            if commentary.text is None or commentary.text.path is None:
                raise ValueError(f"commentary missing text.path: {commentary_id}")

            commentaries.append(commentary)
            commentary_by_id[commentary_id] = commentary

        meta = {k: v for k, v in m.items() if k not in {"match_id", "title", "league", "date", "length_sec", "video", "commentaries"}}
        match = Match(
            match_id=match_id,
            title=_opt_str(m, "title"),
            league=_opt_str(m, "league"),
            date=_opt_str(m, "date"),
            length_sec=_opt_int(m, "length_sec"),
            video=video,
            commentaries=commentaries,
            meta=meta if isinstance(meta, dict) else {},
        )
        matches.append(match)
        match_by_id[match_id] = match

    return Manifest(version=version, matches=matches, match_by_id=match_by_id, commentary_by_id=commentary_by_id)
