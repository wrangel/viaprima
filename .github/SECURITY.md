# Security Policy

Grundversicherungsrechner is a calculation tool for Swiss basic health
insurance, maintained by one person. This policy exists so that a genuine
security finding reaches me privately instead of arriving as a public issue.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting:

**[Report a vulnerability](https://github.com/wrangel/viaprima/security/advisories/new)**

That opens a private advisory visible only to me, so the problem can be fixed
before it is described anywhere public.

If you would rather not use GitHub, email
`contact@abstractaltitudes.anonaddy.com` with "security" in the
subject.

## What this application holds

Worth knowing before you look for a data breach: there is very little to
breach. The app has no accounts, no login, no database and no server-side
storage of anything a visitor types. Nothing is sent to third parties; usage
statistics are switched off.

What you enter — postcode, year of birth, accident cover, expected healthcare
costs, tariff models, today's insurer, model and deductible — is kept in the
browser's own `localStorage`, so that reloading the page does not throw it
away. That store never leaves your machine: it is not a cookie, so it is not
attached to requests and never reaches the server or its logs. "Eingaben
löschen" at the foot of the page deletes it, and a form you have not touched is
not stored at all.

The values themselves do reach the server, because that is where Streamlit
calculates: each change travels over the page's websocket, is computed with,
and is held only in that browser session's memory until the tab closes. The
app writes none of it to disk or to a log, and the page says so in those words.

A cookie was considered and rejected for exactly this reason: it would travel
with every request and end up in the reverse proxy's access log. Query
parameters were rejected too — they would sit in the URL, in browser history,
in the proxy log, and would leak through the `Referer` header on any outbound
link.

The only data the server holds is the BAG's public premium file, cached on
disk. If any of this changes, this section changes with it.

## What helps

- The URL or the file and line, and what an attacker could actually achieve
- Steps to reproduce, ideally the smallest case that shows it

A wrong number is a correctness bug, not a vulnerability — those are very
welcome, but as a normal issue or by email rather than a private advisory.

## What to expect

This is a side project, not a staffed product. I will acknowledge reports as
soon as I reasonably can and fix what is genuinely exploitable, but I am not
promising a response deadline I cannot keep. There is no bug bounty.

Reports that are clearly automated scanner output with no demonstrated impact
will usually be closed without a detailed reply.

## Scope

In scope: this repository's source, and the deployed instance at
<https://viaprima.ch>.

Out of scope: the third-party services this depends on — the BAG's data
delivery via opendata.swiss, Docker Hub, Streamlit itself, and Let's Encrypt —
which should be reported to those vendors directly.

Please do not run automated scanners or load tests. It runs on a small home
server; a scan is indistinguishable from an outage.

## Versions

There are no released versions to support. The site runs whatever is currently
on `main`, deployed as a Docker image, so fixes apply to the live site rather
than to a version range.
