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

import re
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

# Allowed, but Cloudflare may not verify them, so rule 1 must name them as
# exceptions. The big search engines are deliberately not here: they are
# verified, and exempting their names would let anyone in who claims them.
UNVERIFIED_ALLOWED = [
    "Bravebot", "archive.org_bot", "Arquivo-web-crawler",
    "Twitterbot", "LinkedInBot", "Slackbot", "Discordbot", "TelegramBot",
]

# Google's helpers that must never be caught by name: Search Console's live
# test, Merchant Center, Ads checks, the AdSense crawler, feed fetching.
GOOGLE_HELPERS = [
    "Google-InspectionTool", "Storebot-Google", "AdsBot-Google",
    "Mediapartners-Google", "FeedFetcher-Google",
]

README = Path(__file__).resolve().parent / "README.md"

BLOCKED = [
    "Google-Extended", "Applebot-Extended", "GPTBot", "ClaudeBot", "anthropic-ai",
    "CCBot", "Bytespider", "meta-externalagent", "DeepSeekBot", "GrokBot",
]


def cloudflare_rules() -> tuple[str, str]:
    """The two custom-rule expressions, as documented in the README.

    The README is where the rules are pasted from, so it is what gets checked.
    """
    text = README.read_text(encoding="utf-8")
    blocks = {}
    for name in ("Rule 1", "Rule 2"):
        start = text.find(f"**{name}")
        fence = text.find("```", start)
        end = text.find("```", fence + 3)
        blocks[name] = text[fence + 3:end] if start != -1 and fence != -1 else ""
    return blocks["Rule 1"], blocks["Rule 2"]


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

    rule1, rule2 = cloudflare_rules()
    exempted = re.findall(r'not \((.*?)\)\)', rule1, re.S)
    exempted = re.findall(r'contains "([^"]+)"', exempted[0]) if exempted else []
    for agent in UNVERIFIED_ALLOWED:
        if not any(token in agent.lower() for token in exempted):
            failures.append(f"rule 1 does not exempt {agent}")
    for token in exempted:
        if any(token in name.lower() for name in ("googlebot", "bingbot", "applebot", "duckduckbot")):
            failures.append(f"rule 1 exempts the name of a verified search engine: {token}")
    blocked_by_name = re.findall(r'contains "([^"]+)"', rule2)
    if not blocked_by_name:
        failures.append("rule 2 not found in the README")
    for agent in ALLOWED + GOOGLE_HELPERS:
        for token in blocked_by_name:
            if token in agent.lower():
                failures.append(f"rule 2 token {token!r} would block {agent}")

    for failure in failures:
        print("FAIL", failure)
    checked = (len(ALLOWED) * 2 + len(BLOCKED) + 2 + len(UNVERIFIED_ALLOWED) + 1
               + len(ALLOWED) + len(GOOGLE_HELPERS))
    print(f"{checked - len(failures)}/{checked} robots.txt checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
