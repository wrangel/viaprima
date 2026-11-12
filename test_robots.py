"""Check seo/robots.txt against the crawler policy.

The policy (README, "Crawlers"): search engines and archives may crawl, the six
AI answer bots may read and cite, everything that trains AI is turned away.
The risk this guards against is a token added to the block group that also
matches an allowed crawler: robots.txt matching is by substring, and blocking
Googlebot by accident is exactly the failure that cost abstractaltitudes.com its
indexing for a week.

Uses the standard library's parser - no network, no pytest:

    python test_robots.py
"""

import sys
from pathlib import Path
from urllib.robotparser import RobotFileParser

ROBOTS = Path(__file__).resolve().parent / "seo" / "robots.txt"
SITE = "https://viaprima.ch/"

ALLOWED = [
    # search engines
    "Googlebot", "Googlebot-Image", "bingbot", "Applebot", "DuckDuckBot", "Bravebot",
    # archives
    "archive.org_bot", "Arquivo-web-crawler",
    # AI answer bots: may read and cite, not train
    "OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "Perplexity-User",
    "Claude-SearchBot", "Claude-User",
    # link previews
    "facebookexternalhit", "Twitterbot", "LinkedInBot", "Slackbot", "WhatsApp",
]

BLOCKED = [
    "Google-Extended", "Applebot-Extended", "GPTBot", "ClaudeBot", "anthropic-ai",
    "CCBot", "Bytespider", "meta-externalagent", "DeepSeekBot", "GrokBot",
]


def main() -> int:
    text = ROBOTS.read_text(encoding="utf-8")
    parser = RobotFileParser()
    parser.parse(text.splitlines())

    failures = []
    for agent in ALLOWED:
        if not parser.can_fetch(agent, SITE):
            failures.append(f"{agent} is blocked but should be allowed")
        if parser.can_fetch(agent, SITE + "_stcore/health"):
            failures.append(f"{agent} may crawl /_stcore/, which is not a page")
    for agent in BLOCKED:
        if parser.can_fetch(agent, SITE):
            failures.append(f"{agent} is allowed but should be blocked")

    if "Content-Signal: search=yes, ai-input=yes, ai-train=no" not in text:
        failures.append("the Content-Signal line is missing or changed")
    if "Sitemap: https://viaprima.ch/sitemap.xml" not in text:
        failures.append("the Sitemap line is missing")

    for failure in failures:
        print("FAIL", failure)
    checked = len(ALLOWED) * 2 + len(BLOCKED) + 2
    print(f"{checked - len(failures)}/{checked} robots.txt checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
