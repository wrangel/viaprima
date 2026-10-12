# Grundversicherung: finding the cheapest premium

A small tool for Swiss basic health insurance (*Grundversicherung*). From the official
premium data of the Federal Office of Public Health (BAG) it computes, for every
selectable deductible, the total cost of a year — across the whole range of possible
healthcare costs — and shows which deductible is cheapest when. Which ones those are, and
how many, follows from the data; nothing is assumed.

It answers three questions:

1. **Which insurer offers the cheapest premium per deductible?** — for a given canton,
   premium region and age class.
2. **From what annual healthcare costs does the lowest deductible pay off?** — the
   *tipping point*, taking into account the environmental levy refund that is deducted
   from the premium per person and month.
3. **What does the whole household cost, with which insurer?** — adults, young adults and
   children together, including sibling discounts and the family cap on cost sharing.

The data comes straight from the BAG's official premium comparison, obtained via
[opendata.swiss](https://opendata.swiss/en/dataset/health-insurance-premiums), and is
fetched fresh on every run.

### A note on language

Identifiers, comments and documentation are English. Two things are deliberately not:

- **DataFrame column labels** (`Prämie`, `Altersklasse`, `Geschäftsjahr`) are the names
  the BAG ships in its file. Translating them would add a mapping layer that breaks on
  every schema change, for no gain.
- **Swiss legal and tariff codes** (`AKL-ERW`, `FRA-300`, `PR-REG CH1`, `K4`) are official
  identifiers. They are data, not words.

The user interface is still German. A translation layer covering the four Swiss national
languages plus English is planned and is deliberately being left until the content has
settled.

## How the calculation works

For every deductible, the effective total cost of a year is determined:

```
annual cost = 12 × (monthly premium − environmental levy refund)
            + min(healthcare costs, deductible)        ← deductible share
            + min(10 % of the costs above the deductible,
                  cap)                                  ← coinsurance
```

The coinsurance cap is CHF 700 per year for adults and young adults, CHF 350 for children
(Art. 103 KVV).

Then, for each cost amount, the cheapest deductible is determined. The tipping point is
the lowest amount from which the **lowest** deductible wins.

## Project layout

The modules form a straight line; nothing reaches backwards.

```
constants.py        data sources, legal constants, shared vocabularies (no imports)
theme.py            page config and CSS (no imports)
  calculation.py    the whole domain model: cost formula, tipping point,
                    sibling-discount schemes. No user interface.
    common.py       loading, formatting, location lookup, age class
      view_person.py / view_household.py     the two views
        app.py      Streamlit entry point: sequence only

main.py                 the same calculation from the command line
check_data_sources.py   monitoring; writes data/data_state.json and the history
refresh_insurers.py     regenerates data/insurers.json from the BAG register
refresh_regions.py      regenerates data/premium_regions.json
test_calculation.py     arithmetic tests on invented premiums, no network

data/                   reference data and recorded state, never hand-edited
scripts/                dev / test / prod / NAS deployment
```

The layout is deliberately flat. A `src/` package would buy tidiness at the
price of five places that can silently break the deployment — the Streamlit
entry path, the Dockerfile `CMD`, `dev.sh`, the `streamlit run app.py` match in
`free_port.sh` and CI — which is a poor trade at this size.

## Installation

Requires Python 3.12 or newer.

```bash
git clone https://github.com/wrangel/viaprima.git
cd viaprima
python3 -m venv ~/.venvs/viaprima
~/.venvs/viaprima/bin/pip install -r requirements.txt
```

The virtual environment deliberately sits outside the project folder — that way it is
neither synchronised by cloud services nor checked in by accident. A path inside the
project (`python3 -m venv venv`) works just as well.

## Usage

### Graphical interface

```bash
~/.venvs/viaprima/bin/streamlit run app.py
```

Opens <http://localhost:8501>. The household is entered as a list of people, one box per
person. Each person carries their own postcode, age, accident cover, expected healthcare
costs and selection of tariff models — a household can be spread across municipal
boundaries, and someone who wants free choice of doctor for themselves does not
necessarily want it for everyone else.

Per person, when the box is expanded:

- the cheapest deductible at the healthcare costs entered, and the resulting annual total,
- the cost curves of all deductibles as a chart, with the tipping point and the expected
  costs marked,
- the cheapest offers for that deductible, including insurer and tariff model, with the
  current contract marked and ranked if one was entered,
- a comparison of all deductibles at the costs entered,
- the cost matrix as a CSV download.

Below the list, **Gesamtkosten des Haushalts** adds everyone up — people whose box is
collapsed included, so the total does not change just because a section was closed. From
two children onwards it also compares free choice per child against all children with one
insurer, which is the only way any sibling discount is available, and reports the family
cap on cost sharing. The whole household can be downloaded as an Excel workbook: a summary with a total row, then one sheet per person with their cost matrix.

Entries are kept in the browser's `localStorage`, so a reload does not discard
them. That store never leaves the machine — it is not a cookie, so it is never
attached to a request and never reaches the server or its logs. A form nobody
has touched is not stored at all, and *Eingaben löschen* at the foot of the
page deletes it. See [SECURITY.md](.github/SECURITY.md) for why cookies and
query parameters were both rejected.

The interface is available in German, French, Italian and English, chosen at
the top of the page and remembered with the rest of your entries. The
catalogues are one JSON file per language in [`locales/`](locales), flat dotted
keys; German is the fallback, so a key missing from another language shows the
German text rather than a gap.

Two things are deliberately not translated. Insurer names and tariff names come
from the BAG file in German and have no other source — a French page will still
say *Sanitas Grundversicherungen AG — TelMed Basic*. And the DataFrame column
names stay German, because they are what lands in the CSV exports: an export
whose columns are named differently depending on the reader's interface
language cannot be compared with a colleague's. Only the header shown on screen
is translated, through `common.header`.

Romansh is absent on purpose. The BAG publishes no Romansh source text, the
written standard is contested (Rumantsch Grischun against the five idioms), and
a visibly machine-translated page about money and health would serve Romansh
speakers worse than the German one they can already read. The layer is ready if
a translator is ever found.

### Command line

```bash
~/.venvs/viaprima/bin/python main.py
~/.venvs/viaprima/bin/python main.py --canton BE --environmental-rebate 4.75
```

Options: `--canton`, `--region`, `--environmental-rebate`, `--max-costs`.

## Dependencies and tests

`requirements.txt` pins the six direct dependencies exactly.
[Renovate](.github/renovate.json5) proposes updates every Monday morning, set up as in
Abstract Altitudes: minor and patch grouped into one pull request and merged
automatically once the check is green, majors one at a time for review. The GitHub
Actions and the Docker base image follow monthly; base-image updates are never merged
automatically, because CI does not build the image. Security fixes come at once. The
Dependency Dashboard issue lists everything pending.

So that a green check on such a pull request says something, `test_calculation.py`
recomputes on invented premiums: the cost formula, the tipping point, dominated
deductibles, the coinsurance cap and the family cap. The expected values are worked out by
hand and derived in the test, not read off the code.

```bash
python test_calculation.py     # no network, no pytest
```

That closes the gap installation and compilation checks leave open: the whole app is a
chain of computation over pandas. If the behaviour of `groupby`, `idxmin` or
`str.extract` changed, a wrong tipping point would come out without complaint, and
neither installation nor compilation would notice.

## Monitoring the data sources

The switch to premium year 2027 showed how necessary this is — and how badly one can
predict *how* a source breaks. The expectation was that the premium comparison would
silently get new contents at a fixed path while the insurer register would run into a 404.
The opposite happened: the supposedly fixed path
`priminfo.admin.ch/downloads/gesamtbericht_ch.xlsx` was switched off, and the register
stayed reachable. On top of that, practically everything else changed too:

| | up to 2026 | from 2027 |
|---|---|---|
| Location | priminfo.admin.ch | opendata.swiss |
| Sheet name | `Export` | `Sheet1` |
| Region | `PR-REG CH1` | `PR_REG_1` |
| Age class | `AKL-ERW` | `AKA_03_ERW` |
| Accident cover | `OHN-UNF` | `OHN_UNF` |
| Deductible | `FRA-300` | `FRA_01_E_0300` |
| Age subgroup | empty for adults | `E1` / `J1` |
| Tariff types | `TAR-BASE`, `TAR-HAM`, `TAR-HMO`, `TAR-DIV` | `BASE`, `PRAXIS`, `FLEX`, `TEL_DIG`, `PHARM` |
| `isBaseP` | marked duplicates (0 = duplicate-free table) | a plain flag (1 = base tariff) |

The last row was the most dangerous: from 2027 the previous filter `isBaseP == 0` would
have discarded every standard tariff — without complaint, without an error message, with
plausible-looking numbers. `load_premiums` therefore de-duplicates on the business key
instead, and `_normalise_codes` maps the new spellings back onto the previous ones so the
rest of the code speaks a single language.

`check_data_sources.py` compares against the state recorded in `data/data_state.json`:
reachability, premium year, columns, age classes, age subgroups and deductible steps.

```bash
python check_data_sources.py           # check (exit code 1 on a deviation)
python check_data_sources.py --write   # record the new state
```

The workflow [`data-sources.yml`](.github/workflows/data-sources.yml) runs this
automatically: weekly, and daily in September and October, when the BAG publishes the
following year's premiums. If the run fails, GitHub notifies the repository owner. The
project therefore speaks up by itself rather than quietly showing wrong numbers.

**What the monitoring watches is the source, not the result.** Reachability, columns,
value ranges, premium year — things that break the tool or silently falsify it. Which
deductibles are ever the cheapest, and where the tipping point lies, are deliberately
*not* checked against anything.

That distinction is not a detail. That so far only the highest and the lowest deductible
have ever won is an **observation about individual premium years, not a target value**.
Premiums are set anew every year, and what pays off follows from them — not the other way
round. A tool that reported a changed result as a failure would be defending a hypothesis
instead of calculating. So the finding is recorded, never compared: every
`--write` adds an entry to `data/finding_history.json`, where it builds a series across the
years without ever becoming a specification.

`data/data_state.json` is accordingly a memory, not a specification: it records what was last
observed, so that change gets noticed in the first place.

For the same reason, nothing in the interface is hard-wired to say that only two
deductibles matter. The message is generated from `never_optimal`, that is from the loaded
data; if something else comes out, the interface says something else. `test_calculation.py`
likewise never tests the thesis itself, only the mechanics — with invented premiums for
which it has been worked out by hand which deductible dominates.

## What to do at the turn of the year

The BAG publishes the following year's premiums at the end of September. The monitoring
runs daily during those weeks and reports by itself. The sequence:

1. **The check fails** — a new premium year, often together with changed URLs or codes.
   The message says what has shifted.
2. **Update**: the download address and the spellings in `constants.py` and
   `_normalise_codes`, the environmental levy refund for the new year, and a look at
   whether `data/insurers.json` still knows every insurer.
3. **Record**:

   ```bash
   python check_data_sources.py --write
   ```

   That overwrites `data/data_state.json` (only ever the present) and **appends** an entry for
   the new premium year to `data/finding_history.json`.

`data/finding_history.json` is the only part that grows: one entry per year with the
deductibles that were ever cheapest and the tipping point. Over the years that builds a
series against which the observation in the section below can actually be checked —
instead of being asserted from memory. The series starts with premium year 2027; earlier
years are deliberately not backfilled, because they come from a different source with
different de-duplication and would not be comparable.

## Annual maintenance

- **Environmental levy refund** — changes every year (2027: CHF 57.00 per person and year,
  so 4.75 per month; 2026 it was 61.80 and 5.15). Set as `environmental_rebate_default` in
  `constants.py`. It does not move the tipping point, but it does affect every absolute
  amount.
- **Insurer names** — `data/insurers.json` comes from the
  [BAG register of authorised health insurers](https://www.bag.admin.ch/de/verzeichnisse-der-zugelassenen-kranken-und-rueckversicherer).
  The download URL contains a hash that changes annually: read the new URL off the page,
  enter it in `refresh_insurers.py` and run it.
- **Premium data** — fetched automatically and cached for seven days under `.cache/` (in
  the container, the `premium-cache` volume). To refetch sooner, delete the cached file and
  restart; there is deliberately no button for it in the interface. The notice under the
  info box follows the data: deadlines for 1 January while next year's premiums are loaded,
  an off-season note while they are not yet published, a warning if the data is older than
  the running year.
- **Premium regions** — `data/premium_regions.json` is produced by `refresh_regions.py`. Its
  source URL carries the year (`praemienregionen-2027.xlsx`) and therefore changes
  annually.

## Notes on the data

- **Duplicates.** Up to premium year 2026 the standard tariffs (`TAR-BASE`) appeared twice
  in the BAG table and were removed with a filter on `isBaseP == 0`. From 2027 that flag
  means something else entirely (see the table above), so `load_premiums` de-duplicates on
  the business key — insurer, canton, region, age class, age subgroup, accident cover,
  tariff, deductible. Up to 2026 that removes the duplicates; from 2027 it does nothing.
  Every tariff model is considered, not just the alternative ones.
- Children have the age subgroups `K1`, `K3`, `K4`, `K5` — the **sibling discounts**.
  Their meaning is given in the BAG tariff list (`Tarife.xlsx` on opendata.swiss, category
  `ALT`):

  | Tier | Meaning per the BAG | Insurers | Discount against `K1` |
  |-------|--------------------|---------:|----------------------:|
  | `K1`  | no additional discount | 26 (all) | – (standard tariff) |
  | `K3`  | discount from the 3rd child | 13 | 60 % |
  | `K4`  | discount from the **2nd** child, valid for all children | 1 | 1.6 % |
  | `K5`  | discount from the 3rd child, valid for all children | 4 | 25 % |

  The discount figures are medians across all tariffs and deductibles in ZH region 1. Note
  that `K4` means the discount from the **second** child, not the fourth — the number in
  the code is a tier number, not a child count. No `K2` exists anywhere in Switzerland.

  These are four schemes, of which a family picks one — **not** a construction kit from
  which each child takes the cheapest. `K4` for one child and `K5` for another is not a
  hybrid that can be bought, so `children_with_one_insurer` iterates over whole schemes and
  only chooses the deductible per child freely within a scheme.

  Any sibling discount requires **all children to be with the same insurer**. The interface
  therefore computes the children jointly and sets the result against free choice per child
  without a discount, taking whichever is cheaper. Should a tier appear whose conditions
  are not documented, it is reported rather than silently passed over — it could carry a
  discount the calculation would otherwise be withholding.

- Children's **basic insurance** (standard model) is offered exclusively *without* accident
  cover. Filtering children by `MIT-UNF` — the default — therefore compares alternative
  models only.

## An observation on the side

This section is not part of the tool. It describes what has come out of using it so far.
It is an observation, not an assumption — the calculation always works from the loaded
data.

The continuously extended series is in
[`data/finding_history.json`](data/finding_history.json) — one entry per premium year, from 2027 on.

**So far only the highest and the lowest deductible have won.** In premium year 2027 the
steps 500, 1000, 1500 and 2000 are optimal at *no* healthcare costs; either the 300 or the
2500 always comes out cheaper. The same for children — only 0 and 600, never the five
steps in between. Recomputed for all 42 canton/region combinations and, in Zurich region 1,
additionally for each of the 128 individual insurer/tariff combinations: no counterexample.
Looked at across several premium years, the picture has stayed stable.

**The ordinance does not prescribe this.** It merely caps the premium reduction at no more
than 70 per cent of the risk assumed with the higher deductible
(Art. 95 para. 2<sup>bis</sup> KVV); the level itself is set by the insurers "on the basis
of insurance requirements" (Art. 95 para. 1<sup>bis</sup> KVV). That the middle steps
nonetheless win nowhere is market behaviour, not a legal consequence — and premiums are set
anew every year. The observation can therefore stop holding at any time without anything
having gone wrong.

**The tipping point has been surprisingly stable so far.** For premium year 2027 it lies
between CHF 1,706 and 1,900 for adults, and every one of the 42 canton/region combinations
falls inside 1,700–1,950 (ZH region 1: 1,893; my own earlier runs put 2026 at 1,892, which
predates the recorded series). For children the range is CHF 386 to 467.

> **On the 42.** The BAG's `Kanton` column carries 28 values, not 26. `ZE` and `ZR` are the
> categories for people insured in Switzerland but living abroad, not cantons. They cannot
> be reached through the postcode lookup, so they never affect a user, but a national figure
> computed naively over that column will quietly include them — and `ZE` carries adult
> premiums around CHF 65, which drags the apparent national minimum down to 590. Every
> figure in this section is computed over the 26 cantons' premium regions only.

**Where this comes from.**\* The tipping point is not something I read somewhere. It came
out of working the numbers for my own family, year after year, long before this app existed.
The arithmetic does hold up independently: a published closed form for the 300/2500 pair,

```
S = 40/3 × (premium₃₀₀ − premium₂₅₀₀ + 22.5)
```

agrees with this tool to within a franc in all 42 combinations. Note what it cannot do,
though. The low deductible is baked into that 22.5 — `40/3 × 22.5` is exactly 300 — so the
formula only ever compares the two endpoints. Anyone applying it has already assumed the
steps in between are irrelevant. This tool computes all of them and finds that they are,
which is a different and stronger statement.

\* Observation, not doctrine. See the caveat about the ordinance above: premiums are reset
every year, and the day the middle steps start winning, this tool will say so.

## How seriously to take the tipping point

Briefly: less seriously than the number looks. The tool computes the tipping point to the
franc, but the cost curves cross very flatly. Two things worth knowing before putting
weight on the value:

**Choosing between the two is very much worth it.** Someone who estimates their healthcare
costs realistically saves up to CHF 1,433 per year against the worse of the two (adults,
ZH region 1), or CHF 420 (children). At zero healthcare costs, deductible 2,500 beats
deductible 300 by exactly those 1,433 francs.

**But adjacent steps sit close together.** Against the *next best* step, the lowest
deductible gains at most around CHF 70 per year (adults) or 30 (children). Empirically the
steps appear to be priced so that consecutive ones almost balance out. That is exactly why
the tipping point is blurry: what matters is the direction — high or low deductible — not
the franc.

**For comparison, the choice of insurer.** At an identical deductible, more than CHF 2,000
per year separates the cheapest provider from the most expensive — more again than the
choice of deductible. Both levers are worth pulling; the interface shows both spreads.

**The environmental levy refund does not move the tipping point.** It is deducted from
every premium equally, so it shifts all cost curves down by the same `12 × refund` and
leaves the ordering unchanged. It affects only the absolute amounts. The same goes for
premium reductions (*Prämienverbilligung*). Entering the new value each year is therefore
worth it for correct totals, but changes nothing about the deductible recommendation.

Rather than looking at the tipping point alone, the interface therefore also reports how
much is actually at stake: the spread between the best and the worst deductible, which is
typically a multiple of the gap between neighbouring steps.

## What is not taken into account

- **Premium reductions** (*Prämienverbilligung*), supplementary insurance, the hospital
  contribution of CHF 15 per day, and the particulars of individual models.
- **The family cap for children on different deductibles.** Children of one family with
  the same insurer share a cap on cost sharing, and the household total includes it when
  they share a deductible: 300 + 700 CHF together with no deductible (Art. 64 para. 4 KVG),
  twice the per-child maximum with a chosen one (Art. 93 para. 3 KVV). With different
  deductibles the ordinance leaves the cap to the insurer, which publishes it nowhere, so
  the total for that case is computed without one. The per-person curves never include
  the cap: it is a property of the household, not of one child.
- **Restrictions on the choice of doctor.** Alternative models (HMO, family doctor,
  telemedicine) are included in the premiums, but their conditions are not evaluated. The
  cheapest premium is not automatically the most suitable model — the cheapest are almost
  always models that restrict the choice of doctor.

The tool is a calculation aid and not financial or insurance advice.

## Contact

Questions, corrections, or a number that looks wrong:
[contact@abstractaltitudes.anonaddy.com](mailto:contact@abstractaltitudes.anonaddy.com)

Corrections are genuinely welcome — the whole point of computing from the
official data is that an error is findable. What this address is not is
insurance advice about an individual policy; see the disclaimer above.

That address is an alias, not a mailbox. Security findings go through
[private vulnerability reporting](.github/SECURITY.md) rather than a public
issue.

## Design

The palette, typography and footer are shared with
[Abstract Altitudes](https://abstractaltitudes.com); [BRAND.md](BRAND.md) records
what was taken from it and the one place the two deliberately differ.

## Licence

[MIT](LICENSE) — Copyright (c) 2017-2026 Matthias Wettstein.

The premium data comes from the Federal Office of Public Health and is subject to its
terms of use.

## Running it in a container

Three steps, the same as in abstractaltitudes, just without pnpm:

```bash
make dev     # run the app locally from the virtual environment, no container
make test    # build an image for this machine and check it in a container
make prod    # build the image for the Synology (linux/amd64) and publish it
```

`make test` deliberately builds for this machine's own architecture. A `linux/amd64` image
would only run emulated on an Apple machine, and pandas crashes inside it with
`qemu: uncaught target signal 11` — that is a quirk of the emulation, not of the image. The
platform is controlled by the variable `TARGET_PLATFORM`; without it, `linux/amd64`
applies, i.e. the Synology.

Both free the port beforehand if it is held by this project's own app or container, so
`make dev` and `make test` do not tread on each other. If a foreign process holds it, they
stop and say which, rather than killing it. To run them side by side, use the port:

```bash
PORT=8502 make test
```

`make prod` runs the tests first, then builds for `linux/amd64` and pushes the image to
Docker Hub. On the Synology afterwards:

```bash
docker pull wrangel/viaprima:1.0
```

`make check` runs the tests and the data-source monitor without touching Docker.

### Making it publicly reachable

The order is not arbitrary: a certificate is issued for a name, so the name has to exist
first.

1. **Name.** Either your own domain, or free of charge via DSM:
   *Control Panel → External Access → DDNS*, provider Synology, giving
   `something.synology.me`. That is enough to start with and saves the detour via a
   registrar.

2. **Router.** Forward port 443 to the NAS, and **port 80 as well** — not for operation,
   but because Let's Encrypt uses it to verify that the name really is yours. If your
   provider blocks port 80, the certificate is only obtainable via the DNS challenge.

3. **Certificate.** *Control Panel → Security → Certificate → Add → Let's Encrypt*, with
   the name from step 1 as the domain. DSM renews it by itself afterwards.

4. **Reverse proxy.** *Control Panel → Login Portal → Advanced → Reverse Proxy*:

   | | |
   |---|---|
   | Source | HTTPS, name from step 1, port 443 |
   | Destination | HTTP, `localhost`, port 8501 |

   **This is where the trap is.** Streamlit keeps the connection open over a WebSocket;
   without it the page loads and then sits at "Connecting…" — the interface is there, but
   nothing responds. Under *Custom Header* in the reverse proxy rule, add the **WebSocket**
   template. That sets `Upgrade` and `Connection`, and it is the most common reason a
   Streamlit app looks dead behind a proxy.

5. **HTTP to HTTPS.** A second rule for port 80 on the same name, and **HSTS** enabled in
   the HTTPS rule. Web Station is not needed for this.

6. **Firewall.** *Control Panel → Security → Firewall*: 80 and 443 open, 8501 **not**. It
   is not needed anyway — since this version the container listens only on `127.0.0.1`, so
   it is not reachable from outside at all, only through the proxy on the NAS itself.

Then check — and check properly. That the start page loads says nothing: if the WebSocket
template is missing, `/_stcore/health` still returns 200 and the page shows only its grey
skeleton. The only meaningful test is whether the proxy lets the upgrade through:

```bash
curl -s -i --max-time 20 \
  -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  https://YOURNAME/_stcore/stream | head -3
```

- `HTTP/1.1 101 Switching Protocols` — the proxy passes the WebSocket through, the app
  works.
- `HTTP/2 200` with `content-type: text/html` — the proxy answers the upgrade with the
  page instead of switching the connection. The WebSocket template is missing from the
  rule's headers.

### On the Synology

There, things are only pulled and restarted, never built. In the Task Scheduler as a
user-defined script:

```bash
bash /volume1/homes/Matthias/Drive/Programming/viaprima/scripts/syno-deploy.sh
```

The script pulls exactly the tag written in `docker-compose.yml`, brings the stack back up,
waits until the app responds, and additionally checks that the container can reach the BAG
— without internet this app is worthless, and the network is the part that, in experience
on this NAS, jams after a rebuild. Only this project's images are cleared out;
`premium-cache` is left untouched.

The script reaches the NAS through Synology Drive, not through git, so it can be older than
the version on the Mac. Its `SCRIPT_VERSION` line is printed at the start and says which
version actually ran.

The BAG premium file (around 12 MB) is fetched on first use and lives in the volume
`premium-cache`. Next to it the app stores the parsed table: downloading takes under a
second, parsing the 220,000 rows out of the Excel format about six seconds on a fast
machine and a multiple of that on the Synology. Read back from the cache, startup takes
0.14 seconds. If a newer premium file arrives, the parsed copy is discarded and rebuilt.
That way a restart does not cost those six seconds every time.
