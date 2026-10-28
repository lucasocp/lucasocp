#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape

USERNAME = os.getenv("GITHUB_USERNAME", "lucasocp")
TOKEN = os.getenv("GITHUB_TOKEN")
OUT = os.getenv("OUTPUT_FILE", "github-stats.svg")

if not TOKEN:
    raise SystemExit("GITHUB_TOKEN is required")

API = "https://api.github.com/graphql"

def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "lucasocp-github-profile-stats",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]

def fetch_public_repos():
    query = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositories(
          first: 100
          after: $cursor
          ownerAffiliations: OWNER
          privacy: PUBLIC
          orderBy: {field: UPDATED_AT, direction: DESC}
        ) {
          pageInfo { hasNextPage endCursor }
          nodes {
            name
            isFork
            languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
              edges {
                size
                node { name color }
              }
            }
          }
        }
      }
    }
    """
    repos = []
    cursor = None
    while True:
        data = graphql(query, {"login": USERNAME, "cursor": cursor})
        connection = data["user"]["repositories"]
        repos.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["pageInfo"]["endCursor"]
    return repos

def fetch_contributions():
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar { totalContributions }
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          totalRepositoryContributions
          totalRepositoriesWithContributedCommits
        }
      }
    }
    """
    data = graphql(
        query,
        {
            "login": USERNAME,
            "from": start.isoformat(),
            "to": end.isoformat(),
        },
    )
    return data["user"]["contributionsCollection"]

def pct(value, total):
    return (value / total * 100) if total else 0

def short_number(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)

def svg_text(x, y, text, size=14, weight=400, fill="#E6EDF3", anchor="start"):
    return (
        f'<text x="{x}" y="{y}" font-family="Inter,Segoe UI,Arial,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">'
        f'{escape(str(text))}</text>'
    )

def build_svg(stats, languages):
    width, height = 920, 520
    bg, card, text, muted, accent, border = "#0D1117", "#161B22", "#E6EDF3", "#8B949E", "#58A6FF", "#30363D"

    metrics = [
        ("Contribuições", stats["totalContributions"]),
        ("Commits", stats["commits"]),
        ("Pull Requests", stats["prs"]),
        ("Issues", stats["issues"]),
        ("PR Reviews", stats["reviews"]),
    ]

    top_langs = languages[:6]
    total_lang_bytes = sum(v["bytes"] for v in top_langs) or 1

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="GitHub statistics for {escape(USERNAME)}">',
        f'<rect width="{width}" height="{height}" rx="14" fill="{bg}"/>',
        f'<rect x="18" y="18" width="884" height="484" rx="12" fill="{card}" stroke="{border}"/>',
        svg_text(42, 62, "GitHub Activity", 22, 700),
        svg_text(42, 86, "Últimos 12 meses", 13, 400, muted),
    ]

    # Metric cards
    x_positions = [42, 215, 388, 561, 734]
    for x, (label, value) in zip(x_positions, metrics):
        parts += [
            f'<rect x="{x}" y="110" width="150" height="96" rx="10" fill="{bg}" stroke="{border}"/>',
            svg_text(x + 14, 142, label, 12, 500, muted),
            svg_text(x + 14, 179, short_number(value), 26, 700, text),
        ]

    parts += [
        svg_text(42, 246, "Linguagens por volume de código", 17, 650),
        svg_text(42, 268, "Baseado nos bytes reportados pelo GitHub para seus repositórios públicos.", 12, 400, muted),
    ]

    y = 302
    bar_x, bar_w, bar_h = 42, 836, 12
    cursor = bar_x
    for lang in top_langs:
        w = bar_w * (lang["bytes"] / total_lang_bytes)
        if w < 2:
            continue
        color = lang["color"] or accent
        parts.append(
            f'<rect x="{cursor:.2f}" y="{y}" width="{w:.2f}" height="{bar_h}" fill="{escape(color)}"/>'
        )
        cursor += w

    y += 42
    for i, lang in enumerate(top_langs):
        col = i % 2
        row = i // 2
        x = 42 + col * 418
        yy = y + row * 38
        color = lang["color"] or accent
        percentage = pct(lang["bytes"], sum(v["bytes"] for v in languages))
        parts += [
            f'<circle cx="{x + 5}" cy="{yy - 5}" r="5" fill="{escape(color)}"/>',
            svg_text(x + 18, yy, lang["name"], 13, 600),
            svg_text(x + 385, yy, f"{percentage:.1f}%", 13, 600, text, "end"),
        ]

    parts += [
        svg_text(42, 487, "github.com/lucasocp", 12, 500, muted),
        "</svg>",
    ]
    return "\n".join(parts)

def main():
    repos = fetch_public_repos()
    contributions = fetch_contributions()

    lang_totals = defaultdict(lambda: {"bytes": 0, "color": None})
    for repo in repos:
        if repo.get("isFork"):
            continue
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            lang_totals[name]["bytes"] += edge["size"]
            if not lang_totals[name]["color"]:
                lang_totals[name]["color"] = edge["node"].get("color")

    languages = sorted(lang_totals.values(), key=lambda x: x["bytes"], reverse=True)
    for name, data in lang_totals.items():
        data["name"] = name
    languages = sorted(lang_totals.values(), key=lambda x: x["bytes"], reverse=True)

    stats = {
        "totalContributions": contributions["contributionCalendar"]["totalContributions"],
        "commits": contributions["totalCommitContributions"],
        "prs": contributions["totalPullRequestContributions"],
        "issues": contributions["totalIssueContributions"],
        "reviews": contributions["totalPullRequestReviewContributions"],
    }

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build_svg(stats, languages))

if __name__ == "__main__":
    main()
