"""Generate a six-completed-month snapshot using public GitHub activity only."""
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

from PIL import Image, ImageDraw
from build_profile_assets import font

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
RAW_RUN = ROOT / ".metrics-raw" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def api(endpoint):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LL0rddd-profile-public-metrics",
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
    for offset in range(6, 0, -1):
        year, month = divmod(current - offset, 12)
        month += 1
        result.append((date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])))
    return result


def search_count(kind, query):
    payload = api("search/" + kind + "?per_page=1&q=" + urllib.parse.quote(query))
    if payload.get("incomplete_results") or not isinstance(payload.get("total_count"), int):
        raise RuntimeError("Incomplete public GitHub search; previous assets were not replaced")
    return payload["total_count"]


def collect(today):
    # /users/:login/repos lists public repositories, even with an authenticated request.
    repos = []
    for page in range(1, 101):
        batch = api(f"users/LL0rddd/repos?type=owner&per_page=100&page={page}")
        repos.extend(r for r in batch if not r["private"] and not r["fork"]
                     and r["owner"]["login"].lower() == "ll0rddd")
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Repository pagination exceeded the safety limit")
    months = []
    for start, end in periods(today):
        window = f"{start.isoformat()}..{end.isoformat()}"
        months.append({"month": start.strftime("%Y-%m"),
                       "commits": search_count("commits", f"author:LL0rddd is:public author-date:{window}"),
                       "pull_requests": search_count("issues", f"author:LL0rddd is:public is:pr created:{window}"),
                       "repositories": sum(r["created_at"][:10] <= end.isoformat() for r in repos)})
    return {"owner": "LL0rddd", "scope": "public_only", "as_of": today.isoformat(), "months": months,
            "method": "Commits indexed by GitHub search and author date; public PRs created; currently public owned non-fork repositories created by each month end. Not a reconstruction of past repository visibility. Independent zero-based chart scales. Private activity is excluded."}


def render(data):
    months = data["months"]
    if data.get("scope") != "public_only" or len(months) != 6:
        raise ValueError("Expected six months of public metrics")
    for row in months:
        if any(type(row[k]) is not int or row[k] < 0 for k in ("commits", "pull_requests", "repositories")):
            raise ValueError("Metrics must be non-negative integers")
    labels = [MONTHS[int(row["month"][5:]) - 1] for row in months]
    series = [("Commits", "commits", "#22d3ee", "indexados em 6 meses"),
              ("Pull requests", "pull_requests", "#a78bfa", "criados em 6 meses"),
              ("Repositórios", "repositories", "#14b8a6", "públicos próprios · sem forks")]
    period = f"{labels[0]}–{labels[-1]} {months[-1]['month'][:4]}"
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="580" height="205" viewBox="0 0 580 205" role="img">',
           "<title>Atividade pública de Lucas Aguiar</title>",
           f"<desc>{escape(data['method'])}</desc>",
           '<rect x=".5" y=".5" width="579" height="204" rx="10" fill="#0b1830" stroke="#233653"/>']
    def text(x, y, content, size=11, color="#b4c3d5"):
        svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-family="Segoe UI,Helvetica,Arial,sans-serif">{escape(str(content))}</text>')
    text(16, 24, "Atividade em código", 12, "#f1f5f9")
    text(390, 24, period + " · público")
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
    text(16, 193, "Somente dados públicos · escalas independentes · " + data["as_of"])
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
        t(390, 24, period + " · público")
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
        t(16, 193, "Somente dados públicos · escalas independentes · " + data["as_of"])
        frames.append(image)
    frames[0].save(ROOT / "assets/activity.gif", save_all=True, append_images=frames[1:],
                   duration=[60]*14+[10000], disposal=2, optimize=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-snapshot", action="store_true", help="Render without querying GitHub")
    args = parser.parse_args()
    snapshot = ROOT / "assets/activity.json"
    data = json.loads(snapshot.read_text()) if args.from_snapshot else collect(datetime.now(timezone.utc).date())
    render(data)
    if not args.from_snapshot:
        snapshot.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Public activity generated:", data["as_of"], "(private activity excluded)")
