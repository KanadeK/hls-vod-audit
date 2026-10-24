"""Synthetic structural fixtures are not advertised as playable media."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as scratch:
    root = Path(scratch)
    asset = root / "data.bin"
    asset.write_bytes(bytes(range(32)))
    (root / "master.m3u8").write_text(
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800\nindex.m3u8\n", encoding="utf-8"
    )
    (root / "index.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-TARGETDURATION:1\n"
        '#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-MAP:URI="data.bin",BYTERANGE="4@0"\n'
        "#EXTINF:1.0,\n#EXT-X-BYTERANGE:8@4\ndata.bin\n"
        "#EXTINF:1.0,\n#EXT-X-BYTERANGE:8\ndata.bin\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )

    def check(expected, code=None):
        result = subprocess.run(
            [sys.executable, "-m", "hls_vod_audit", str(root / "master.m3u8"), "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        report = json.loads(result.stdout)
        if result.returncode != expected or (
            code and code not in [f["code"] for f in report["findings"]]
        ):
            raise SystemExit(result.stdout + result.stderr)
        return report

    good = check(0)
    asset.write_bytes(b"1234567890")
    check(1, "range_out_of_bounds")
    asset.unlink()
    check(1, "missing_asset")
    print(
        json.dumps(
            {
                "structural_example": "passed",
                "good_package": good["summary"],
                "detected": ["truncated byte ranges", "missing asset"],
            }
        )
    )
