import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hls_vod_audit.audit import audit
from hls_vod_audit.parser import ParseError, attributes, byte_range, parse


def media(uri="part.ts", duration="1.5", target=2, version=3, extra=""):
    return (
        f"#EXTM3U\n#EXT-X-VERSION:{version}\n#EXT-X-TARGETDURATION:{target}\n"
        f"{extra}#EXTINF:{duration},\n{uri}\n#EXT-X-ENDLIST\n"
    )


class ParserTests(unittest.TestCase):
    def test_quoted_commas_and_duplicate_attributes(self):
        self.assertEqual(attributes('BANDWIDTH=100,CODECS="a,b"')["CODECS"], "a,b")
        for value in ('URI="a",URI="b"', "URI=a", 'URI="a",', 'URI="unterminated'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                attributes(value)

    def test_byte_range_syntax(self):
        self.assertEqual(byte_range("8@4"), (8, 4))
        self.assertEqual(byte_range("8"), (8, None))
        for value in ("0@0", "-1@0", "8@-1", "4@2@1", "8@18446744073709551616"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                byte_range(value)

    def test_encoding_header_and_control_characters(self):
        for value in (b"\xff", b"\xef\xbb\xbf#EXTM3U\n", b"#EXTM3U\n\0", b"hello"):
            with self.subTest(value=value), self.assertRaises(ParseError):
                parse(value)

    def test_invalid_duration_and_pending_tags(self):
        for value in ("NaN", "Infinity", "-1", "1e9", "0", "1.1234567890"):
            with self.subTest(value=value), self.assertRaises(ParseError):
                parse(media(duration=value).encode())
        for value in (
            "#EXTM3U\n#EXTINF:1,\n",
            "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\n",
            "#EXTM3U\npart.ts\n",
        ):
            with self.assertRaises(ParseError):
                parse(value.encode())

    def test_duplicate_and_mixed_tags(self):
        for text in (
            media() + "#EXT-X-ENDLIST\n",
            media() + "#EXT-X-STREAM-INF:BANDWIDTH=100\nother.m3u8\n",
        ):
            with self.assertRaises(ParseError):
                parse(text.encode())

    def test_target_duration_nearest_integer(self):
        safe = parse(media(duration="6.499999999", target=6).encode())
        bad = parse(media(duration="6.500000000", target=6).encode())
        self.assertNotIn("target_duration", [x[0] for x in safe.findings])
        self.assertIn("target_duration", [x[0] for x in bad.findings])

    def test_version_requirements(self):
        self.assertIn("version_too_low", [x[0] for x in parse(media(version=1).encode()).findings])
        self.assertIn(
            "version_too_low",
            [
                x[0]
                for x in parse(media(version=3, extra="#EXT-X-BYTERANGE:8@0\n").encode()).findings
            ],
        )


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.parent = Path(self.scratch.name)
        self.root = self.parent / "package"
        self.root.mkdir()
        self.entry = self.root / "index.m3u8"
        (self.root / "part.ts").write_bytes(b"original structural test bytes")

    def tearDown(self):
        self.scratch.cleanup()

    def run_audit(self, text=None):
        if text is not None:
            self.entry.write_text(text, encoding="utf-8", newline="\n")
        return audit(self.entry)

    def codes(self, report):
        return [finding["code"] for finding in report["findings"]]

    def test_valid_vod_and_exact_decimal_total(self):
        report = self.run_audit(media())
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"]["unique_assets"], 1)
        self.assertEqual(report["playlists"][0]["duration_seconds"], "1.5")

    def test_missing_and_empty_segment(self):
        (self.root / "part.ts").unlink()
        report = self.run_audit(media())
        self.assertTrue(report["complete"])
        self.assertIn("missing_asset", self.codes(report))
        (self.root / "part.ts").write_bytes(b"")
        self.assertIn("empty_asset", self.codes(self.run_audit()))

    def test_master_and_alternate_audio_traversal(self):
        (self.root / "video.m3u8").write_text(media())
        (self.root / "audio.m3u8").write_text(media())
        report = self.run_audit(
            '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",URI="audio.m3u8"\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=1000,AUDIO="aud",CODECS="v,a"\nvideo.m3u8\n'
        )
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"]["playlists"], 3)
        self.assertEqual(report["summary"]["unique_assets"], 1)

    def test_undefined_rendition_group(self):
        (self.root / "video.m3u8").write_text(media())
        report = self.run_audit(
            '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,AUDIO="missing"\nvideo.m3u8\n'
        )
        self.assertIn("missing_rendition_group", self.codes(report))

    def test_playlist_cycle_and_nested_master(self):
        report = self.run_audit("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nindex.m3u8\n")
        self.assertIn("playlist_cycle", self.codes(report))
        (self.root / "child.m3u8").write_text(
            "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nleaf.m3u8\n"
        )
        (self.root / "leaf.m3u8").write_text(media())
        report = self.run_audit("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nchild.m3u8\n")
        self.assertIn("nested_master", self.codes(report))

    def test_missing_child_playlist_is_incomplete(self):
        report = self.run_audit("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nmissing.m3u8\n")
        self.assertFalse(report["complete"])
        self.assertIn("missing_playlist", self.codes(report))

    def test_root_escape_and_encoded_traversal(self):
        (self.parent / "outside.ts").write_bytes(b"private data never read")
        for uri in (
            "../outside.ts",
            "%2e%2e/outside.ts",
            "%2foutside.ts",
            "C:/outside.ts",
            "x\\outside.ts",
        ):
            with self.subTest(uri=uri):
                report = self.run_audit(media(uri=uri))
                self.assertFalse(report["complete"])
                self.assertIn("unsupported_uri", self.codes(report))
                self.assertEqual(report["summary"]["unique_assets"], 0)

    def test_remote_uris_queries_and_bad_escapes_are_never_fetched(self):
        for uri in (
            "https://example.invalid/seg.ts?secret=privatevalue",
            "//example.invalid/seg.ts",
            "part.ts?secret=privatevalue",
            "part.ts#fragment",
            "%ff.ts",
            "%ZZ.ts",
            "part%00.ts",
        ):
            with self.subTest(uri=uri), patch("socket.create_connection") as network:
                report = self.run_audit(media(uri=uri))
                self.assertFalse(report["complete"])
                self.assertNotIn("privatevalue", json.dumps(report))
                network.assert_not_called()

    def test_percent_encoded_file_name(self):
        (self.root / "with space.ts").write_bytes(b"bytes")
        self.assertTrue(self.run_audit(media(uri="with%20space.ts"))["ok"])

    def test_url_parser_errors_do_not_echo_sensitive_uri(self):
        # urlsplit can include a complete netloc in its NFKC-error exception text.
        uri = "https://user:privatevalue@exa\uff0fmple.invalid/segment.ts"
        report = self.run_audit(media(uri=uri))
        self.assertFalse(report["complete"])
        self.assertNotIn("privatevalue", json.dumps(report))
        self.assertIn("unsupported_uri", self.codes(report))

    def test_byte_range_implicit_continuation(self):
        text = "#EXTM3U\n#EXT-X-VERSION:4\n#EXT-X-TARGETDURATION:1\n"
        text += "#EXTINF:1,\n#EXT-X-BYTERANGE:8@0\npart.ts\n"
        text += "#EXTINF:1,\n#EXT-X-BYTERANGE:8\npart.ts\n#EXT-X-ENDLIST\n"
        self.assertTrue(self.run_audit(text)["ok"])
        (self.root / "part.ts").write_bytes(b"1234567890")
        self.assertIn("range_out_of_bounds", self.codes(self.run_audit()))

    def test_implicit_range_requires_previous_range_in_same_file(self):
        self.assertIn(
            "implicit_range",
            self.codes(self.run_audit(media(version=4, extra="#EXT-X-BYTERANGE:8\n"))),
        )
        (self.root / "other.ts").write_bytes(b"long enough for eight bytes")
        text = "#EXTM3U\n#EXT-X-VERSION:4\n#EXT-X-TARGETDURATION:1\n"
        text += "#EXTINF:1,\n#EXT-X-BYTERANGE:8@0\npart.ts\n"
        text += "#EXTINF:1,\n#EXT-X-BYTERANGE:8\nother.ts\n#EXT-X-ENDLIST\n"
        self.assertIn("implicit_range", self.codes(self.run_audit(text)))

    def test_map_existence_and_range(self):
        (self.root / "init.mp4").write_bytes(b"1234")
        text = media(version=7, extra='#EXT-X-MAP:URI="init.mp4",BYTERANGE="4@0"\n')
        self.assertTrue(self.run_audit(text)["ok"])
        self.assertIn("range_out_of_bounds", self.codes(self.run_audit(text.replace("4@0", "5@0"))))
        self.assertFalse(self.run_audit(text.replace("4@0", "4"))["complete"])
        (self.root / "init.mp4").unlink()
        self.assertIn("missing_asset", self.codes(self.run_audit(text)))

    def test_unknown_tags_and_encryption_fail_closed(self):
        for extra in (
            '#EXT-X-PART:DURATION=1,URI="x"\n',
            '#EXT-X-KEY:METHOD=AES-128,URI="secret.key"\n',
        ):
            report = self.run_audit(media(extra=extra))
            self.assertFalse(report["complete"])
            self.assertFalse(report["ok"])

    def test_empty_and_non_vod_playlists(self):
        self.assertIn("empty_media", self.codes(self.run_audit("#EXTM3U\n#EXT-X-ENDLIST\n")))
        self.assertIn(
            "missing_endlist", self.codes(self.run_audit(media().replace("#EXT-X-ENDLIST\n", "")))
        )
        self.assertFalse(self.run_audit(media(extra="#EXT-X-PLAYLIST-TYPE:EVENT\n"))["complete"])

    def test_nonregular_and_unreadable_inputs(self):
        (self.root / "folder").mkdir()
        self.assertFalse(self.run_audit(media(uri="folder"))["complete"])
        self.assertFalse(audit(self.root / "absent.m3u8")["complete"])
        self.assertFalse(audit(self.entry, self.root / "different")["complete"])

    def test_resource_budgets_never_pass(self):
        self.entry.write_text(media())
        for constant, value in (
            ("MAX_PLAYLIST_BYTES", 5),
            ("MAX_TOTAL_BYTES", 5),
            ("MAX_REFERENCES", 0),
            ("MAX_PLAYLISTS", 0),
        ):
            with self.subTest(constant=constant), patch("hls_vod_audit.audit." + constant, value):
                self.assertFalse(self.run_audit()["complete"])
        with patch("hls_vod_audit.parser.MAX_LINES", 2):
            self.assertFalse(self.run_audit()["complete"])
        self.entry.write_text(media(uri="missing.ts", target=1))
        with patch("hls_vod_audit.audit.MAX_FINDINGS", 1):
            self.assertFalse(self.run_audit()["complete"])

    def test_explicit_root_supports_shared_parent_asset(self):
        sub = self.root / "video"
        sub.mkdir()
        entry = sub / "index.m3u8"
        entry.write_text(media(uri="../part.ts"))
        self.assertFalse(audit(entry)["ok"])
        self.assertTrue(audit(entry, self.root)["ok"])

    def test_cli_exit_codes_and_json(self):
        self.entry.write_text(media())
        for uri, expected in (("part.ts", 0), ("missing.ts", 1), ("https://example.invalid/a", 2)):
            self.entry.write_text(media(uri=uri))
            result = subprocess.run(
                [sys.executable, "-m", "hls_vod_audit", str(self.entry), "--format", "json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertEqual(json.loads(result.stdout)["ok"], expected == 0)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
