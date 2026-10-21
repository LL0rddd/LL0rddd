"""Build the approved profile badges from original logos and Lucide icons.

Network is used only with --download. No credentials are needed for brand assets.
"""
import argparse
import base64
import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
LUCIDE = "https://cdn.jsdelivr.net/npm/lucide-static@0.468.0"
ICONS = ("settings", "flask-conical", "plug", "shield-check", "puzzle",
         "link", "route", "layers", "list-checks", "bot")
SOURCES = {
    "python.png": "https://cdn.jsdelivr.net/gh/python/cpython@main/Lib/profiling/sampling/_assets/python-logo-only.png",
    "node.svg": "https://cdn.jsdelivr.net/gh/nodejs/nodejs.org@main/apps/site/public/static/logos/nodejsHex.svg",
    "typescript.svg": "https://cdn.jsdelivr.net/gh/microsoft/TypeScript-Website@04569788cf46f97e2f16356639bc9635c88c0a61/packages/typescriptlang-org/static/branding/ts-logo-128.svg",
    "react.svg": "https://cdn.jsdelivr.net/gh/reactjs/react.dev@main/public/images/brand/logo_dark.svg",
    "electron.svg": "https://cdn.jsdelivr.net/gh/electron/website@main/static/assets/img/logo.svg",
    "streamlit.svg": "https://cdn.jsdelivr.net/gh/streamlit/streamlit@develop/frontend/lib/src/assets/img/streamlit-logo/streamlit-mark-color.svg",
    "n8n.svg": "https://cdn.jsdelivr.net/gh/n8n-io/n8n@master/packages/frontend/@n8n/design-system/src/components/N8nLogo/logo-icon.svg",
    "playwright.svg": "https://cdn.jsdelivr.net/gh/microsoft/playwright@main/packages/dashboard/public/playwright-logo.svg",
    "claudecode.png": "https://cdn.jsdelivr.net/gh/lobehub/lobe-icons@master/packages/static-png/dark/claudecode-color.png",
    "codex.png": "https://cdn.jsdelivr.net/gh/lobehub/lobe-icons@master/packages/static-png/light/codex.png",
    "antigravity.png": "https://cdn.jsdelivr.net/gh/lobehub/lobe-icons@master/packages/static-png/dark/antigravity-color.png",
}
TONES = {"blue": ("#67d7ff", "#193346"),
         "purple": ("#c4b5fd", "#302943"),
         "green": ("#5eead4", "#193b39")}


def font(size, bold=False):
    candidates = ["/System/Library/Fonts/Helvetica.ttc",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans" + ("-Bold" if bold else "") + ".ttf"]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size, index=1 if bold and candidate.endswith(".ttc") else 0)
    raise RuntimeError("Install Helvetica or DejaVu Sans to build profile assets")


def svg(width, height, label):
    root = ET.Element(f"{{{NS}}}svg", {"width": str(width), "height": str(height),
                       "viewBox": f"0 0 {width} {height}", "role": "img"})
    ET.SubElement(root, "title").text = label
    return root


def add(root, tag, **attrs):
    return ET.SubElement(root, tag, {k.replace("_", "-"): str(v) for k, v in attrs.items()})


def save(root, name):
    destination = ASSETS / "badges" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")


def version_readme_asset(relative):
    """Change only the target image URL when its content changes, avoiding stale caches."""
    digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()[:12]
    readme = ROOT / "README.md"
    original = readme.read_text(encoding="utf-8")
    pattern = re.compile(r'((?:src|srcset)="\./' + re.escape(relative) + r')(?:\?v=[^"]*)?(\")')
    updated = pattern.sub(lambda match: match[1] + "?v=" + digest + match[2], original)
    if updated != original:
        readme.write_text(updated, encoding="utf-8")


def icon(root, name, x, y, size, color):
    source = ET.parse(ASSETS / "icons" / (name + ".svg")).getroot()
    source.attrib.update(x=str(x), y=str(y), width=str(size), height=str(size),
                         stroke=color, fill="none")
    root.append(source)


def badge(name, label, icon_name, tone, header=False):
    accent, tint = TONES[tone]
    height, size, left = (36, 20, 36) if header else (32, 12, 34)
    label_width = int(font(size, True).getlength(label)) + 26
    root = svg(left + label_width, height, label)
    add(root, "rect", width=left + label_width, height=height, fill="#17202d")
    add(root, "rect", x=left, width=label_width, height=height,
        fill=tint if header else {"blue": "#0ea5e9", "purple": "#8b5cf6", "green": "#14b8a6"}[tone])
    icon(root, icon_name, (left - 18) / 2, (height - 18) / 2, 18, accent)
    text = add(root, "text", x=left + 13, y=height / 2 + size * .35,
               fill="#cdd5df" if header else "#ffffff", font_size=size,
               font_weight="600" if header else "700",
               font_family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif")
    text.text = label
    save(root, name + ".svg")


def technology(name, label, filename, background, foreground="#ffffff"):
    left, height = 25, 28
    width = left + int(font(11).getlength(label)) + 12
    if name == "antigravity":
        # Approved HTML preview: 134.789 CSS px including the original 8 px right padding.
        width = 135
    root = svg(width, height, label)
    add(root, "rect", width=width, height=height, fill=background)
    add(root, "rect", x=3, y=3, width=22, height=22,
        fill="#ffffff" if name in ("codex", "n8n") else "#17202d")
    source = ASSETS / "brands" / filename
    if source.suffix == ".svg":
        logo = ET.parse(source).getroot()
        logo.attrib.update(x="6", y="6", width="16", height="16")
        root.append(logo)
    else:
        add(root, "image", x=6, y=6, width=16, height=16,
            href="data:image/png;base64," + base64.b64encode(source.read_bytes()).decode())
    text = add(root, "text", x=left + 6, y=18, fill=foreground, font_size=11,
               font_family="Segoe UI,system-ui,sans-serif" if name == "antigravity" else "Segoe UI,Helvetica,Arial,sans-serif")
    text.text = label
    if name == "antigravity":
        definitions = add(root, "defs")
        gradient = add(definitions, "linearGradient", id="antigravity-colors", x1="0%", y1="0%", x2="100%", y2="0%")
        for offset, color in (("0%", "#00b95c"), ("40%", "#3186ff"), ("72%", "#ffe432"), ("100%", "#fc413d")):
            add(gradient, "stop", offset=offset, stop_color=color)
        add(root, "rect", x=0, y=26, width=width, height=2, fill="url(#antigravity-colors)")
    save(root, name + ".svg")


def download():
    sources = dict(SOURCES)
    sources.update({"../icons/" + name + ".svg": LUCIDE + "/icons/" + name + ".svg" for name in ICONS})
    sources["../icons/LUCIDE-LICENSE"] = LUCIDE + "/LICENSE"
    sources["LOBE-LICENSE"] = "https://cdn.jsdelivr.net/gh/lobehub/lobe-icons@master/LICENSE"
    for name, url in sources.items():
        # Download only the fixed public list. Never accept arbitrary destinations or credentials.
        target = ASSETS / "brands" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("Asset exceeds 1 MB: " + name)
        if name.endswith(".svg"):
            doc = ET.fromstring(data)
            for node in doc.iter():
                if node.tag.rsplit("}", 1)[-1] in ("script", "foreignObject"):
                    raise ValueError("Active content in asset: " + name)
                if any(k.startswith("on") or (k.endswith("href") and not v.startswith("#")) for k, v in node.attrib.items()):
                    raise ValueError("External references in asset: " + name)
        target.write_bytes(data)
    (ASSETS / "sources.json").write_text(json.dumps({
        "brands": SOURCES, "lucide": LUCIDE,
        "note": "Technology logos are from vendor repositories. AI icons are Lobe Icons reproductions, not official vendor kits. Badges and headings are custom compositions, not official lockups. Logos remain trademarks of their owners. Sources were retrieved on 2026-10-21."
    }, indent=2) + "\n", encoding="utf-8")


def build():
    for name, label, glyph, tone in (
        ("automation", "AUTOMAÇÃO", "settings", "blue"),
        ("quality", "QUALIDADE", "flask-conical", "purple"),
        ("integrations", "INTEGRAÇÕES", "plug", "green")):
        badge(name, label, glyph, tone)
    for name, label, glyph, tone in (
        ("build-automation", "Automação", "settings", "blue"),
        ("build-quality", "Qualidade", "flask-conical", "purple"),
        ("build-integrations", "Integrações", "plug", "green"),
        ("build-security", "Segurança operacional", "shield-check", "green"),
        ("prompt-forge", "Prompt Forge", "puzzle", "purple"),
        ("requests-automations", "Requests Automations", "settings", "blue"),
        ("jira-issue-analyzer", "Jira Issue Analyzer", "link", "green"),
        ("clean-git-commit", "Clean Git Commit", "shield-check", "green")):
        badge(name, label, glyph, tone, header=True)
    for name, glyph, tone in (("traceability", "route", "blue"), ("security", "shield-check", "green"),
                              ("architecture", "layers", "blue"), ("verification", "list-checks", "purple"),
                              ("supervision", "bot", "purple")):
        root = svg(30, 30, name)
        add(root, "rect", width=30, height=30, fill="#17202d")
        icon(root, glyph, 6.5, 6.5, 17, TONES[tone][0])
        save(root, name + ".svg")
    for args in (
        ("python", "Python", "python.png", "#3776ab"),
        ("node", "Node.js", "node.svg", "#339933"),
        ("typescript", "TypeScript", "typescript.svg", "#3178c6"),
        ("react", "React", "react.svg", "#61dafb", "#0b1220"),
        ("electron", "Electron", "electron.svg", "#47848f"),
        ("streamlit", "Streamlit", "streamlit.svg", "#ff4b4b"),
        ("n8n", "n8n", "n8n.svg", "#ea4b71"),
        ("playwright", "Playwright", "playwright.svg", "#2ead33"),
        ("claude-code", "Claude Code", "claudecode.png", "#d97757", "#141413"),
        ("codex", "Codex", "codex.png", "#ffffff", "#000000"),
        ("antigravity", "Antigravity/Gemini", "antigravity.png", "#17202d", "#f1f5f9")):
        technology(*args)
    version_readme_asset("assets/badges/antigravity.svg")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        download()
    build()
    print("Profile assets built successfully")
