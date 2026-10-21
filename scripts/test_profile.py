import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image
import refresh_activity as activity

ROOT = Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    def test_completed_months_across_year(self):
        spans = activity.periods(date(2026, 1, 15))
        self.assertEqual(spans[0][0], date(2025, 7, 1))
        self.assertEqual(spans[-1][1], date(2025, 12, 31))

    def test_incomplete_search_is_not_a_count(self):
        with patch.object(activity, "api", return_value={"incomplete_results": True, "total_count": 10}):
            with self.assertRaises(RuntimeError):
                activity.search_count("commits", "public")

    def test_raw_bytes_preserved_without_token(self):
        raw = b'{"total_count":0,"note":"CRLF\r\nretained"}'
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return raw
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / "raw" / "run"
            with patch.object(activity, "RAW_RUN", run), patch.object(activity.urllib.request, "urlopen", return_value=Response()), patch.object(activity.json, "loads", return_value={}):
                activity.api("test-public")
            files = list(run.iterdir())
            self.assertEqual(files[0].read_bytes(), raw)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(run.stat().st_mode & 0o777, 0o700)

    def test_all_readme_assets_exist(self):
        readme = (ROOT / "README.md").read_text()
        for relative in re.findall(r'(?:src|srcset)="\./([^" ]+)"', readme):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_svg_assets_are_local_and_inert(self):
        for asset in (ROOT / "assets").rglob("*.svg"):
            doc = ET.parse(asset).getroot()
            for node in doc.iter():
                self.assertNotIn(node.tag.rsplit("}", 1)[-1], ("script", "foreignObject"))
                for key, value in node.attrib.items():
                    self.assertFalse(key.startswith("on"), str(asset))
                    if key.endswith("href"):
                        self.assertTrue(value.startswith(("#", "data:image/png;base64,")), str(asset))

    def test_metrics_are_public_and_complete(self):
        data = json.loads((ROOT / "assets/activity.json").read_text())
        self.assertEqual(data["scope"], "public_only")
        self.assertEqual(len(data["months"]), 6)
        for row in data["months"]:
            for key in ("commits", "pull_requests", "repositories"):
                self.assertIs(type(row[key]), int)
                self.assertGreaterEqual(row[key], 0)
        self.assertNotIn("repositories_private", data)

    def test_animation_is_finite_with_static_fallback(self):
        with Image.open(ROOT / "assets/activity.gif") as image:
            self.assertGreater(image.n_frames, 1)
            self.assertNotIn("loop", image.info)
            self.assertEqual(image.size, (1160, 410))
        self.assertIn("prefers-reduced-motion", (ROOT / "README.md").read_text())

    def test_private_project_order_and_pending_title_preserved(self):
        readme = (ROOT / "README.md").read_text()
        positions = [readme.index('alt="' + name + '"') for name in
                     ("Prompt Forge", "Requests Automations", "Jira Issue Analyzer", "Clean Git Commit")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("estão privados no momento", readme)
        self.assertIn("Posicionamento profissional a definir", readme)
        self.assertNotIn("Sicredi", readme)
        self.assertNotIn("File Insight", readme)


if __name__ == "__main__":
    unittest.main()
