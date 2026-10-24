# hls-vod-audit

Find missing local HLS segments, invalid byte ranges and broken playlist references
before uploading a VOD package. Checks stay inside a chosen directory and never make
network requests. Python 3.11+, standard library only.

[中文说明](README.zh-CN.md) · [Supported checks](docs/design.md) · [MIT](LICENSE)

## Install and run

```sh
git clone https://github.com/KanadeK/hls-vod-audit.git
cd hls-vod-audit
python -m pip install .
python examples/check_example.py
hls-vod-audit /path/to/package/master.m3u8 --format json
```

The example creates a temporary structural fixture, checks its master/media playlists,
then proves that a shortened byte-range file and a missing asset fail. Its byte fixture
is deliberately not playable video; the checker does not decode media.

For actual video acceptance, if you have a local ffmpeg with libx264/lavfi:

```sh
python examples/check_ffmpeg.py --ffmpeg ffmpeg
```

This generates four tiny VOD packages (MPEG-TS/fMP4, separate segments/single-file ranges),
checks and decodes each, and then verifies detection of a deleted segment or shortened
range file. Everything is generated in a temporary directory, cleaned on exit. ffmpeg
is optional for this acceptance script and is not needed by the installed checker.

## Use on your package

```sh
hls-vod-audit video/index.m3u8 --root package-root
hls-vod-audit package/master.m3u8 --format json
python -m hls_vod_audit package/master.m3u8
```

The default root is the entry playlist's parent directory. Set `--root` to the actual
package directory if variants use `../shared/` assets. All resolved references must
remain inside that root. The checker reads bounded UTF-8 playlists and stats regular
assets; it does not open media payloads or encryption keys.

| Check | Behavior |
|---|---|
| Package references | Follow variant and alternate audio/video/subtitle playlists; detect cycles, nested masters, absent child manifests and missing rendition groups |
| Local assets | Verify regular, nonempty segment and initialization files exist inside root |
| Byte ranges | Validate explicit offsets, continuation offsets in the same preceding segment resource, and end against local file size |
| Durations | Positive decimal EXTINF, target duration using nearest-integer rounding (ties upward), exact decimal totals |
| VOD structure | EXTM3U, tag/URI pairs, singleton tags, ENDLIST, media/master separation, selected minimum-version requirements |
| Unsupported features | Return INCOMPLETE for unknown tags, versions above 7, encryption, EVENT, remote URIs, query/fragment URIs and implicit MAP offsets |

Percent-encoded UTF-8 local filenames work. Absolute paths, backslashes, colons,
decoded control characters, symlinks and references escaping root are rejected. Raw
spaces in URI lines must be percent encoded. The filesystem is assumed stable during
the run; this is not a sandbox against hostile concurrent path replacement.

Exit codes:

- `0` — all supported structural checks passed.
- `1` — the completed check found a defect, such as a missing segment or an oversized range.
- `2` — the check is incomplete: unreadable/malformed manifest, unsupported feature,
  unsafe reference, missing child playlist, resource limit or invalid CLI arguments.

JSON includes `ok`, `complete`, counts, per-playlist durations and findings with relative
playlist paths and line numbers. It omits raw URI values, queries, headers and local
absolute paths. Reports still contain package names and metadata. A playlist may be
structurally invalid even if an incomplete result takes precedence in the exit code.

## Scope and alternatives

The problem is the local multi-file package, before a server/CDN is involved.
[validate-hls](https://github.com/makandra/validate-hls) downloads streams and checks
frames/keyframes using Ruby, wget and ffmpeg. [Mamba](https://github.com/Comcast/mamba)
is a playlist library. This tool focuses on offline directory completeness, range
bounds and actionable machine-readable findings, without external tools at runtime.
The implementation and synthetic test data are original.

Version 0.1.0 is a selected structural preflight, not a complete RFC 8216 validator or a
playback certification. It does not inspect codecs, decode frames, verify keyframes,
compare actual media duration to EXTINF, validate audio/subtitle alignment, follow
network URLs, check HTTP/CORS/MIME behavior, or determine content integrity from hashes.
A nonempty corrupted segment without a range-size mismatch can pass. Case sensitivity
follows the host filesystem; use Linux CI for a deployment to a case-sensitive host.
LL-HLS, live/EVENT, encryption and unrecognized tags are intentionally incomplete.

Budgets: 1 MiB per playlist, 16 MiB of total playlist reads, 20,000 lines per playlist,
16,384 characters per line, 128 playlists, 10,000 references, depth 8 and 1,000 findings.
Numbers are bounded; duration syntax allows up to 10 integer and 9 fractional digits.
Budget exhaustion never produces a clean result. No package files are modified.

## Development and cleanup

```sh
python -m pip install -e . -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m build
python -m pip uninstall hls-vod-audit
```

No daemon, database or user cache is created. Redirected reports are ordinary files
under your control. See [contributing](CONTRIBUTING.md) and [security reporting](SECURITY.md).
