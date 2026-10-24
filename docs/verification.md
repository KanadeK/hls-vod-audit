# Release verification

Version 0.1.0: local verification uses Windows and CPython 3.13.16.

- 26 regression tests cover parsing, quote/comma handling, decimal rounding, variants,
  alternate audio, groups, cycles, missing/empty files, ranges, maps, root escapes,
  URI handling, unsupported features, budgets and the three CLI exit outcomes.
- The structural example passes, then detects shortened ranges and a missing asset.
- Optional real-media acceptance was actually run with local ffmpeg 7.1: four original
  generated MPEG-TS/fMP4 packages, with separate segments and single-file ranges, pass
  both structural checks and an independent full video decode. Deliberate segment
  deletions and one-byte range-file truncations are then detected in the four modes.
- Ruff lint/format and sdist/wheel builds pass. The wheel has no runtime dependencies.
  A clean wheel-only environment outside the checkout reruns tests and the example.
- Release requires all Ubuntu/Windows × Python 3.11/3.13 CI jobs to pass. CI runs the
  structural suite/example; optional ffmpeg acceptance is a separate local check.

Second-pass review checked incomplete-result precedence, root resolution, exact byte
range continuation, fixed traversal budgets and honest handling of unsupported tags.
It found a privacy edge case: urllib's URL-parser exception can echo the original netloc.
Only explicitly safe static diagnostics are now exposed; library exceptions are replaced
with a generic message. A regression test uses a synthetic credential-bearing invalid
Unicode netloc. No real credentials or user media are in the tests or repository.

The optional ffmpeg binary was obtained separately for development and is not included
in the wheel, source release or repository. Passing this preflight does not certify
decoding, alignment, actual durations, CORS, deployment case behavior or content integrity.
