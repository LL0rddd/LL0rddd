"""Generate aggregate public/private activity for LL0rddd-owned repositories."""
import argparse
import calendar
import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw
from build_profile_assets import font

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
RAW_RUN = ROOT / ".metrics-raw" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def api(endpoint):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LL0rddd-profile-aggregate-metrics",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request("https://api.github.com/" + endpoint, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    # Response bytes are preserved locally; authorization headers are never recorded.
    RAW_RUN.mkdir(parents=True, exist_ok=True, mode=0o700)
    RAW_RUN.parent.chmod(0o700)
    target = RAW_RUN / (hashlib.sha256(endpoint.encode()).hexdigest() + ".json")
    target.touch(mode=0o600, exist_ok=False)
    target.write_bytes(raw)
    return json.loads(raw)


def periods(today):
    current = today.year * 12 + today.month - 1
    result = []
    for offset in range(5, -1, -1):
        year, month = divmod(current - offset, 12)
        month += 1
        end = date(year, month, calendar.monthrange(year, month)[1])
        result.append((date(year, month, 1), min(end, today)))
    return result


def search_count(kind, query):
    payload = api("search/" + kind + "?per_page=1&q=" + urllib.parse.quote(query))
    if payload.get("incomplete_results") or not isinstance(payload.get("total_count"), int):
        raise RuntimeError("Incomplete GitHub search; previous assets were not replaced")
    return payload["total_count"]


def collect(today):
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        raise RuntimeError("Authentication is required; refusing a public-only fallback")
    user = api("user")
    if user.get("login", "").lower() != "ll0rddd":
        raise RuntimeError("The credential must belong to LL0rddd")
    # Use the authenticated endpoint: /users/:login/repos excludes private repositories.
    # Retain raw responses locally, but never export repository names or identifiers.
    repos = []
    for page in range(1, 101):
        batch = api(f"user/repos?visibility=all&affiliation=owner&per_page=100&page={page}")
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
                       "commits": search_count("commits", f"author:LL0rddd user:LL0rddd author-date:{window}"),
                       "pull_requests": search_count("issues", f"author:LL0rddd user:LL0rddd is:pr created:{window}"),
                       "repositories": sum(r["created_at"][:10] <= end.isoformat() for r in own_nonfork)})
    return {"owner": "LL0rddd", "scope": "personal_public_and_private", "as_of": today.isoformat(), "months": months,
            "method": "Latest six calendar months including the current partial month through as_of (reference date in America/Sao_Paulo; GitHub date queries use UTC). Aggregate counts from LL0rddd-owned public and private repositories accessible to the credential. Commits indexed by GitHub search and author date; PRs created by LL0rddd; currently owned non-fork repositories created by each period end. Other owners and organizations are excluded. Not a reconstruction of past visibility, deletions or transfers. Independent zero-based scales. No private names, code, messages or URLs are exported."}


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-snapshot", action="store_true", help="Render without querying GitHub")
    args = parser.parse_args()
    snapshot = ROOT / "assets/activity.json"
    data = json.loads(snapshot.read_text()) if args.from_snapshot else collect(datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    render(data)
    if not args.from_snapshot:
        snapshot.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Aggregate activity generated:", data["as_of"], "(public + private; no repository details)")
