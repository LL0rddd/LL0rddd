"""Generate aggregate public/private activity authored by LL0rddd across GitHub."""
import argparse
import calendar
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw
from build_profile_assets import font, version_readme_asset

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
RAW_RUN = ROOT / ".metrics-raw" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
MAX_ATTEMPTS = 3
MAX_SEARCH_REQUESTS = 90
COLLECTION_SECONDS = 420
MAX_RETRY_WAIT = 120


class CollectionUnavailable(RuntimeError):
    """Abort without replacing the last complete dashboard."""


class CollectionBudget:
    def __init__(self):
        self.deadline = time.monotonic() + COLLECTION_SECONDS
        self.searches = 0

    def timeout(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CollectionUnavailable("Collection time budget exhausted; previous assets were not replaced")
        return min(30, remaining)

    def wait(self, seconds, reason):
        remaining = self.deadline - time.monotonic()
        if seconds > MAX_RETRY_WAIT or seconds >= remaining:
            raise CollectionUnavailable(f"Required retry wait exceeds collection budget ({reason}; required={seconds:.1f}s, remaining={max(0, remaining):.1f}s, wait_limit={MAX_RETRY_WAIT}s); previous assets were not replaced")
        print(f"Activity retry: {reason}; waiting {seconds:.1f}s", flush=True)
        time.sleep(seconds)

    def request(self, endpoint):
        if endpoint.startswith("search/"):
            if self.searches >= MAX_SEARCH_REQUESTS:
                raise CollectionUnavailable(f"Search request budget exhausted ({request_label(endpoint)}; used={self.searches}, limit={MAX_SEARCH_REQUESTS}); previous assets were not replaced")
            self.searches += 1
        return self.timeout()


def header_items(headers):
    return list(headers.items()) if hasattr(headers, "items") else list(headers)


def masked_value(value):
    raw = value.encode("utf-8")
    return {"masked": True, "bytes": len(raw),
            **({"sha256_prefix": hashlib.sha256(raw).hexdigest()[:12]} if len(raw) >= 16 else {})}


def safe_detail(value):
    text = str(value)
    def marker(value):
        return "<omitted:" + json.dumps(masked_value(value), separators=(",", ":")) + ">"
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        token = os.environ.get(name)
        if token:
            text = text.replace(token, marker(token))
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})", lambda m: marker(m.group()), text)
    text = re.sub(r"(?i)(Bearer\s+)([A-Za-z0-9._~+/-]+)", lambda m: m[1] + marker(m[2]), text)
    return re.sub(r"(https?://)([^\s/@]+:[^\s/@]+)@", lambda m: m[1] + marker(m[2]) + "@", text)


def request_label(endpoint):
    route, _, query = endpoint.partition("?")
    if route in ("search/commits", "search/issues"):
        search = urllib.parse.parse_qs(query).get("q", [""])[0]
        window = re.search(r"\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}", search)
        return route + (" " + window.group() if window else "")
    return {"user": "account", "user/repos": "owned-repositories"}.get(route, "api")


def preserve_response(endpoint, raw, status, headers, category, *, diagnostic=None, error=None):
    """Keep each attempt byte-for-byte, including errors, without request credentials."""
    RAW_RUN.mkdir(parents=True, exist_ok=True, mode=0o700)
    RAW_RUN.parent.chmod(0o700)
    RAW_RUN.chmod(0o700)
    stem = hashlib.sha256(endpoint.encode()).hexdigest() + "-" + str(time.monotonic_ns())
    saved_headers, masked_headers = [], []
    sensitive = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key",
                 "x-auth-token", "x-access-token", "x-api-token", "authentication-info"}
    for key, value in header_items(headers):
        key = key.lower()
        if key in sensitive or safe_detail(value) != value:
            saved_headers.append([key, masked_value(value)])
            masked_headers.append(key)
        else:
            saved_headers.append([key, value])
    safe_headers = dict(saved_headers)  # Full ordered/repeated values remain in header_items.
    metadata = {"endpoint": endpoint, "status": status, "category": category,
                "headers": safe_headers, "header_items": saved_headers, "masked_headers": masked_headers,
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                "captured_at": datetime.now(timezone.utc).isoformat()}
    if diagnostic:
        metadata.update({key: value for key, value in diagnostic.items() if key != "started_clock"})
        metadata["elapsed_ms"] = round((time.monotonic() - diagnostic["started_clock"]) * 1000, 3)
    if error:
        reason = getattr(error, "reason", error)
        metadata["exception"] = {"type": type(error).__name__, "reason_type": type(reason).__name__,
                                 "detail": safe_detail(reason)}
    for suffix, content in ((".body", raw), (".meta.json", json.dumps(metadata).encode())):
        descriptor = os.open(RAW_RUN / (stem + suffix), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
    def public_header(name, pattern):
        value = safe_headers.get(name)
        return value if isinstance(value, str) and re.fullmatch(pattern, value) else None
    summary = {"kind": request_label(endpoint), "attempt": metadata.get("attempt"), "status": status,
               "request_id": public_header("x-github-request-id", r"[A-Za-z0-9:._-]{1,128}"),
               "rate_remaining": public_header("x-ratelimit-remaining", r"\d+"),
               "rate_reset": public_header("x-ratelimit-reset", r"\d+"),
               "bytes": len(raw), "sha256_prefix": metadata["sha256"][:12],
               "elapsed_ms": metadata.get("elapsed_ms"), "category": category,
               "exception_type": metadata.get("exception", {}).get("type"),
               "reason_type": metadata.get("exception", {}).get("reason_type")}
    print("Activity request: " + json.dumps(summary, separators=(",", ":")), flush=True)


def retry_delay(headers, attempt, limited):
    headers = {key.lower(): value for key, value in header_items(headers)}
    delay = 2 ** attempt
    retry_after = headers.get("retry-after")
    if retry_after is not None:
        try:
            delay = max(delay, float(retry_after))
        except ValueError:
            try:
                delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                delay = max(delay, 60 if limited else 0)
    elif limited:
        delay = max(delay, 60 * 2 ** (attempt - 1))
    if headers.get("x-ratelimit-remaining") == "0":
        try:
            delay = max(delay, float(headers["x-ratelimit-reset"]) - time.time() + 1)
        except (KeyError, ValueError):
            delay = max(delay, 60)
    return delay


def api(endpoint, *, budget=None):
    budget = budget or CollectionBudget()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LL0rddd-profile-aggregate-metrics",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request("https://api.github.com/" + endpoint, headers=headers)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        timeout = budget.request(endpoint)
        response_headers, status, raw = [], None, b""
        diagnostic = {"attempt": attempt, "timeout": timeout, "started_at": datetime.now(timezone.utc).isoformat(),
                      "started_clock": time.monotonic()}
        limited = False
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_headers = header_items(response.headers)
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as error:
            response_headers, status = header_items(error.headers), error.code
            transport_error = error
            partial_body = False
            try:
                raw = error.read()
            except http.client.IncompleteRead as partial:
                raw = partial.partial
                partial_body = True
                transport_error = partial
            except (OSError, http.client.HTTPException) as partial:
                partial_body = True
                transport_error = partial
            finally:
                error.close()
            lower_headers = {key.lower(): value for key, value in response_headers}
            limited = status == 429 or (status == 403 and (
                "retry-after" in lower_headers or lower_headers.get("x-ratelimit-remaining") == "0"
                or b"rate limit" in raw.lower() or b"abuse detection" in raw.lower()))
            reason = f"GitHub HTTP {status}"
            preserve_response(endpoint, raw, status, response_headers,
                              reason + ("; partial error body" if partial_body else ""),
                              diagnostic=diagnostic, error=transport_error)
            if not limited and status not in (408, 500, 502, 503, 504):
                raise CollectionUnavailable(reason + "; verify access/configuration; previous assets were not replaced") from None
        except (OSError, http.client.HTTPException) as error:
            raw = error.partial if isinstance(error, http.client.IncompleteRead) else b""
            reason = "temporary network/timeout or partial response"
            preserve_response(endpoint, raw, status, response_headers, reason, diagnostic=diagnostic, error=error)
        else:
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError) as error:
                reason = "invalid JSON response"
                preserve_response(endpoint, raw, status, response_headers, reason, diagnostic=diagnostic, error=error)
            else:
                preserve_response(endpoint, raw, status, response_headers, "response", diagnostic=diagnostic)
                return payload
        if attempt == MAX_ATTEMPTS:
            raise CollectionUnavailable(reason + "; retry attempts exhausted; previous assets were not replaced")
        budget.wait(retry_delay(response_headers, attempt, limited), reason)


def periods(today):
    current = today.year * 12 + today.month - 1
    result = []
    for offset in range(5, -1, -1):
        year, month = divmod(current - offset, 12)
        month += 1
        end = date(year, month, calendar.monthrange(year, month)[1])
        result.append((date(year, month, 1), min(end, today)))
    return result


def search_count(kind, query, *, budget=None):
    budget = budget or CollectionBudget()
    endpoint = "search/" + kind + "?per_page=1&q=" + urllib.parse.quote(query)
    window = re.search(r"\b(?:author-date|created):(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})\b", query)
    label = kind + (" " + window.group(0) if window else "")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        budget.timeout()
        payload = api(endpoint, budget=budget)
        if (not isinstance(payload, dict) or type(payload.get("total_count")) is not int
                or payload["total_count"] < 0 or type(payload.get("incomplete_results")) is not bool):
            raise CollectionUnavailable(f"Invalid search response ({label}); previous assets were not replaced")
        if not payload["incomplete_results"]:
            return payload["total_count"]
        if attempt < MAX_ATTEMPTS:
            budget.wait(2 ** attempt, f"incomplete search ({label}), attempt {attempt}/{MAX_ATTEMPTS}")
    if window:
        start, end = (date.fromisoformat(value) for value in window.groups())
        if start < end:
            middle = start + (end - start) // 2
            print(f"Activity recovery: splitting incomplete search ({label}) into non-overlapping dates", flush=True)
            def narrowed(first, last):
                return query[:window.start(1)] + first.isoformat() + ".." + last.isoformat() + query[window.end(2):]
            return (search_count(kind, narrowed(start, middle), budget=budget)
                    + search_count(kind, narrowed(middle + timedelta(days=1), end), budget=budget))
    raise CollectionUnavailable(f"Incomplete GitHub search ({label}) after retries/splitting; previous assets were not replaced")


def collect(today):
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        raise RuntimeError("Authentication is required; refusing a public-only fallback")
    budget = CollectionBudget()
    user = api("user", budget=budget)
    if user.get("login", "").lower() != "ll0rddd":
        raise RuntimeError("The credential must belong to LL0rddd")
    # Use the authenticated endpoint: /users/:login/repos excludes private repositories.
    # Retain raw responses locally, but never export repository names or identifiers.
    repos = []
    for page in range(1, 101):
        batch = api(f"user/repos?visibility=all&affiliation=owner&per_page=100&page={page}", budget=budget)
        repos.extend(r for r in batch if r["owner"]["login"].lower() == "ll0rddd")
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Repository pagination exceeded the safety limit")
    private_count = sum(r["private"] for r in repos)
    if not private_count:
        raise RuntimeError("No private repositories visible; verify credential access instead of publishing partial counts")
    expected_private = user.get("owned_private_repos")
    if isinstance(expected_private, int) and private_count != expected_private:
        raise RuntimeError("Incomplete private repository access; refusing partial counts")
    own_nonfork = [r for r in repos if not r["fork"]]
    months = []
    for start, end in periods(today):
        window = f"{start.isoformat()}..{end.isoformat()}"
        months.append({"month": start.strftime("%Y-%m"),
                       "commits": search_count("commits", f"author:LL0rddd author-date:{window}", budget=budget),
                       "pull_requests": search_count("issues", f"author:LL0rddd is:pr created:{window}", budget=budget),
                       "repositories": sum(r["created_at"][:10] <= end.isoformat() for r in own_nonfork)})
    return {"owner": "LL0rddd", "scope": "personal_public_and_private", "as_of": today.isoformat(), "months": months,
            "method": "Latest six calendar months including the current partial month through as_of (reference date in America/Sao_Paulo; GitHub date queries use UTC). Commits and PRs authored by LL0rddd across accessible public and private repositories, including other owners and organizations. Commits indexed by GitHub search on default branches and author date, not all local or unmerged commits; PRs created in the period, in any state. Repository counter remains currently owned non-fork repositories created by each period end, excluding collaborators' repositories. Coverage depends on credential access and GitHub indexing. Not a reconstruction of past visibility, deletions or transfers. Independent zero-based scales. No private names, code, messages or URLs are exported."}


def validate_snapshot(data):
    if set(data) != {"owner", "scope", "as_of", "months", "method"}:
        raise ValueError("Unexpected metadata: only aggregate snapshot fields are allowed")
    if data.get("owner") != "LL0rddd" or data.get("scope") != "personal_public_and_private" or len(data["months"]) != 6:
        raise ValueError("Expected six months of personal public/private aggregate metrics")
    for row in data["months"]:
        if set(row) != {"month", "commits", "pull_requests", "repositories"}:
            raise ValueError("Repository-level details are not allowed in the published snapshot")
        if any(type(row[k]) is not int or row[k] < 0 for k in ("commits", "pull_requests", "repositories")):
            raise ValueError("Metrics must be non-negative integers")
    expected = [start.strftime("%Y-%m") for start, _ in periods(date.fromisoformat(data["as_of"]))]
    if [row["month"] for row in data["months"]] != expected:
        raise ValueError("Snapshot must contain the latest six months including the current month")


def render(data):
    validate_snapshot(data)
    months = data["months"]
    labels = [MONTHS[int(row["month"][5:]) - 1] for row in months]
    series = [("Commits", "commits", "#22d3ee", "indexados em 6 meses"),
              ("Pull requests", "pull_requests", "#a78bfa", "criados em 6 meses"),
              ("Repositórios", "repositories", "#14b8a6", "próprios · sem forks")]
    period = f"{labels[0]}–{labels[-1]} {months[-1]['month'][:4]}"
    footer = "Mês atual parcial até " + date.fromisoformat(data["as_of"]).strftime("%d/%m/%Y") + " · escalas independentes"
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="580" height="205" viewBox="0 0 580 205" role="img">',
           "<title>Atividade agregada de Lucas Aguiar: públicos e privados</title>",
           f"<desc>{escape(data['method'])}</desc>",
           '<rect x=".5" y=".5" width="579" height="204" rx="10" fill="#0b1830" stroke="#233653"/>']
    def text(x, y, content, size=11, color="#b4c3d5"):
        svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-family="Segoe UI,Helvetica,Arial,sans-serif">{escape(str(content))}</text>')
    text(16, 24, "Atividade em código", 12, "#f1f5f9")
    text(360, 24, period + " · públicos + privados")
    bars = []
    for i, (label, key, color, unit) in enumerate(series):
        x = 16 + i * 190
        values = [row[key] for row in months]
        total = values[-1] if key == "repositories" else sum(values)
        text(x, 51, label)
        text(x, 77, f"{total:,}".replace(",", "."), 20, "#f1f5f9")
        ceiling = max(max(values) * 1.12, 1)
        svg.append(f'<path d="M{x} 127 H{x+168}" fill="none" stroke="#233653"/>')
        for j, value in enumerate(values):
            bx, bh = x + 6 + j * 27, value / ceiling * 35
            svg.append(f'<rect x="{bx}" y="{127-bh:.2f}" width="14" height="{bh:.2f}" rx="2" fill="{color}"><title>{labels[j]}: {value}</title></rect>')
            text(bx - 2, 143, labels[j])
            bars.append((bx, bh, color))
        text(x, 161, unit)
    svg.append('<path d="M16 174 H564" stroke="#233653"/>')
    text(16, 193, footer)
    svg.append("</svg>")
    (ROOT / "assets/activity.svg").write_text("\n".join(svg) + "\n", encoding="utf-8")
    # A non-looping animation; the static SVG remains available for reduced motion.
    frames = []
    for frame_index in range(15):
        image = Image.new("RGB", (1160, 410), "#0b1830")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1, 1, 1158, 408), radius=20, outline="#233653", width=2)
        def t(x, y, value, size=11, color="#b4c3d5"):
            draw.text((x * 2, (y - size) * 2), str(value), font=font(size * 2), fill=color)
        t(16, 24, "Atividade em código", 12, "#f1f5f9")
        t(360, 24, period + " · públicos + privados")
        progress = 1 - (1 - frame_index / 14) ** 3
        for i, (label, key, color, unit) in enumerate(series):
            x = 16 + i * 190
            values = [row[key] for row in months]
            total = values[-1] if key == "repositories" else sum(values)
            t(x, 51, label)
            t(x, 77, f"{total:,}".replace(",", "."), 20, "#f1f5f9")
            draw.line((x*2, 254, (x+168)*2, 254), fill="#233653", width=2)
            for j in range(6):
                bx, bh, bar_color = bars[i*6+j]
                if bh > 0 and progress > 0:
                    draw.rounded_rectangle((bx*2, (127-bh*progress)*2, (bx+14)*2, 254), radius=4, fill=bar_color)
                t(bx-2, 143, labels[j])
            t(x, 161, unit)
        draw.line((32, 348, 1128, 348), fill="#233653", width=2)
        t(16, 193, footer)
        frames.append(image)
    frames[0].save(ROOT / "assets/activity.gif", save_all=True, append_images=frames[1:],
                   duration=[60]*14+[10000], disposal=2, optimize=False)
    version_readme_asset("assets/activity.gif")
    version_readme_asset("assets/activity.svg")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-snapshot", action="store_true", help="Render without querying GitHub")
    args = parser.parse_args(argv)
    snapshot = ROOT / "assets/activity.json"
    try:
        data = json.loads(snapshot.read_text()) if args.from_snapshot else collect(datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    except CollectionUnavailable as error:
        parser.exit(1, "Activity update deferred: " + str(error) + "\n")
    render(data)
    if not args.from_snapshot:
        snapshot.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Aggregate activity generated:", data["as_of"], "(public + private; no repository details)")


if __name__ == "__main__":
    main()
