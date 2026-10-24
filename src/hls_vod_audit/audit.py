"""Read-only traversal of an explicitly bounded local VOD package."""

from __future__ import annotations

import re
import stat
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .parser import ParseError, parse

MAX_PLAYLIST_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_PLAYLISTS = 128
MAX_REFERENCES = 10000
MAX_DEPTH = 8
MAX_FINDINGS = 1000


class LimitReached(ValueError):
    pass


class LocalURIError(ValueError):
    """A diagnostic with a static message safe for a public report."""


class Auditor:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.findings = []
        self.complete = True
        self.playlists = {}
        self.active = set()
        self.assets = {}
        self.references = 0
        self.manifest_bytes = 0

    def label(self, path):
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return "<outside-root>"

    def issue(self, code, path, line, message, incomplete=False):
        if incomplete:
            self.complete = False
        if len(self.findings) >= MAX_FINDINGS:
            self.complete = False
            raise LimitReached("finding budget exceeded")
        self.findings.append(
            {"code": code, "playlist": self.label(path), "line": line, "message": message}
        )

    def resolve(self, source, uri, line):
        try:
            if not uri or len(uri) > 4096 or any(c.isspace() for c in uri):
                raise LocalURIError("empty, whitespace or overlong URI")
            parsed = urlsplit(uri)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                raise LocalURIError("only relative file URIs without query/fragment are supported")
            if re.search(r"%(?![0-9a-fA-F]{2})", parsed.path):
                raise LocalURIError("malformed percent escape in URI")
            decoded = unquote(parsed.path, encoding="utf-8", errors="strict")
            if not decoded or decoded.startswith(("/", "\\")) or "\\" in decoded or ":" in decoded:
                raise LocalURIError("absolute paths, backslashes and colons are unsupported")
            if any(ord(c) < 32 or ord(c) == 127 for c in decoded):
                raise LocalURIError("control character in decoded URI")
            candidate = source.parent / decoded
            target = candidate.resolve()
            if not target.is_relative_to(self.root):
                raise LocalURIError("reference resolves outside the package root")
            # Reject links within the root as well. Containment is checked after resolution.
            cursor = candidate
            while cursor != self.root and cursor != cursor.parent:
                if cursor.is_symlink():
                    raise LocalURIError("symbolic links are unsupported")
                cursor = cursor.parent
            return target
        except (OSError, RuntimeError, ValueError) as error:
            self.issue(
                "unsupported_uri",
                source,
                line,
                str(error)
                if isinstance(error, LocalURIError)
                else "unable to resolve local reference",
                True,
            )
            return None

    def file_size(self, path, source, line, playlist=False):
        try:
            info = path.stat()
        except FileNotFoundError:
            self.issue(
                "missing_playlist" if playlist else "missing_asset",
                source,
                line,
                "referenced local file is missing",
                playlist,
            )
            return None
        except OSError:
            self.issue("unreadable_file", source, line, "cannot stat referenced local file", True)
            return None
        if not stat.S_ISREG(info.st_mode):
            self.issue("nonregular_file", source, line, "reference must be a regular file", True)
            return None
        if info.st_size == 0 and not playlist:
            self.issue("empty_asset", source, line, "referenced asset is empty")
        return info.st_size

    def visit(self, path, depth=0):
        if path in self.active:
            self.issue("playlist_cycle", path, 1, "playlist reference cycle")
            return None
        if path in self.playlists:
            return self.playlists[path]["kind"]
        if depth > MAX_DEPTH or len(self.playlists) >= MAX_PLAYLISTS:
            self.issue("playlist_budget", path, 1, "playlist count/depth budget exceeded", True)
            raise LimitReached("playlist budget exceeded")
        if self.file_size(path, path, 1, playlist=True) is None:
            return None
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_PLAYLIST_BYTES + 1)
        except OSError:
            self.issue("unreadable_playlist", path, 1, "unable to read playlist", True)
            return None
        self.manifest_bytes += len(data)
        if len(data) > MAX_PLAYLIST_BYTES or self.manifest_bytes > MAX_TOTAL_BYTES:
            self.issue("byte_budget", path, 1, "playlist byte budget exceeded", True)
            raise LimitReached("playlist byte budget exceeded")
        try:
            playlist = parse(data)
        except ParseError as error:
            self.issue("parse_error", path, error.line, str(error), True)
            self.playlists[path] = {"kind": "invalid", "segments": 0, "duration_seconds": "0"}
            return "invalid"
        self.playlists[path] = {
            "kind": playlist.kind,
            "segments": len(playlist.durations),
            "duration_seconds": str(sum((d for d, _ in playlist.durations), Decimal(0))),
        }
        self.active.add(path)
        for code, line, message, incomplete in playlist.findings:
            self.issue(code, path, line, message, incomplete)
        previous_range = None
        try:
            for ref in playlist.references:
                self.references += 1
                if self.references > MAX_REFERENCES:
                    self.issue(
                        "reference_budget", path, ref.line, "reference budget exceeded", True
                    )
                    raise LimitReached("reference budget exceeded")
                target = self.resolve(path, ref.uri, ref.line)
                if target is None:
                    if ref.kind == "segment":
                        previous_range = None
                    continue
                if ref.kind == "playlist":
                    kind = self.visit(target, depth + 1)
                    if kind == "master":
                        self.issue(
                            "nested_master",
                            path,
                            ref.line,
                            "variant/rendition must reference a media playlist",
                        )
                    continue
                size = self.file_size(target, path, ref.line)
                if size is not None:
                    self.assets[target] = size
                offset = ref.offset
                if ref.length is not None and offset is None:
                    if ref.kind == "segment" and previous_range and previous_range[0] == target:
                        offset = previous_range[1]
                    else:
                        self.issue(
                            "implicit_range",
                            path,
                            ref.line,
                            "implicit offset needs the previous segment range in the same file",
                        )
                if ref.length is not None and offset is not None:
                    if size is not None and offset + ref.length > size:
                        self.issue(
                            "range_out_of_bounds",
                            path,
                            ref.line,
                            "byte range extends beyond the local file",
                        )
                    if ref.kind == "segment":
                        previous_range = target, offset + ref.length
                elif ref.kind == "segment":
                    previous_range = None
        finally:
            self.active.remove(path)
        return playlist.kind

    def run(self, entry: Path):
        try:
            # Entry is resolved through the same checks as child references.
            absolute = entry.absolute()
            if not self.root.is_dir():
                self.issue(
                    "invalid_root", absolute, 1, "package root must be an existing directory", True
                )
            elif absolute.is_symlink() or not absolute.resolve().is_relative_to(self.root):
                self.issue(
                    "entry_boundary",
                    absolute,
                    1,
                    "entry must be a non-symlink file inside root",
                    True,
                )
            else:
                self.visit(absolute.resolve())
        except LimitReached:
            self.complete = False
        except (OSError, RuntimeError):
            self.issue(
                "filesystem_error", entry, 1, "unable to inspect the requested package", True
            )
        return {
            "schema_version": 1,
            "complete": self.complete,
            "ok": self.complete and not self.findings,
            "summary": {
                "playlists": len(self.playlists),
                "references": self.references,
                "unique_assets": len(self.assets),
                "asset_bytes": sum(self.assets.values()),
                "playlist_bytes_read": self.manifest_bytes,
                "findings": len(self.findings),
            },
            "playlists": [
                {"path": self.label(path), **value}
                for path, value in sorted(self.playlists.items())
            ],
            "findings": self.findings,
        }


def audit(entry: Path, root: Path | None = None) -> dict:
    return Auditor(root if root is not None else entry.absolute().parent).run(entry)
