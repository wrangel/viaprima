"""All of the computation, none of the user interface.

Vocabulary, since the Swiss terms have no single obvious English equivalent:

    Franchise         deductible          the amount paid before cover starts
    Selbstbehalt      coinsurance         10% share above the deductible
    Kostenbeteiligung cost sharing        deductible plus coinsurance
    Prämie            premium
    Kipppunkt         tipping point       healthcare costs at which the lowest
                                          deductible becomes the cheaper choice

DataFrame column labels stay as the BAG spells them - see constants.py for why.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import json
import urllib.request

import numpy as np
import pandas as pd

from constants import (
    AGE_CLASS_LABELS,
    TARIFF_TYPES,
    ADULTS,
    CACHE_DIR,
    CHILD_SUBGROUPS_DEFAULT,
    CHILDREN,
    INSURERS_FILE,
    YOUNG_ADULTS,
    coinsurance_cap,
    coinsurance_rate,
    min_cost_range,
    ordinary_adult_deductible,
    premiums_sheet,
    premiums_url,
)

# admin.ch rejects requests without a browser user agent.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Default accident cover per age class. Employees are covered through their
# employer, children are not.
_ACCIDENT_DEFAULT = {
    ADULTS: "OHN-UNF",
    YOUNG_ADULTS: "OHN-UNF",
    CHILDREN: "MIT-UNF",
}


def download_file(url: str, filename: str, max_age_days: int = 7) -> Path:
    """Download a file into the cache. An existing download is reused as long as
    it is younger than `max_age_days`."""
    CACHE_DIR.mkdir(exist_ok=True)
    target = CACHE_DIR / filename

    if target.exists():
        age = datetime.now() - datetime.fromtimestamp(target.stat().st_mtime)
        if age < timedelta(days=max_age_days):
            return target

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request) as response:
        content = response.read()

    temp = target.with_suffix(target.suffix + ".part")
    temp.write_bytes(content)
    temp.replace(target)
    return target


def insurer_names() -> dict[int, str]:
    """BAG number -> insurer name (see refresh_insurers.py)."""
    if not INSURERS_FILE.exists():
        return {}
    raw = json.loads(INSURERS_FILE.read_text(encoding="utf-8"))
    return {int(number): name for number, name in raw.items()}


_AGE_CLASSES_FROM_2027: dict[str, str] = {
    "AKA_01_KIN": "AKL-KIN",
    "AKA_02_JUG": "AKL-JUG",
    "AKA_03_ERW": "AKL-ERW",
}

_ACCIDENT_FROM_2027: dict[str, str] = {
    "MIT_UNF": "MIT-UNF",
    "OHN_UNF": "OHN-UNF",
}


def _normalise_codes(df: pd.DataFrame) -> pd.DataFrame:
    """Translate the premium file's keys into this project's spelling.

    With premium year 2027 the BAG changed every code:

        Region            PR-REG CH1  ->  PR_REG_1
        Age class         AKL-ERW     ->  AKA_03_ERW
        Accident cover    OHN-UNF     ->  OHN_UNF
        Deductible        FRA-300     ->  FRA_01_E_0300   (now with age class)

    Rather than pulling the new spelling through the whole project, it is mapped
    back here once. The rest of the code - and with it the tests - therefore
    keeps speaking a single language. Files in the old spelling pass through
    unchanged.
    """
    df = df.copy()

    if "Altersklasse" in df:
        df["Altersklasse"] = df["Altersklasse"].replace(_AGE_CLASSES_FROM_2027)
    if "Unfalleinschluss" in df:
        df["Unfalleinschluss"] = df["Unfalleinschluss"].replace(_ACCIDENT_FROM_2027)

    # PR_REG_1 -> PR-REG CH1
    if "Region" in df:
        df["Region"] = df["Region"].str.replace(
            r"^PR_REG_(\d+)$", r"PR-REG CH\1", regex=True
        )

    # FRA_01_E_0300 -> FRA-300 (leading zeros dropped, age-class letter dropped -
    # the age class sits in a column of its own anyway)
    if "Franchise" in df:
        new = df["Franchise"].str.extract(r"^FRA_\d+_[EJK]_(\d+)$")[0]
        df["Franchise"] = new.where(
            new.isna(), "FRA-" + new.str.lstrip("0").replace("", "0")
        ).fillna(df["Franchise"])

    # The file carries stray blanks in some tariff names ("Helsana BeneFit
    # PLUS Flexmed "); priminfo shows them trimmed.
    if "Tarifbezeichnung" in df:
        df["Tarifbezeichnung"] = df["Tarifbezeichnung"].str.strip()

    return df


def load_premiums(max_age_days: int = 7) -> pd.DataFrame:
    """The raw BAG premium table. The download is about 14 MB and is cached."""
    path = download_file(premiums_url, "praemien_ch.xlsx", max_age_days)

    # Keep the parsed table next to the download. Fetching the 12 MB takes well
    # under a second; parsing the 220,000 rows out of the Excel format costs
    # around six seconds on a fast machine and a multiple of that on the
    # Synology - it is pure computation. Read back from the pickle it is 0.01
    # seconds, roughly 600 times faster.
    #
    # What is cached is deliberately the *raw* table, not the cleaned one: that
    # way changes to the de-duplication and to _normalise_codes take effect
    # immediately, without anyone having to remember to throw the cache away.
    cached = path.with_suffix(".pkl")
    df = None
    if cached.exists() and cached.stat().st_mtime >= path.stat().st_mtime:
        try:
            df = pd.read_pickle(cached)
        except Exception:
            # Unreadable, for instance after a pandas version change: discard and
            # parse again. It is only a cache.
            cached.unlink(missing_ok=True)
            df = None

    if df is None:
        # The sheet was once called "Export" and is now called "Sheet1". If the
        # expected name is missing, take the first sheet rather than crash.
        sheets = pd.ExcelFile(path).sheet_names
        sheet = premiums_sheet if premiums_sheet in sheets else sheets[0]
        df = pd.read_excel(path, sheet_name=sheet)
        try:
            df.to_pickle(cached)
        except Exception:
            # Without write permission it carries on, just slowly.
            pass

    # There used to be a filter on isBaseP == 0 here. That was right for the
    # file up to 2026, where the standard tariffs were listed twice and the
    # 0 rows were exactly the duplicate-free table. From 2027 on isBaseP is a
    # plain flag ("Tarif Base? 1 = yes, 0 = no") and there are no duplicates at
    # all - so the same filter would have discarded every standard tariff
    # without raising an error anywhere. De-duplication now happens on the
    # business key instead: up to 2026 that removes the duplicates, from 2027 on
    # it does nothing.
    key = [
        "Versicherer", "Kanton", "Region", "Altersklasse", "Altersuntergruppe",
        "Unfalleinschluss", "Tarif", "Franchise",
    ]
    df = df.drop_duplicates(subset=[k for k in key if k in df.columns])

    return _normalise_codes(df)


def get_data(
    df: pd.DataFrame,
    canton: str = "ZH",
    region: str = "PR-REG CH1",
    age_groups: tuple[str, ...] = (ADULTS, CHILDREN),
    accident_cover: dict[str, str] | None = None,
    child_subgroups: tuple[str, ...] = CHILD_SUBGROUPS_DEFAULT,
    tariff_types: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Filter the BAG premium data by canton, region, age group and accident
    cover, and normalise deductible, premium and age class."""
    accident_cover = accident_cover or dict(_ACCIDENT_DEFAULT)

    base = df[(df["Kanton"] == canton) & (df["Region"] == region)]
    if tariff_types:
        base = base[base["Tariftyp"].isin(tariff_types)]

    parts = []
    for age_group in age_groups:
        part = base[
            (base["Altersklasse"] == age_group)
            & (base["Unfalleinschluss"] == accident_cover[age_group])
        ]
        if age_group == CHILDREN and child_subgroups:
            part = part[part["Altersuntergruppe"].isin(child_subgroups)]
        parts.append(part)

    filtered = pd.concat(parts) if parts else base.iloc[0:0]

    result = filtered[
        [
            "Versicherer",
            "Altersklasse",
            "Altersuntergruppe",
            "Unfalleinschluss",
            "Tariftyp",
            "Franchise",
            "Prämie",
            "Tarifbezeichnung",
        ]
    ].copy()
    result["Franchise"] = result["Franchise"].str.extract(r"FRA-(\d+)")[0].astype(int)
    result["Prämie"] = result["Prämie"].astype(float)
    # Same values as "Altersklasse" now that identity is the code. Kept as a
    # separate column because the grouping and filtering downstream name it,
    # and collapsing the two is a tidy-up for its own commit, not this one.
    result["Zielgruppe"] = result["Altersklasse"]

    names = insurer_names()
    result["Versicherername"] = (
        result["Versicherer"].map(names).fillna(result["Versicherer"].astype(str))
    )
    return result


def available_tariff_types(df: pd.DataFrame) -> list[str]:
    """The tariff types actually present in the data, ordered as in TARIFF_TYPES.

    The BAG defines five categories, but it does not necessarily ship rows for
    all of them. In premium year 2027 there is not a single PHARM row in the
    national file, although priminfo still offers PHARM as a filter. Presenting
    a choice that cannot match anything is bad enough; here it was actively
    misleading, because pharmacy products do exist - PharMed, Favorit Medpharm,
    casamed pharm, KPTwin.win - and the BAG files them under PRAXIS and FLEX.
    Someone looking for a pharmacy model would have picked the one option that
    excludes every one of them.

    Deriving the list from the data rather than from the vocabulary means a
    category that reappears in a later year is offered again by itself, and one
    that is empty is never offered. TARIFF_TYPES stays the full vocabulary, so
    the label is ready whenever a category shows up.
    """
    # Kept on the frame itself: the form asks for it once per person and
    # per run, and scanning 220,000 rows each time made every click slower.
    if "tariff_types" not in df.attrs:
        present = set(df["Tariftyp"].dropna())
        df.attrs["tariff_types"] = [t for t in TARIFF_TYPES if t in present]
    return list(df.attrs["tariff_types"])


def cheapest_premiums(df: pd.DataFrame) -> pd.DataFrame:
    """Cheapest offer per age group and deductible, including the provider."""
    if df.empty:
        return df
    idx = df.groupby(["Zielgruppe", "Franchise"])["Prämie"].idxmin()
    return df.loc[idx].sort_values(["Zielgruppe", "Franchise"]).reset_index(drop=True)


@dataclass
class Result:
    age_group: str
    premiums: dict[int, float]
    providers: dict[int, str]
    costs: pd.DataFrame
    optimal: pd.Series
    segments: pd.DataFrame
    tipping_point: int | None
    lowest_deductible: int
    saving_at_tipping_point: float | None = None

    @property
    def advantage_of_lowest(self) -> pd.Series:
        """How much better per year the lowest deductible is than the best
        alternative. Negative as long as a higher deductible pays off more."""
        others = self.costs.drop(columns=[self.lowest_deductible])
        return others.min(axis=1) - self.costs[self.lowest_deductible]

    @property
    def max_advantage(self) -> float:
        """Largest advantage of the lowest deductible over the *next best* step.

        Careful, this is narrow: it measures only how close adjacent deductible
        steps sit to each other - not how much the choice of deductible matters
        overall. That is what `max_spread` is for, and it is typically a
        multiple of this.
        """
        return float(self.advantage_of_lowest.max())

    @property
    def never_optimal(self) -> list[int]:
        """Deductibles that are never the cheapest across the whole cost range.

        Empirically that has so far been every middle step - checked across all
        canton/region combinations and individual insurer offers. But that is a
        finding from the data, not a legal consequence: the ordinance only caps
        the premium discount (Art. 95 para. 2bis KVV), the insurers set it
        themselves (para. 1bis). Since premiums are set anew every year, the
        finding is recomputed on every run rather than assumed.
        """
        winners = set(self.optimal)
        return [d for d in self.costs.columns if d not in winners]

    @property
    def spread(self) -> pd.Series:
        """Difference between the best and the worst deductible at each cost
        level - the price of getting it wrong at known healthcare costs."""
        return self.costs.max(axis=1) - self.costs.min(axis=1)

    @property
    def max_spread(self) -> float:
        """Largest difference between the best and the worst deductible. This is
        what the choice of deductible is actually worth: someone who knows their
        healthcare costs saves up to this much per year against the worst
        choice."""
        return float(self.spread.max())

    def material_tipping_point(self, tolerance: float = 50.0) -> int | None:
        """The first healthcare costs at which the lowest deductible is better by
        more than `tolerance` francs per year.

        The plain tipping point is mathematically exact but practically
        worthless: the cost curves cross very flatly, so around it the
        difference is a matter of centimes. Only this value answers from when
        switching is worth noticing.
        """
        hits = self.advantage_of_lowest.index[self.advantage_of_lowest > tolerance]
        return int(hits[0]) if len(hits) else None


def _segments(optimal: pd.Series) -> pd.DataFrame:
    """Collapse contiguous ranges that share the same optimal deductible."""
    changes = optimal.ne(optimal.shift()).cumsum()
    groups = optimal.groupby(changes)
    return pd.DataFrame(
        {
            "Von": groups.apply(lambda g: g.index[0]).values,
            "Bis": groups.apply(lambda g: g.index[-1]).values,
            "Franchise": groups.first().values,
        }
    )


def compute_tipping_point(
    cheapest: pd.DataFrame,
    environmental_rebate: float,
    max_costs: int = min_cost_range,
) -> list[Result]:
    """For each age group, the annual costs per deductible and from them the
    tipping point: the lowest healthcare costs at which the lowest deductible
    wins."""
    healthcare_costs = np.arange(max_costs + 1)
    results = []

    for age_group, group in cheapest.groupby("Zielgruppe"):
        premiums = dict(zip(group["Franchise"], group["Prämie"]))
        providers = dict(zip(group["Franchise"], group["Versicherername"]))
        cap = coinsurance_cap[age_group]

        costs = pd.DataFrame(index=pd.Index(healthcare_costs, name="Krankheitskosten"))
        for deductible, premium in sorted(premiums.items()):
            coinsurance = np.minimum(
                np.maximum(0, healthcare_costs - deductible) * coinsurance_rate,
                cap,
            )
            costs[deductible] = (
                12 * (premium - environmental_rebate)
                + np.minimum(healthcare_costs, deductible)
                + coinsurance
            )

        optimal = costs.idxmin(axis=1)
        lowest = min(premiums)
        hits = optimal.index[optimal == lowest]
        tipping_point = int(hits[0]) if len(hits) else None

        saving = None
        if tipping_point is not None:
            row = costs.loc[tipping_point]
            others = row.drop(index=lowest)
            saving = float(others.min() - row[lowest])

        results.append(
            Result(
                age_group=age_group,
                premiums=premiums,
                providers=providers,
                costs=costs,
                optimal=optimal,
                segments=_segments(optimal),
                tipping_point=tipping_point,
                lowest_deductible=lowest,
                saving_at_tipping_point=saving,
            )
        )
    return results


@dataclass
class Household:
    """Composition of a household. `children` holds, per child, the age subgroup
    the insurer applies to that child (e.g. ("K1", "K1", "K3") for three
    children, one of them on the discounted tier)."""

    adults: int = 1
    young_adults: int = 0
    children: tuple[str, ...] = ()

    @property
    def child_count(self) -> int:
        return len(self.children)


def _price_series(
    base: pd.DataFrame,
    age_class: str,
    accident: str,
    deductible: int,
    subgroup: str | None = None,
) -> pd.Series:
    """Cheapest premium per (insurer, tariff name) for one category of person."""
    part = base[
        (base["Altersklasse"] == age_class)
        & (base["Unfalleinschluss"] == accident)
        & (base["Franchise"] == f"FRA-{deductible}")
    ]
    if subgroup is not None:
        part = part[part["Altersuntergruppe"] == subgroup]
    return part.groupby(["Versicherer", "Tarifbezeichnung"])["Prämie"].min()


def household_offers(
    df: pd.DataFrame,
    household: Household,
    deductible_adults: int = 300,
    deductible_young_adults: int = 300,
    deductible_children: int = 0,
    canton: str = "ZH",
    region: str = "PR-REG CH1",
    accident_cover: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Annual premium for the whole household per insurer and tariff, ascending.

    Only offers that carry *every* required category of person are considered -
    including the requested child subgroups. That is the honest comparison for a
    family: an insurer with cheap adult premiums but no sibling discount can be
    more expensive for the household as a whole.
    """
    accident_cover = accident_cover or dict(_ACCIDENT_DEFAULT)
    base = df[(df["Kanton"] == canton) & (df["Region"] == region)]

    parts: dict[str, pd.Series] = {}
    if household.adults:
        parts[ADULTS] = (
            _price_series(base, ADULTS, accident_cover[ADULTS], deductible_adults)
            * household.adults
        )
    if household.young_adults:
        parts[YOUNG_ADULTS] = (
            _price_series(
                base, YOUNG_ADULTS, accident_cover[YOUNG_ADULTS], deductible_young_adults
            )
            * household.young_adults
        )
    for subgroup in sorted(set(household.children)):
        count = household.children.count(subgroup)
        parts[f"Kinder {subgroup}"] = (
            _price_series(
                base, CHILDREN, accident_cover[CHILDREN], deductible_children, subgroup
            )
            * count
        )

    if not parts:
        return pd.DataFrame()

    combined = pd.concat(parts, axis=1, join="inner").dropna()
    if combined.empty:
        return combined

    combined["Monatsprämie"] = combined.sum(axis=1)
    combined["Jahresprämie"] = combined["Monatsprämie"] * 12

    names = insurer_names()
    result = combined.reset_index()
    result["Versicherername"] = (
        result["Versicherer"].map(names).fillna(result["Versicherer"].astype(str))
    )
    return result.sort_values("Jahresprämie").reset_index(drop=True)


def family_cap(deductible: int) -> float:
    """Most that all children of a family with one insurer pay in cost sharing.

    Two rules, depending on the deductible they share:

    * None (0, the ordinary one for children): Art. 64 para. 4 KVG - together
      at most an adult's deductible and coinsurance cap, 300 + 700.
    * A chosen one (100 to 600): Art. 93 para. 3 KVV - twice the maximum per
      child, 2 x (deductible + 350).

    For children on *different* deductibles Art. 93 para. 3 KVV leaves the
    limit to the insurer, so there is no figure to compute; callers apply no
    cap then.
    """
    if deductible == 0:
        return ordinary_adult_deductible + coinsurance_cap[ADULTS]
    return 2 * (deductible + coinsurance_cap[CHILDREN])


def children_cost_sharing(
    costs_per_child: list[float], deductible: int
) -> tuple[float, bool]:
    """Combined cost sharing of children who share one insurer and deductible.

    Returns (amount, was_capped), with the family cap applied.
    """
    cap = coinsurance_cap[CHILDREN]
    individually = sum(
        min(c, deductible)
        + min(max(0.0, c - deductible) * coinsurance_rate, cap)
        for c in costs_per_child
    )
    maximum = family_cap(deductible)
    return (min(individually, maximum), individually > maximum)


def shared_switch_saving(
    data: pd.DataFrame, shared: dict, child: int, current, accident: str | None = None
) -> float | None:
    """What one child saves a year by moving to the shared recommendation.

    `shared` is the result of children_with_one_insurer, `child` the child's
    position in it. Compared at the deductible and tariff tier the
    recommendation gives that child, so only the premium differs - cost
    sharing is the same on both sides. Today's contract is looked up on the
    same tier (the sibling discount, if its insurer offers one), else on K1.
    None without a current contract or when it is not in the data.
    """
    if not current:
        return None
    if accident is not None:
        data = data[data["Unfalleinschluss"] == accident]
    placement = shared["per_child"][child]
    deductible, tier = placement["deductible"], placement["tier"]

    def monthly(insurer: str, tariff: str, tiers: tuple[str, ...]) -> float | None:
        for code in tiers:
            rows = data[(data["Versicherername"] == insurer)
                        & (data["Tarifbezeichnung"] == tariff)
                        & (data["Franchise"] == deductible)
                        & (data["Altersuntergruppe"] == code)]
            if not rows.empty:
                return float(rows["Prämie"].min())
        return None

    target = monthly(shared["insurer"], shared["tariff"], (tier,))
    today = monthly(current[0], current[1], (tier, "K1"))
    if target is None or today is None:
        return None
    # Rounded yearly amounts, as the tables show them.
    return float(round(today * 12) - round(target * 12))


def shared_contract_switch(
    data: pd.DataFrame, shared: dict, child: int, current,
    healthcare_costs: float, environmental_rebate: float,
    accident: str | None = None,
) -> tuple[float | None, list[str], dict | None]:
    """For a child placed with the shared recommendation: saving and changes.

    Without today's deductible, the premium difference at the recommended
    deductible and tier (shared_switch_saving). With it, whole yearly costs:
    today's contract at today's deductible - on the recommended tier if its
    insurer offers it, else K1 - against the child's placement. The family
    cap is left out on both sides; it is a household amount, not a child's.
    """
    if not current:
        return None, [], None
    insurer, tariff, deductible = (list(current) + [None])[:3]
    placement = shared["per_child"][child]
    changes = []
    if deductible is None:
        saving = shared_switch_saving(data, shared, child, current[:2], accident)
        if saving is None:
            return None, [], None
    else:
        if accident is not None:
            data = data[data["Unfalleinschluss"] == accident]
        rows = data[(data["Versicherername"] == insurer)
                    & (data["Tarifbezeichnung"] == tariff)
                    & (data["Franchise"] == deductible)]
        own = rows[rows["Altersuntergruppe"] == placement["tier"]]
        if own.empty:
            own = rows[rows["Altersuntergruppe"] == "K1"]
        if own.empty:
            return None, [], None
        today = annual_costs(float(own["Prämie"].min()), deductible,
                             healthcare_costs, environmental_rebate, CHILDREN)
        saving = float(round(today) - round(placement["costs"]))
        if deductible != placement["deductible"]:
            changes.append("deductible")
    if insurer != shared["insurer"]:
        changes.append("insurer")
    elif tariff != shared["tariff"]:
        changes.append("model")
    # The advised contract is the box's recommendation for this child.
    return saving, changes, {
        "insurer": shared["insurer"], "tariff": shared["tariff"],
        "deductible": placement["deductible"], "annual_costs": placement["costs"]}


def display_results(
    results: list[Result], window: int = 3, tolerance: float = 50.0
) -> None:
    """Text output for the CLI run."""
    for r in results:
        if r.tipping_point is None:
            print(
                f"\n{AGE_CLASS_LABELS[r.age_group]}: the lowest deductible "
                f"({r.lowest_deductible} CHF) "
                f"never pays off within the range examined."
            )
        else:
            print(
                f"\nFor {AGE_CLASS_LABELS[r.age_group]}, the lowest deductible "
                f"({r.lowest_deductible} CHF) pays off arithmetically from "
                f"{r.tipping_point} CHF of healthcare costs."
            )
            noticeable = r.material_tipping_point(tolerance)
            if noticeable is None:
                print(
                    f"  But: it never gains more than {tolerance:.0f} CHF per year "
                    f"up to {r.costs.index[-1]} CHF of healthcare costs."
                )
            else:
                print(
                    f"  The advantage only becomes noticeable (over "
                    f"{tolerance:.0f} CHF per year) from {noticeable} CHF."
                )
            print(
                f"  Against the next best step it gains at most "
                f"{r.max_advantage:.0f} CHF per year - adjacent deductibles sit "
                f"close together."
            )
            print(
                f"  The choice of deductible as such weighs heavily, though: "
                f"between the best and the worst deductible lie up to "
                f"{r.max_spread:.0f} CHF per year (at {r.spread.idxmax()} CHF of "
                f"healthcare costs)."
            )
            print()
            start = max(0, r.tipping_point - window)
            end = min(r.costs.index[-1], r.tipping_point + window)
            print(r.costs.loc[start:end].round(2).to_markdown())

        print(
            f"\nOptimal deductible by healthcare costs "
            f"({AGE_CLASS_LABELS[r.age_group]}):"
        )
        print(r.segments.to_markdown(index=False))


# The tiers whose conditions are known from the BAG tariff list. The BAG field
# index additionally mentions "K2"; it does not occur anywhere in the national
# data, and the tariff list does not describe it. Should it or any other unknown
# tier appear in future, it must not be passed over silently - it could carry a
# discount that the calculation would then be withholding.
KNOWN_CHILD_TIERS = frozenset({"K1", "K3", "K4", "K5"})


def unknown_child_tiers(data: pd.DataFrame) -> set[str]:
    """Child tariff tiers present in the data whose condition is not known."""
    if "Altersuntergruppe" not in data or "Altersklasse" not in data:
        return set()
    children = data[data["Altersklasse"] == CHILDREN]
    present = set(children["Altersuntergruppe"].dropna())
    return {t for t in present if t not in KNOWN_CHILD_TIERS}


def child_tier_schemes(child_count: int, available: set[str]) -> list[list[str]]:
    """Which tariff tier each child gets, for `child_count` children in one place.

    The meaning of the tiers is in the BAG tariff list (Tarife.xlsx, category
    ALT):

        K1  no additional discount
        K3  discount from the 3rd child
        K4  discount from the 2nd child, valid for all children
        K5  discount from the 3rd child, valid for all children

    That lets the assignment be derived from the number of children rather than
    asked for. "Valid for all children" means: once the threshold is reached,
    the discount applies to every child, not only from the nth onwards. Note
    that K4 refers to the second child, not the fourth - the digit is a tier
    number.

    Returns one scheme per entry, each with one tier per child; the caller picks
    the cheapest, because that depends on the insurer's premiums.
    """
    if child_count <= 0:
        return []

    candidates: list[list[str]] = [["K1"] * child_count]
    if "K4" in available and child_count >= 2:
        candidates.append(["K4"] * child_count)
    if "K5" in available and child_count >= 3:
        candidates.append(["K5"] * child_count)
    if "K3" in available and child_count >= 3:
        # Only the children from the third onwards get the discount.
        candidates.append(["K1", "K1"] + ["K3"] * (child_count - 2))
    return candidates


def cheapest_child_combination(
    premium_per_tier: dict[str, float], child_count: int
) -> tuple[float, list[str]]:
    """Cheapest permissible tier scheme for `child_count` children.

    `premium_per_tier` holds one insurer's monthly premiums per tier. Returns the
    monthly total for all children and the scheme that produces it.
    """
    if child_count <= 0:
        return 0.0, []

    best: tuple[float, list[str]] | None = None
    for scheme in child_tier_schemes(child_count, set(premium_per_tier)):
        if any(tier not in premium_per_tier for tier in scheme):
            continue
        total = sum(premium_per_tier[tier] for tier in scheme)
        if best is None or total < best[0]:
            best = (total, scheme)
    return best if best else (0.0, [])


def annual_costs(
    monthly_premium: float, deductible: int, healthcare_costs: float,
    environmental_rebate: float, age_group: str,
) -> float:
    """One person's costs for a year: premiums, deductible and coinsurance.

    The same formula compute_tipping_point applies to every deductible.
    """
    coinsurance = min(max(0.0, healthcare_costs - deductible) * coinsurance_rate,
                      coinsurance_cap[age_group])
    return (12 * (monthly_premium - environmental_rebate)
            + min(healthcare_costs, deductible) + coinsurance)


def _child_annual_costs(
    premium: float,
    deductible: int,
    healthcare_costs: float,
    environmental_rebate: float,
) -> float:
    """Total costs for one child for a year: premium plus cost sharing."""
    cap = coinsurance_cap[CHILDREN]
    coinsurance = min(
        max(0.0, healthcare_costs - deductible) * coinsurance_rate, cap
    )
    return (
        12 * (premium - environmental_rebate)
        + min(healthcare_costs, deductible)
        + coinsurance
    )


def _each_on_own_deductible(
    premiums: list[pd.Series], scheme: list[str], costs_per_child: list[float],
    environmental_rebate: float,
) -> dict | None:
    """Every child on whichever deductible is cheapest for it.

    No family cap: with different deductibles Art. 93 para. 3 KVV leaves the
    limit to the insurer, so the figure shown is an upper bound.
    """
    total, per_child = 0.0, []
    for premium, tier, healthcare_costs in zip(premiums, scheme, costs_per_child):
        costs = {
            int(deductible): _child_annual_costs(
                monthly, int(deductible), healthcare_costs, environmental_rebate)
            for deductible, monthly in premium[tier].items()
        }
        deductible = min(costs, key=costs.get)
        total += costs[deductible]
        per_child.append({"deductible": deductible, "tier": tier,
                          "costs": costs[deductible]})
    return {"total": total, "per_child": per_child, "family_cap_saving": 0.0}


def _all_on_one_deductible(
    premiums: list[pd.Series], scheme: list[str], costs_per_child: list[float],
    environmental_rebate: float,
) -> dict | None:
    """All children on one common deductible, with the family cap applied.

    The cap only has a statutory figure when the deductible is shared, which
    is why this is computed apart from the free choice above.
    """
    common = set.intersection(*(
        set(premium[tier].index.astype(int))
        for premium, tier in zip(premiums, scheme)))
    best = None
    for deductible in sorted(common):
        per_child = [
            {"deductible": deductible, "tier": tier,
             "costs": _child_annual_costs(premium[tier][deductible], deductible,
                                          healthcare_costs, environmental_rebate)}
            for premium, tier, healthcare_costs in zip(premiums, scheme,
                                                       costs_per_child)
        ]
        uncapped = sum(c["costs"] for c in per_child)
        individually = sum(
            min(c, deductible)
            + min(max(0.0, c - deductible) * coinsurance_rate,
                  coinsurance_cap[CHILDREN])
            for c in costs_per_child
        )
        sharing, _ = children_cost_sharing(costs_per_child, deductible)
        saving = individually - sharing
        total = uncapped - saving
        if best is None or total < best["total"]:
            best = {"total": total, "per_child": per_child,
                    "family_cap_saving": saving,
                    "family_cap": family_cap(deductible)}
    return best


def children_with_one_insurer(
    data: pd.DataFrame, costs_per_child: list[float], environmental_rebate: float,
    accident_per_child: list[str] | None = None,
) -> dict | None:
    """Cheapest offer when all children are with the same insurer.

    That is the condition for any sibling discount. The BAG tariff list
    (Tarife.xlsx, category ALT) describes four schemes, worded identically in
    all four language versions:

        K1  no additional discount
        K3  discount from the 3rd child
        K4  discount from the 2nd child, valid for all children
        K5  discount from the 3rd child, valid for all children

    The qualifier "valid for all children" appears on K4 and K5, not on K3. Two
    children therefore both get the discount under K4, the first one included;
    under K3 only the third child and every further one gets it.

    What matters for the calculation: these are four schemes, of which the
    family picks one - not a construction kit from which each child takes the
    cheapest. K4 for one child and K5 for another is not a hybrid that can be
    bought. The iteration therefore runs over the schemes, and within a scheme
    only the deductible per child is chosen freely.

    `data` must already be filtered by children, location and tariff models.
    `accident_per_child` gives each child's accident cover, and `data` must
    then hold both covers: a child without accident cover is priced without
    it even when its sibling has it. Without the list, `data` must already be
    filtered to one cover.
    """
    count = len(costs_per_child)
    if count == 0 or data.empty:
        return None

    # A tier whose condition we do not know is not considered below. That must
    # not go unnoticed.
    unknown = {
        t for t in set(data["Altersuntergruppe"].dropna())
        if t not in KNOWN_CHILD_TIERS
    }

    best: dict | None = None
    for (insurer, tariff), group in data.groupby(
        ["Versicherername", "Tarifbezeichnung"]
    ):
        rows = group.dropna(subset=["Altersuntergruppe"])
        # Monthly premium per (tier, deductible) at this insurer and tariff -
        # one table per child, for that child's accident cover.
        if accident_per_child:
            premiums = []
            for accident in accident_per_child:
                own = rows[rows["Unfalleinschluss"] == accident]
                premiums.append(
                    own.groupby(["Altersuntergruppe", "Franchise"])["Prämie"].min())
        else:
            premiums = [rows.groupby(["Altersuntergruppe", "Franchise"])["Prämie"].min()
                        ] * count
        if any(p.empty for p in premiums):
            continue  # not offered for one child's accident cover
        # A tier counts as available only if every child can have it.
        available = set.intersection(
            *(set(p.index.get_level_values(0)) for p in premiums))
        for scheme in child_tier_schemes(count, available):
            if any(tier not in available for tier in scheme):
                continue
            for option in (
                _each_on_own_deductible(premiums, scheme, costs_per_child,
                                        environmental_rebate),
                _all_on_one_deductible(premiums, scheme, costs_per_child,
                                       environmental_rebate),
            ):
                if option is None:
                    continue
                if best is None or option["total"] < best["total"]:
                    best = {"insurer": insurer, "tariff": tariff,
                            "scheme": list(scheme), **option}
    if best is not None:
        best["unknown_tiers"] = sorted(unknown)
    return best
