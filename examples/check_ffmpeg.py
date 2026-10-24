"""Optional acceptance with real, locally generated and decoded video packages."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from hls_vod_audit.audit import audit

parser = argparse.ArgumentParser()
parser.add_argument(
    "--ffmpeg", default="ffmpeg", help="path to a local ffmpeg with libx264 and lavfi"
)
args = parser.parse_args()
checks = []
with tempfile.TemporaryDirectory() as scratch:
    for kind, single in (("mpegts", False), ("fmp4", False), ("mpegts", True), ("fmp4", True)):
        root = Path(scratch) / f"{kind}-{single}"
        root.mkdir()
        command = [
            args.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=128x72:r=10",
            "-t",
            "4",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "10",
            "-sc_threshold",
            "0",
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_playlist_type",
            "vod",
            "-hls_segment_type",
            kind,
        ]
        if single:
            command += ["-hls_flags", "single_file"]
        subprocess.run(
            [*command, "index.m3u8"], cwd=root, check=True, capture_output=True, timeout=60
        )
        entry = root / "index.m3u8"
        report = audit(entry)
        if not report["ok"]:
            raise SystemExit(json.dumps(report))
        # Decode separately: structural acceptance alone cannot prove playback.
        subprocess.run(
            [
                args.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-protocol_whitelist",
                "file,crypto,data",
                "-i",
                str(entry),
                "-map",
                "0:v:0",
                "-f",
                "null",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        segment = next(p for p in root.iterdir() if p.suffix in {".ts", ".m4s"})
        if single:
            segment.write_bytes(segment.read_bytes()[:-1])
            expected = "range_out_of_bounds"
        else:
            segment.unlink()
            expected = "missing_asset"
        damaged = audit(entry)
        if damaged["ok"] or expected not in [f["code"] for f in damaged["findings"]]:
            raise SystemExit("Intentional defect was not detected")
        checks.append(
            {
                "format": kind,
                "single_file": single,
                "structural_pass": True,
                "ffmpeg_decode_pass": True,
                "detected": expected,
            }
        )
print(json.dumps({"real_media_acceptance": checks}, sort_keys=True))
