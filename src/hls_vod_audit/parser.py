"""A bounded structural HLS subset. Unsupported features are explicit."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

MAX_LINES = 20000
INTEGER = re.compile(r"[0-9]{1,20}")
ATTR = re.compile(r'([A-Z0-9-]+)=(?:"([^"\r\n]*)"|([^,\s"]+))(,|$)')


class ParseError(ValueError):
    def __init__(self, line: int, message: str):
        super().__init__(message)
        self.line = line


def integer(value: str, positive=False) -> int:
    if not INTEGER.fullmatch(value) or int(value) > 2**64 - 1:
        raise ValueError("expected an unsigned 64-bit decimal integer")
    result = int(value)
    if positive and result == 0:
        raise ValueError("expected a positive decimal integer")
    return result


def attributes(text: str) -> dict[str, str]:
    values = {}
    position = 0
    while position < len(text):
        match = ATTR.match(text, position)
        if not match:
            raise ValueError("malformed attribute list")
        key, quoted, unquoted, comma = match.groups()
        if key in values:
            raise ValueError("duplicate attribute")
        if (
            key in {"URI", "BYTERANGE", "GROUP-ID", "NAME", "CODECS", "AUDIO", "VIDEO", "SUBTITLES"}
            and quoted is None
        ):
            raise ValueError("string attribute must be quoted")
        values[key] = quoted if quoted is not None else unquoted
        position = match.end()
        if comma and position == len(text):
            raise ValueError("trailing attribute comma")
    if not values:
        raise ValueError("empty attribute list")
    return values


def byte_range(value: str) -> tuple[int, int | None]:
    parts = value.split("@")
    if len(parts) > 2:
        raise ValueError("invalid byte range")
    return integer(parts[0], positive=True), integer(parts[1]) if len(parts) == 2 else None


@dataclass
class Reference:
    uri: str
    line: int
    kind: str
    length: int | None = None
    offset: int | None = None


@dataclass
class Playlist:
    kind: str = "media"
    references: list[Reference] = field(default_factory=list)
    findings: list[tuple[str, int, str, bool]] = field(default_factory=list)
    durations: list[tuple[Decimal, int]] = field(default_factory=list)
    version: int = 1
    minimum_version: int = 1
    target: int | None = None
    ended: bool = False
    variants: int = 0


def parse(data: bytes) -> Playlist:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ParseError(1, "playlist must be UTF-8") from error
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise ParseError(1, "control character in playlist")
    lines = text.replace("\r\n", "\n").split("\n")
    if len(lines) > MAX_LINES:
        raise ParseError(1, "playlist line budget exceeded")
    if not lines or lines[0] != "#EXTM3U":
        raise ParseError(1, "first line must be #EXTM3U without a BOM")
    result = Playlist()
    singletons = set()
    master_seen = media_seen = False
    pending_stream = False
    pending_duration = None
    pending_range = None
    rendition_groups = set()
    required_groups = []
    rendition_names = set()

    for number, raw in enumerate(lines[1:], 2):
        if "\r" in raw or len(raw) > 16384:
            raise ParseError(number, "invalid line ending or line length budget exceeded")
        line = raw.strip()
        if not line or (line.startswith("#") and not line.startswith("#EXT")):
            continue
        if not line.startswith("#"):
            if pending_stream:
                result.references.append(Reference(line, number, "playlist"))
                result.variants += 1
                pending_stream = False
            else:
                if pending_duration is None:
                    raise ParseError(number, "segment URI has no preceding EXTINF")
                length, offset = pending_range if pending_range else (None, None)
                result.references.append(Reference(line, number, "segment", length, offset))
                result.durations.append((pending_duration, number))
                pending_duration = pending_range = None
            continue
        if pending_stream:
            raise ParseError(number, "EXT-X-STREAM-INF must be followed by its playlist URI")
        tag, separator, value = line.partition(":")
        try:
            if tag in {
                "#EXTM3U",
                "#EXT-X-VERSION",
                "#EXT-X-TARGETDURATION",
                "#EXT-X-ENDLIST",
                "#EXT-X-PLAYLIST-TYPE",
                "#EXT-X-MEDIA-SEQUENCE",
                "#EXT-X-DISCONTINUITY-SEQUENCE",
                "#EXT-X-INDEPENDENT-SEGMENTS",
            }:
                if tag in singletons or tag == "#EXTM3U":
                    raise ValueError("duplicate singleton tag")
                singletons.add(tag)
            if tag == "#EXT-X-VERSION":
                result.version = integer(value, positive=True)
                if result.version > 7:
                    result.findings.append(
                        ("unsupported_version", number, "versions above 7 are unsupported", True)
                    )
            elif tag == "#EXT-X-TARGETDURATION":
                media_seen = True
                result.target = integer(value, positive=True)
            elif tag == "#EXT-X-ENDLIST":
                media_seen = True
                if separator:
                    raise ValueError("ENDLIST must not have a value")
                result.ended = True
            elif tag == "#EXT-X-PLAYLIST-TYPE":
                media_seen = True
                if value != "VOD":
                    result.findings.append(
                        (
                            "unsupported_playlist_type",
                            number,
                            "only VOD packages are supported",
                            True,
                        )
                    )
            elif tag in {"#EXT-X-MEDIA-SEQUENCE", "#EXT-X-DISCONTINUITY-SEQUENCE"}:
                media_seen = True
                integer(value)
                if result.durations:
                    raise ValueError("sequence tag must precede segments")
            elif tag == "#EXTINF":
                media_seen = True
                if pending_duration is not None:
                    raise ValueError("EXTINF without its segment URI")
                duration, comma, _ = value.partition(",")
                if not comma or not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,9})?", duration):
                    raise ValueError("EXTINF requires a finite positive decimal duration and comma")
                pending_duration = Decimal(duration)
                if pending_duration <= 0:
                    raise ValueError("EXTINF duration must be positive")
                if "." in duration:
                    result.minimum_version = max(result.minimum_version, 3)
            elif tag == "#EXT-X-BYTERANGE":
                media_seen = True
                if pending_range is not None:
                    raise ValueError("BYTERANGE without its segment URI")
                pending_range = byte_range(value)
                result.minimum_version = max(result.minimum_version, 4)
            elif tag == "#EXT-X-MAP":
                media_seen = True
                attrs = attributes(value)
                if not attrs.get("URI"):
                    raise ValueError("MAP requires URI")
                length, offset = (
                    byte_range(attrs["BYTERANGE"]) if "BYTERANGE" in attrs else (None, None)
                )
                if length is not None and offset is None:
                    result.findings.append(
                        (
                            "unsupported_map_offset",
                            number,
                            "MAP byte range requires an explicit offset",
                            True,
                        )
                    )
                result.references.append(Reference(attrs["URI"], number, "map", length, offset))
                result.minimum_version = max(result.minimum_version, 6)
            elif tag == "#EXT-X-KEY":
                media_seen = True
                attrs = attributes(value)
                if attrs.get("METHOD") != "NONE":
                    result.findings.append(
                        (
                            "unsupported_encryption",
                            number,
                            "encrypted media is outside this offline check",
                            True,
                        )
                    )
                elif set(attrs) != {"METHOD"}:
                    raise ValueError("METHOD=NONE must have no other attributes")
            elif tag == "#EXT-X-DISCONTINUITY":
                media_seen = True
                if separator:
                    raise ValueError("DISCONTINUITY must not have a value")
            elif tag == "#EXT-X-INDEPENDENT-SEGMENTS":
                if separator:
                    raise ValueError("INDEPENDENT-SEGMENTS must not have a value")
            elif tag == "#EXT-X-STREAM-INF":
                master_seen = True
                attrs = attributes(value)
                integer(attrs.get("BANDWIDTH", ""), positive=True)
                pending_stream = True
                for kind in ("AUDIO", "VIDEO", "SUBTITLES", "CLOSED-CAPTIONS"):
                    if kind in attrs and not (kind == "CLOSED-CAPTIONS" and attrs[kind] == "NONE"):
                        required_groups.append((kind, attrs[kind], number))
            elif tag == "#EXT-X-MEDIA":
                master_seen = True
                attrs = attributes(value)
                kind = attrs.get("TYPE")
                group, name = attrs.get("GROUP-ID"), attrs.get("NAME")
                if (
                    kind not in {"AUDIO", "VIDEO", "SUBTITLES", "CLOSED-CAPTIONS"}
                    or not group
                    or not name
                ):
                    raise ValueError("MEDIA requires valid TYPE, nonempty GROUP-ID and NAME")
                if (kind, group, name) in rendition_names:
                    raise ValueError("duplicate rendition name within group")
                rendition_names.add((kind, group, name))
                rendition_groups.add((kind, group))
                if kind == "SUBTITLES" and not attrs.get("URI"):
                    raise ValueError("SUBTITLES rendition requires URI")
                if kind == "CLOSED-CAPTIONS" and "URI" in attrs:
                    raise ValueError("CLOSED-CAPTIONS must not have URI")
                if "URI" in attrs:
                    result.references.append(Reference(attrs["URI"], number, "playlist"))
            else:
                result.findings.append(
                    ("unsupported_tag", number, "tag is outside the supported subset", True)
                )
        except ValueError as error:
            raise ParseError(number, str(error)) from error
    if pending_stream or pending_duration is not None or pending_range is not None:
        raise ParseError(len(lines), "unfinished tag/URI pair at end of playlist")
    if master_seen and media_seen:
        raise ParseError(1, "master and media tags must not be mixed")
    result.kind = "master" if master_seen else "media"
    for kind, group, number in required_groups:
        if (kind, group) not in rendition_groups:
            result.findings.append(
                (
                    "missing_rendition_group",
                    number,
                    "variant references an undefined rendition group",
                    False,
                )
            )
    if result.kind == "master":
        if not result.variants:
            result.findings.append(("empty_master", 1, "master has no variant playlist", False))
    else:
        if not result.durations:
            result.findings.append(("empty_media", 1, "media playlist has no segments", False))
        if not result.ended:
            result.findings.append(
                ("missing_endlist", 1, "VOD package requires EXT-X-ENDLIST", False)
            )
        if result.target is None:
            result.findings.append(
                ("missing_target", 1, "media playlist requires TARGETDURATION", False)
            )
        else:
            for duration, number in result.durations:
                if duration.to_integral_value(rounding=ROUND_HALF_UP) > result.target:
                    result.findings.append(
                        (
                            "target_duration",
                            number,
                            "rounded segment duration exceeds TARGETDURATION",
                            False,
                        )
                    )
    if result.version < result.minimum_version:
        result.findings.append(
            ("version_too_low", 1, "declared/default version is too low for used tags", False)
        )
    return result
