import json
import hashlib
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image
import refresh_activity as activity
import build_profile_assets as profile_assets

ROOT = Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    def test_latest_months_include_current_across_year(self):
        spans = activity.periods(date(2026, 1, 15))
        self.assertEqual(spans[0][0], date(2025, 8, 1))
        self.assertEqual(spans[-1], (date(2026, 1, 1), date(2026, 1, 15)))
        self.assertEqual(len(spans), 6)

    def test_october_is_included_and_partial(self):
        spans = activity.periods(date(2026, 10, 21))
        self.assertEqual(spans[0][0], date(2026, 5, 1))
        self.assertEqual(spans[-1], (date(2026, 10, 1), date(2026, 10, 21)))

    def test_window_rolls_on_first_day_of_next_month(self):
        spans = activity.periods(date(2026, 11, 1))
        self.assertEqual(spans[0][0], date(2026, 6, 1))
        self.assertEqual(spans[-1], (date(2026, 11, 1), date(2026, 11, 1)))

    def test_leap_month_remains_complete_when_previous(self):
        self.assertIn((date(2024, 2, 1), date(2024, 2, 29)), activity.periods(date(2024, 3, 1)))

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
            self.assertTrue((ROOT / relative.split("?", 1)[0]).is_file(), relative)

    def test_changed_images_have_content_versions_in_readme(self):
        readme = (ROOT / "README.md").read_text()
        for relative in ("assets/activity.gif", "assets/activity.svg", "assets/badges/antigravity.svg"):
            digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()[:12]
            self.assertIn('./' + relative + '?v=' + digest + '"', readme)

    def test_image_versioning_preserves_other_content_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "badge.svg").write_text("synthetic-image")
            (root / "README.md").write_text('<p>Preserve this text</p><img src="./badge.svg?v=old"><img src="./other.svg">')
            with patch.object(profile_assets, "ROOT", root):
                profile_assets.version_readme_asset("badge.svg")
                first = (root / "README.md").read_text()
                profile_assets.version_readme_asset("badge.svg")
            self.assertEqual(first, (root / "README.md").read_text())
            self.assertIn('<p>Preserve this text</p>', first)
            self.assertIn('src="./other.svg"', first)
            self.assertNotIn('?v=old', first)

    def test_svg_assets_are_local_and_inert(self):
        for asset in (ROOT / "assets").rglob("*.svg"):
            doc = ET.parse(asset).getroot()
            for node in doc.iter():
                self.assertNotIn(node.tag.rsplit("}", 1)[-1], ("script", "foreignObject"))
                for key, value in node.attrib.items():
                    self.assertFalse(key.startswith("on"), str(asset))
                    if key.endswith("href"):
                        self.assertTrue(value.startswith(("#", "data:image/png;base64,")), str(asset))

    def test_metrics_include_private_aggregates_without_details(self):
        data = json.loads((ROOT / "assets/activity.json").read_text())
        self.assertEqual(data["scope"], "personal_public_and_private")
        activity.validate_snapshot(data)
        self.assertEqual(len(data["months"]), 6)
        for row in data["months"]:
            for key in ("commits", "pull_requests", "repositories"):
                self.assertIs(type(row[key]), int)
                self.assertGreaterEqual(row[key], 0)
        self.assertNotIn("repositories_private", data)

    def test_no_authentication_does_not_fall_back_to_public(self):
        with patch.dict(activity.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Authentication"):
                activity.collect(date(2026, 10, 21))

    def test_wrong_account_is_rejected(self):
        with patch.dict(activity.os.environ, {"GH_TOKEN": "synthetic-test-value"}), patch.object(activity, "api", return_value={"login": "another-account"}):
            with self.assertRaisesRegex(RuntimeError, "LL0rddd"):
                activity.collect(date(2026, 10, 21))

    def test_private_included_foreign_owner_excluded_and_details_not_exported(self):
        def repo(owner, private, fork=False):
            return {"owner": {"login": owner}, "private": private, "fork": fork,
                    "created_at": "2026-04-01T00:00:00Z", "name": "INTERNAL_CANARY",
                    "description": "INTERNAL_DESCRIPTION", "html_url": "https://example.invalid/internal"}
        repos = [repo("LL0rddd", False), repo("LL0rddd", True),
                 repo("LL0rddd", False, True), repo("another-organization", True)]
        responses = [{"login": "LL0rddd", "owned_private_repos": 1}, repos]
        with patch.dict(activity.os.environ, {"GH_TOKEN": "synthetic-test-value"}), patch.object(activity, "api", side_effect=responses) as api_mock, patch.object(activity, "search_count", return_value=9) as searches:
            data = activity.collect(date(2026, 10, 21))
        self.assertIn("visibility=all&affiliation=owner", api_mock.call_args_list[1].args[0])
        self.assertEqual(data["months"][-1]["repositories"], 2)
        self.assertEqual(data["months"][-1]["commits"], 9)
        self.assertNotIn("INTERNAL_", json.dumps(data))
        self.assertNotIn("example.invalid", json.dumps(data))
        for call in searches.call_args_list:
            self.assertIn("user:LL0rddd", call.args[1])
            self.assertNotIn("is:public", call.args[1])
        activity.validate_snapshot(data)

    def test_partial_private_access_is_rejected_when_expected_count_known(self):
        private = {"owner": {"login": "LL0rddd"}, "private": True, "fork": False}
        with patch.dict(activity.os.environ, {"GH_TOKEN": "synthetic-test-value"}), patch.object(activity, "api", side_effect=[{"login": "LL0rddd", "owned_private_repos": 2}, [private]]):
            with self.assertRaisesRegex(RuntimeError, "Incomplete private"):
                activity.collect(date(2026, 10, 21))

    def test_zero_private_visibility_is_rejected(self):
        with patch.dict(activity.os.environ, {"GH_TOKEN": "synthetic-test-value"}), patch.object(activity, "api", side_effect=[{"login": "LL0rddd"}, []]):
            with self.assertRaisesRegex(RuntimeError, "No private"):
                activity.collect(date(2026, 10, 21))

    def test_repository_details_in_snapshot_are_rejected(self):
        data = json.loads((ROOT / "assets/activity.json").read_text())
        data["months"][0]["repository_name"] = "INTERNAL_CANARY"
        with self.assertRaisesRegex(ValueError, "Repository-level"):
            activity.validate_snapshot(data)

    def test_snapshot_missing_current_month_is_rejected(self):
        data = json.loads((ROOT / "assets/activity.json").read_text())
        data["months"][-1]["month"] = "2000-01"
        with self.assertRaisesRegex(ValueError, "latest six months"):
            activity.validate_snapshot(data)

    def test_work_icon_cells_reserve_space_for_github_padding(self):
        readme = (ROOT / "README.md").read_text()
        widths = re.findall(r'<td width="(\d+)"[^>]*><img src="\./assets/badges/(?:traceability|security|architecture|verification|supervision)\.svg" width="30" height="30"', readme)
        self.assertEqual(len(widths), 5)
        self.assertTrue(all(int(width) >= 62 for width in widths))

    def test_antigravity_matches_preview_gradient_and_font(self):
        doc = ET.parse(ROOT / "assets/badges/antigravity.svg").getroot()
        self.assertEqual(doc.attrib["height"], "28")
        self.assertEqual(doc.attrib["width"], "135")
        gradient = doc.find('.//{*}linearGradient')
        self.assertIsNotNone(gradient)
        self.assertEqual([stop.attrib["offset"] for stop in gradient], ["0%", "40%", "72%", "100%"])
        label = doc.find('.//{*}text')
        self.assertEqual(label.attrib["font-family"], "Segoe UI,system-ui,sans-serif")

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
