# Design and supported boundaries

User: a publisher with a local HLS VOD directory, preparing an upload. Acceptance:
enumerate reachable supported playlists and asset references without network traffic;
report missing/empty files and range-size mismatches with a source line; never label
unsupported or uninspected content as fully checked.

`parser.py` parses bounded UTF-8 text, quoted attribute lists, positive decimal durations,
and relevant tags into references. `audit.py` traverses the reference graph, enforces a
root boundary, stats regular files and checks byte spans. `cli.py` presents text/JSON and
the 0/1/2 exit contract. It does not import any network client or execute a command.

Checks are based on [RFC 8216](https://www.rfc-editor.org/rfc/rfc8216.html). A duration
is compared after nearest-integer rounding with positive ties rounded up. Byte-range
continuation requires the immediately preceding media segment to be a byte range of the
same resolved file; initialization ranges do not replace that previous-segment state.
An initialization-map range without an explicit offset is outside this implementation.
Exact Decimal sums avoid binary floating-point drift. No actual media duration is inferred.

Supported tags: EXTM3U, EXT-X-VERSION (1–7), EXT-X-TARGETDURATION, EXTINF,
EXT-X-BYTERANGE, EXT-X-MAP, EXT-X-ENDLIST, EXT-X-PLAYLIST-TYPE:VOD,
EXT-X-MEDIA-SEQUENCE, EXT-X-DISCONTINUITY-SEQUENCE, EXT-X-DISCONTINUITY,
EXT-X-INDEPENDENT-SEGMENTS, EXT-X-STREAM-INF, EXT-X-MEDIA, and EXT-X-KEY:METHOD=NONE.
Not every attribute or cross-rendition constraint is validated. Informational attributes
such as CODECS are parsed but are not compared to media payloads. Independence and
discontinuity tags do not certify keyframes or correct decoding. Unknown EXT tags,
encrypted keys, versions above 7 and EVENT leave `complete=false`.

Resolution accepts relative URI paths, percent-decodes once, rejects control characters,
network/query/fragment references, backslashes and colons, then resolves and checks root
containment. Referenced symbolic links are rejected. Windows junction resolution is
subject to the platform's pathlib behavior. Filesystem mutation races are outside scope.
Paths are not a general security sandbox; use trusted stable local packages.

Budgets cap manifests, traversal, references, output findings and depth. Malformed input,
unreadable children and resource exhaustion produce incomplete results. File payloads
are not opened. A missing segment is a completed negative check; a missing child playlist
is incomplete because its own references could not be examined. Cycles are defects and
terminate traversal. Findings do not echo raw URI strings, which may contain credentials.

Tests use original, explicitly non-playable structural bytes for exact corner cases.
The optional ffmpeg acceptance script independently generates and decodes playable
test video, then plants missing-file/range-length failures. ffmpeg is not vendored,
linked into the package, required by users, or run on user media by the checker.
