import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .audit import audit


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Preflight a local HLS VOD package without network access."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("playlist", type=Path)
    parser.add_argument(
        "--root", type=Path, help="package boundary; default is entry playlist's parent"
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        report = audit(args.playlist, args.root)
    except (OSError, RuntimeError):
        print("hls-vod-audit: unable to resolve package root", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    else:
        verdict = "PASS" if report["ok"] else ("INCOMPLETE" if not report["complete"] else "FAIL")
        summary = report["summary"]
        print(
            f"{verdict}: {summary['playlists']} playlists, {summary['unique_assets']} assets, "
            f"{summary['findings']} findings"
        )
        for finding in report["findings"]:
            # JSON escaping prevents terminal control sequences in user-controlled paths.
            label = json.dumps(finding["playlist"], ensure_ascii=True)
            print(f"{label}:{finding['line']} [{finding['code']}] {finding['message']}")
    return 0 if report["ok"] else (2 if not report["complete"] else 1)
