import json
import hashlib
import io
import re
import ssl
import tempfile
import unittest
from datetime import date
from email.message import Message
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
        with patch.object(activity, "api", return_value={"incomplete_results": True, "total_count": 10}), patch.object(activity.time, "sleep"):
            with self.assertRaises(RuntimeError):
                activity.search_count("commits", "public")

    def test_raw_bytes_preserved_without_token(self):
        raw = b'{"total_count":0,"note":"CRLF\r\nretained"}'
        class Response:
            headers = {}
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return raw
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / "raw" / "run"
            with patch.object(activity, "RAW_RUN", run), patch.object(activity.urllib.request, "urlopen", return_value=Response()), patch.object(activity.json, "loads", return_value={}):
                activity.api("test-public")
            files = list(run.glob("*.body"))
            self.assertEqual(files[0].read_bytes(), raw)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(run.stat().st_mode & 0o777, 0o700)
            metadata = json.loads(next(run.glob("*.meta.json")).read_text())
            self.assertEqual(metadata["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(metadata["bytes"], len(raw))

    def test_all_readme_assets_exist(self):
        readme = (ROOT / "README.md").read_text()
        for relative in re.findall(r'(?:src|srcset)="\./([^" ]+)"', readme):
            self.assertTrue((ROOT / relative.split("?", 1)[0]).is_file(), relative)

    def test_changed_images_have_content_versions_in_readme(self):
        readme = (ROOT / "README.md").read_text()
        for relative in ("assets/activity.gif", "assets/activity.svg", "assets/badges/antigravity.svg"):
            digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()[:12]
            source = Path(relative)
            versioned = Path("assets/versioned") / (source.stem + "-" + digest + source.suffix)
            self.assertIn('./' + versioned.as_posix() + '"', readme)
            self.assertEqual((ROOT / versioned).read_bytes(), (ROOT / relative).read_bytes())

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
            self.assertEqual((root / "badge.svg").read_text(), "synthetic-image")
            original_versions = list((root / "assets/versioned").iterdir())
            (root / "badge.svg").write_text("updated-image")
            with patch.object(profile_assets, "ROOT", root):
                profile_assets.version_readme_asset("badge.svg")
            self.assertEqual(len(list((root / "assets/versioned").iterdir())), 2)
            self.assertEqual(original_versions[0].read_text(), "synthetic-image")

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

    def test_authored_activity_includes_collaborations_but_repo_counter_is_owned_only(self):
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
            self.assertIn("author:LL0rddd", call.args[1])
            self.assertNotIn("user:", call.args[1])
            self.assertNotIn("org:", call.args[1])
            self.assertNotIn("repo:", call.args[1])
            self.assertNotIn("is:public", call.args[1])
        self.assertEqual(len(searches.call_args_list), 12)
        for index in range(0, 12, 2):
            self.assertEqual(searches.call_args_list[index].args[0], "commits")
            self.assertIn("author-date:", searches.call_args_list[index].args[1])
            pr_query = searches.call_args_list[index + 1].args[1]
            self.assertIn("is:pr created:", pr_query)
            self.assertNotIn("is:merged", pr_query)
            self.assertNotIn("is:open", pr_query)
        activity.validate_snapshot(data)

    def test_search_url_preserves_global_author_and_returns_aggregate_only(self):
        query = "author:LL0rddd is:pr created:2026-10-01..2026-10-22"
        with patch.object(activity, "api", return_value={
            "incomplete_results": False, "total_count": 17,
            "items": [{"title": "PRIVATE_CANARY", "html_url": "https://example.invalid/private"}],
        }) as api_mock:
            count = activity.search_count("issues", query)
        endpoint = api_mock.call_args.args[0]
        parsed = activity.urllib.parse.parse_qs(activity.urllib.parse.urlsplit(endpoint).query)
        self.assertEqual(parsed["q"], [query])
        self.assertEqual(count, 17)
        self.assertIs(type(count), int)

    def test_workflow_updates_hourly_without_exposing_credentials_or_raw_data(self):
        workflow = (ROOT / ".github/workflows/refresh-activity.yml").read_text()
        self.assertIn("cron: '17 * * * *'", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("secrets.PROFILE_METRICS_TOKEN", workflow)
        self.assertIn("python scripts/refresh_activity.py", workflow)
        self.assertEqual(workflow.count("python -m unittest discover"), 2)
        self.assertNotIn("pull_request", workflow)
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn(".metrics-raw", workflow)
        self.assertNotIn("--force", workflow)
        self.assertNotIn("git add .", workflow)
        self.assertIn("git push origin HEAD:refs/heads/main", workflow)
        self.assertIn("41898282+github-actions[bot]", workflow)
        self.assertEqual(len(re.findall(r"uses: actions/[a-z-]+@[0-9a-f]{40}", workflow)), 2)

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


class RecoveryTests(unittest.TestCase):
    complete = {"total_count": 7, "incomplete_results": False}
    incomplete = {"total_count": 999, "incomplete_results": True}

    class Response:
        status = 200
        headers = {"X-GitHub-Request-Id": "synthetic-request"}

        def __init__(self, raw=b'{"ok":true}'):
            self.raw = raw

        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return self.raw

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.run = Path(self.folder.name) / "raw" / "run"
        raw_patch = patch.object(activity, "RAW_RUN", self.run)
        raw_patch.start()
        self.addCleanup(raw_patch.stop)
        sleep_patch = patch.object(activity.time, "sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        output_patch = patch("sys.stdout", new_callable=io.StringIO)
        self.stdout = output_patch.start()
        self.addCleanup(output_patch.stop)

    def error(self, code, headers=None, body=b'{"message":"temporary"}'):
        return activity.urllib.error.HTTPError("https://api.github.com/test", code, "error", headers or {}, io.BytesIO(body))

    def test_incomplete_search_recovers_after_backoff(self):
        with patch.object(activity, "api", side_effect=[self.incomplete, self.incomplete, self.complete]) as call:
            self.assertEqual(activity.search_count("commits", "author:LL0rddd"), 7)
        self.assertEqual(call.call_count, 3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [2, 4])

    def test_month_split_has_no_overlap_and_discards_partial_parent_count(self):
        query = "author:LL0rddd is:pr created:2026-10-01..2026-10-31"
        results = [self.incomplete] * 3 + [dict(self.complete, total_count=20), dict(self.complete, total_count=30)]
        with patch.object(activity, "api", side_effect=results) as call:
            self.assertEqual(activity.search_count("issues", query), 50)
        queries = [activity.urllib.parse.parse_qs(activity.urllib.parse.urlsplit(c.args[0]).query)["q"][0]
                   for c in call.call_args_list]
        self.assertEqual(queries[:3], [query] * 3)
        self.assertEqual(queries[3:], ["author:LL0rddd is:pr created:2026-10-01..2026-10-16",
                                       "author:LL0rddd is:pr created:2026-10-17..2026-10-31"])
        self.assertIs(call.call_args_list[0].kwargs["budget"], call.call_args_list[-1].kwargs["budget"])

    def test_recursive_split_handles_leap_day_and_keeps_author_scope(self):
        query = "author:LL0rddd author-date:2024-02-27..2024-03-01"
        results = [self.incomplete] * 6 + [dict(self.complete, total_count=1),
                                         dict(self.complete, total_count=2), dict(self.complete, total_count=3)]
        with patch.object(activity, "api", side_effect=results) as call:
            self.assertEqual(activity.search_count("commits", query), 6)
        queries = [activity.urllib.parse.unquote(c.args[0]) for c in call.call_args_list]
        self.assertIn("author-date:2024-02-29..2024-03-01", queries[-1])
        self.assertTrue(all("author:LL0rddd" in q and "user:" not in q and "repo:" not in q for q in queries))

    def test_single_day_exhaustion_fails_without_accepting_incomplete_count(self):
        with patch.object(activity, "api", return_value=self.incomplete) as call:
            with self.assertRaisesRegex(activity.CollectionUnavailable, "commits.*2026-10-26.*previous assets"):
                activity.search_count("commits", "author:LL0rddd author-date:2026-10-26..2026-10-26")
        self.assertEqual(call.call_count, 3)

    def test_missing_or_invalid_search_fields_never_become_zero(self):
        for payload in ({}, [], {"incomplete_results": False, "total_count": True},
                        {"incomplete_results": False, "total_count": -1},
                        {"incomplete_results": False, "total_count": "7"},
                        {"total_count": 7}, {"incomplete_results": "false", "total_count": 7}):
            with self.subTest(payload=payload), patch.object(activity, "api", return_value=payload) as call:
                with self.assertRaisesRegex(activity.CollectionUnavailable, "Invalid search response"):
                    activity.search_count("commits", "author:LL0rddd")
                self.assertEqual(call.call_count, 1)

    def test_complete_zero_is_valid(self):
        with patch.object(activity, "api", return_value=dict(self.complete, total_count=0)):
            self.assertEqual(activity.search_count("issues", "author:LL0rddd is:pr"), 0)
        self.sleep.assert_not_called()

    def test_http_503_retry_preserves_all_responses_and_diagnostic_headers(self):
        first = b'{"message":"try later"}\r\n'
        error = self.error(503, {"Retry-After": "7", "X-GitHub-Request-Id": "synthetic-503"}, first)
        with patch.object(activity.urllib.request, "urlopen", side_effect=[error, self.Response()]) as call:
            self.assertEqual(activity.api("user"), {"ok": True})
        self.assertEqual(call.call_count, 2)
        self.sleep.assert_called_once_with(7)
        self.assertEqual({p.read_bytes() for p in self.run.glob("*.body")}, {first, b'{"ok":true}'})
        metadata = [json.loads(p.read_text()) for p in self.run.glob("*.meta.json")]
        self.assertEqual({m["status"] for m in metadata}, {200, 503})
        self.assertIn("synthetic-503", [m["headers"]["x-github-request-id"] for m in metadata])

    def test_rate_limit_retry_respects_reset_and_does_not_hammer_api(self):
        headers = {"Retry-After": "5", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1010"}
        with patch.object(activity.time, "time", return_value=1000), patch.object(activity.urllib.request, "urlopen", side_effect=[self.error(403, headers), self.Response()]):
            activity.api("user")
        self.sleep.assert_called_once_with(11)

    def test_timeout_reading_http_error_body_preserves_status_and_retries(self):
        error = self.error(503, {"X-GitHub-Request-Id": "timeout-body"})
        with patch.object(error, "read", side_effect=TimeoutError()), patch.object(activity.urllib.request, "urlopen", side_effect=[error, self.Response()]):
            self.assertEqual(activity.api("user"), {"ok": True})
        metadata = [json.loads(p.read_text()) for p in self.run.glob("*.meta.json")]
        partial = next(m for m in metadata if m["status"] == 503)
        self.assertIn("partial error body", partial["category"])
        self.assertEqual(partial["headers"]["x-github-request-id"], "timeout-body")

    def test_secondary_rate_limit_without_headers_waits_a_minute(self):
        error = self.error(403, body=b'{"message":"You have exceeded a secondary rate limit"}')
        with patch.object(activity.urllib.request, "urlopen", side_effect=[error, self.Response()]):
            activity.api("user")
        self.sleep.assert_called_once_with(60)

    def test_retry_after_http_date_is_respected(self):
        with patch.object(activity.time, "time", return_value=0):
            self.assertEqual(activity.retry_delay({"Retry-After": "Thu, 01 Jan 1970 00:01:30 GMT"}, 1, True), 90)

    def test_long_rate_limit_aborts_without_retrying_early(self):
        with patch.object(activity.urllib.request, "urlopen", side_effect=self.error(429, {"Retry-After": "900"})) as call:
            with self.assertRaisesRegex(activity.CollectionUnavailable, "retry wait exceeds"):
                activity.api("user")
        self.assertEqual(call.call_count, 1)
        self.sleep.assert_not_called()

    def test_authentication_and_permission_errors_are_not_retried(self):
        for code in (401, 403, 404, 422):
            with self.subTest(code=code), patch.object(activity.urllib.request, "urlopen", side_effect=self.error(code)) as call:
                with self.assertRaisesRegex(activity.CollectionUnavailable, f"HTTP {code}.*verify access"):
                    activity.api("user")
                self.assertEqual(call.call_count, 1)
        self.sleep.assert_not_called()

    def test_timeout_network_and_invalid_json_recover_with_finite_attempts(self):
        failures = (TimeoutError(), activity.urllib.error.URLError("synthetic"), self.Response(b'not json'))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch.object(activity.urllib.request, "urlopen", side_effect=[failure, self.Response()]):
                self.assertEqual(activity.api("user"), {"ok": True})

    def test_network_retry_exhaustion_is_bounded(self):
        with patch.object(activity.urllib.request, "urlopen", side_effect=TimeoutError()) as call:
            with self.assertRaisesRegex(activity.CollectionUnavailable, "retry attempts exhausted"):
                activity.api("user")
        self.assertEqual(call.call_count, 3)
        self.assertEqual(len(list(self.run.glob("*.body"))), 3)

    def test_partial_response_bytes_are_saved_before_retry(self):
        class PartialResponse(self.Response):
            def read(self):
                raise activity.http.client.IncompleteRead(b'partial\r\n\xff', 20)
        with patch.object(activity.urllib.request, "urlopen", side_effect=[PartialResponse(), self.Response()]):
            activity.api("user")
        self.assertIn(b'partial\r\n\xff', [p.read_bytes() for p in self.run.glob("*.body")])

    def test_repeated_endpoint_does_not_overwrite_raw_or_record_request_secrets(self):
        class Response(self.Response):
            headers = {"X-GitHub-Request-Id": "synthetic-id", "Set-Cookie": "RESPONSE_SECRET"}
        with patch.dict(activity.os.environ, {"GH_TOKEN": "REQUEST_SECRET_CANARY"}), patch.object(activity.urllib.request, "urlopen", return_value=Response()):
            activity.api("user")
            activity.api("user")
        self.assertEqual(len(list(self.run.glob("*.body"))), 2)
        self.assertEqual(len(list(self.run.glob("*.meta.json"))), 2)
        for saved in self.run.iterdir():
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(b'REQUEST_SECRET_CANARY', saved.read_bytes())
            self.assertNotIn(b'RESPONSE_SECRET', saved.read_bytes())

    def test_search_budget_counts_http_retries_and_stops_before_next_request(self):
        budget = activity.CollectionBudget()
        with patch.object(activity, "MAX_SEARCH_REQUESTS", 2), patch.object(activity.urllib.request, "urlopen", side_effect=TimeoutError()) as call:
            with self.assertRaisesRegex(activity.CollectionUnavailable, "Search request budget"):
                activity.api("search/commits?q=author:LL0rddd", budget=budget)
        self.assertEqual(call.call_count, 2)

    def test_time_budget_prevents_sleep_and_request_after_deadline(self):
        budget = activity.CollectionBudget()
        budget.deadline = activity.time.monotonic() - 1
        with self.assertRaisesRegex(activity.CollectionUnavailable, "time budget"):
            budget.timeout()
        with self.assertRaisesRegex(activity.CollectionUnavailable, "retry wait exceeds"):
            budget.wait(2, "test")
        with patch.object(activity.urllib.request, "urlopen") as call:
            with self.assertRaises(activity.CollectionUnavailable):
                activity.api("user", budget=budget)
        call.assert_not_called()
        self.sleep.assert_not_called()

    def test_failed_collection_does_not_render_or_replace_previous_dashboard(self):
        root = Path(self.folder.name) / "profile"
        (root / "assets").mkdir(parents=True)
        for relative in ("README.md", "assets/activity.json", "assets/activity.svg", "assets/activity.gif"):
            (root / relative).write_bytes(b'previous-complete-dashboard')
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        with patch.object(activity, "ROOT", root), patch.object(activity, "collect", side_effect=activity.CollectionUnavailable("synthetic failure")), patch.object(activity, "render") as render, patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:
                activity.main([])
        self.assertEqual(error.exception.code, 1)
        render.assert_not_called()
        self.assertEqual(before, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_response_headers_keep_duplicates_sso_and_scopes_with_cookie_masking(self):
        headers = Message()
        headers.add_header("Link", "<https://api.github.com/example?page=2>; rel=next")
        headers.add_header("Link", "<https://api.github.com/example?page=3>; rel=last")
        headers.add_header("X-GitHub-SSO", "required; url=https://github.com/orgs/PRIVATE_ORG/sso")
        headers.add_header("X-OAuth-Scopes", "repo, workflow")
        headers.add_header("GitHub-Authentication-Token-Expiration", "2027-01-01 00:00:00 UTC")
        headers.add_header("Set-Cookie", "PRIVATE_COOKIE_VALUE_123456789")
        headers.add_header("Set-Cookie", "SHORT")
        response = self.Response()
        response.headers = headers
        with patch.object(activity.urllib.request, "urlopen", return_value=response):
            activity.api("user/repos?visibility=all&page=1")
        saved = json.loads(next(self.run.glob("*.meta.json")).read_text())
        self.assertEqual(len([v for key, v in saved["header_items"] if key == "link"]), 2)
        cookies = [v for key, v in saved["header_items"] if key == "set-cookie"]
        self.assertEqual(cookies[0]["bytes"], len("PRIVATE_COOKIE_VALUE_123456789"))
        self.assertIn("sha256_prefix", cookies[0])
        self.assertNotIn("sha256_prefix", cookies[1])
        self.assertEqual(saved["masked_headers"], ["set-cookie", "set-cookie"])
        self.assertIn("PRIVATE_ORG", saved["headers"]["x-github-sso"])
        self.assertEqual(saved["headers"]["x-oauth-scopes"], "repo, workflow")
        self.assertIn("github-authentication-token-expiration", saved["headers"])
        for value in ("PRIVATE_ORG", "PRIVATE_COOKIE_VALUE_123456789", "SHORT", "repo, workflow"):
            self.assertNotIn(value, self.stdout.getvalue())
        self.assertNotIn("PRIVATE_COOKIE_VALUE_123456789", json.dumps(saved))

    def test_attempt_timing_exception_reason_and_token_mask_are_saved(self):
        token = "REQUEST_SECRET_CANARY"
        error = activity.urllib.error.URLError("TLS failure with " + token)
        with patch.dict(activity.os.environ, {"GH_TOKEN": token}), patch.object(activity.urllib.request, "urlopen", side_effect=[error, self.Response()]):
            activity.api("user")
        metadata = [json.loads(p.read_text()) for p in self.run.glob("*.meta.json")]
        failed = next(m for m in metadata if m["status"] is None)
        self.assertEqual(failed["attempt"], 1)
        self.assertGreater(failed["timeout"], 0)
        self.assertTrue(failed["started_at"].endswith("+00:00"))
        self.assertGreaterEqual(failed["elapsed_ms"], 0)
        self.assertEqual(failed["exception"]["type"], "URLError")
        self.assertIn("TLS failure", failed["exception"]["detail"])
        self.assertIn("omitted", failed["exception"]["detail"])
        self.assertNotIn(token, json.dumps(metadata) + self.stdout.getvalue())

    def test_tls_and_http_protocol_read_errors_are_preserved_and_retried(self):
        for error in (ssl.SSLError("synthetic TLS"), activity.http.client.LineTooLong("synthetic header"), OSError("synthetic socket")):
            class FailedRead(self.Response):
                def read(self): raise error
            with self.subTest(kind=type(error).__name__), patch.object(activity.urllib.request, "urlopen", side_effect=[FailedRead(), self.Response()]) as call:
                self.assertEqual(activity.api("user"), {"ok": True})
                self.assertEqual(call.call_count, 2)
        metadata = [json.loads(p.read_text()) for p in self.run.glob("*.meta.json")]
        self.assertTrue({"SSLError", "LineTooLong", "OSError"}.issubset(
            {m["exception"]["type"] for m in metadata if "exception" in m}))

    def test_public_diagnostic_logs_have_ids_and_limits_without_private_payload(self):
        response = self.Response(b'{"private_name":"PRIVATE_PAYLOAD_CANARY"}')
        response.headers = {"X-GitHub-Request-Id": "safe-request-id", "X-RateLimit-Remaining": "17", "X-RateLimit-Reset": "2000000000"}
        with patch.object(activity.urllib.request, "urlopen", return_value=response):
            activity.api("search/issues?per_page=1&q=author%3ALL0rddd%20created%3A2026-10-01..2026-10-26")
        line = next(line for line in self.stdout.getvalue().splitlines() if line.startswith("Activity request: "))
        public = json.loads(line.removeprefix("Activity request: "))
        self.assertEqual(public["kind"], "search/issues 2026-10-01..2026-10-26")
        self.assertEqual(public["request_id"], "safe-request-id")
        self.assertEqual(public["rate_remaining"], "17")
        self.assertEqual(public["rate_reset"], "2000000000")
        self.assertEqual(public["attempt"], 1)
        self.assertIn("elapsed_ms", public)
        self.assertNotIn("PRIVATE_PAYLOAD_CANARY", self.stdout.getvalue())

    def test_secondary_rate_limit_second_wait_is_120_seconds(self):
        errors = [self.error(429), self.error(429), self.Response()]
        with patch.object(activity.urllib.request, "urlopen", side_effect=errors):
            activity.api("user")
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [60, 120])

    def test_collect_shares_real_search_budget_across_all_six_months(self):
        user = {"login": "LL0rddd", "owned_private_repos": 1}
        repos = [{"owner": {"login": "LL0rddd"}, "private": True, "fork": False,
                  "created_at": "2026-01-01T00:00:00Z", "name": "PRIVATE_REPO_CANARY"}]
        responses = [self.Response(json.dumps(payload).encode()) for payload in (user, repos)]
        responses += [self.Response(json.dumps(self.complete).encode()) for _ in range(12)]
        budgets = []
        original = activity.CollectionBudget
        def tracked_budget():
            budget = original()
            budgets.append(budget)
            return budget
        with patch.dict(activity.os.environ, {"GH_TOKEN": "synthetic-test-value"}), patch.object(activity, "CollectionBudget", side_effect=tracked_budget), patch.object(activity.urllib.request, "urlopen", side_effect=responses) as call:
            snapshot = activity.collect(date(2026, 10, 26))
        activity.validate_snapshot(snapshot)
        self.assertEqual(call.call_count, 14)
        self.assertEqual(len(budgets), 1)
        self.assertEqual(budgets[0].searches, 12)
        self.assertEqual(len(list(self.run.glob("*.body"))), 14)
        self.assertNotIn("PRIVATE_REPO_CANARY", self.stdout.getvalue() + json.dumps(snapshot))

    def test_exhaustion_messages_keep_required_wait_and_request_counts(self):
        budget = activity.CollectionBudget()
        with self.assertRaisesRegex(activity.CollectionUnavailable, "required=900.0s.*remaining=.*wait_limit=120"):
            budget.wait(900, "GitHub HTTP 429")
        budget.searches = activity.MAX_SEARCH_REQUESTS
        with self.assertRaisesRegex(activity.CollectionUnavailable, "search/commits 2026-10-01..2026-10-26; used=90, limit=90"):
            budget.request("search/commits?q=author%3ALL0rddd%20author-date%3A2026-10-01..2026-10-26")


if __name__ == "__main__":
    unittest.main()
