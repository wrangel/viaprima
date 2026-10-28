"""Arithmetic tests on invented premiums - no network, no BAG.

Why: otherwise CI only checks that the dependencies install and that every
module compiles. But the whole app is a chain of computation over pandas. If the
behaviour of ``groupby``, ``idxmin`` or ``str.extract`` changed, a wrong tipping
point would come out without complaint and the check would stay green. These
tests close exactly that gap - above all for Renovate's automerged PRs.

The expected values are worked out by hand, not read off the code. Otherwise the
test would only confirm whatever the program already does.

    python test_calculation.py     # runs without pytest
    pytest test_calculation.py     # also works, if available
"""

from __future__ import annotations

import pandas as pd

from constants import ADULTS, CHILDREN
from calculation import (
    cheapest_child_combination,
    cheapest_premiums,
    child_tier_schemes,
    children_cost_sharing,
    children_with_one_insurer,
    family_cap,
    compute_tipping_point,
    get_data,
    shared_switch_saving,
)

# --------------------------------------------------------------------------
# Invented starting position
#
# Adults, environmental rebate 0, coinsurance 10% up to at most CHF 700:
#
#     costs(d, k) = 12 · premium(d) + min(k, d) + min(max(0, k − d) · 0.1, 700)
#
# With premiums 500.00 (D300) and 380.00 (D2500), for 300 ≤ k < 2500:
#
#     costs(300, k) − costs(2500, k)
#       = 12·(500−380) + 300 + 0.1·(k−300) − k
#       = 1440 + 270 − 0.9·k
#
# That reaches zero at k = 1710 / 0.9 = 1900. Both variants cost exactly
# CHF 6460.00 there. Deductible 1000 at 460.00 is chosen so that it never wins:
# at low costs it does not beat the 2500, at high costs not the 300.
# --------------------------------------------------------------------------

PREMIUMS_ADULTS = {300: 500.00, 1000: 460.00, 2500: 380.00}
EXPECTED_TIPPING_POINT = 1900
COSTS_AT_TIPPING_POINT = 6460.00


def _raw_data(premiums: dict[int, float], age_class: str = "AKL-ERW") -> pd.DataFrame:
    """Build a table in the shape get_data expects."""
    return pd.DataFrame(
        [
            {
                "Kanton": "ZH",
                "Region": "PR-REG CH1",
                "Altersklasse": age_class,
                "Altersuntergruppe": None if age_class == "AKL-ERW" else "K1",
                "Unfalleinschluss": "OHN-UNF" if age_class == "AKL-ERW" else "MIT-UNF",
                "Tariftyp": "TAR-BASE",
                "Tarifbezeichnung": "Testtarif",
                "Versicherer": 8,
                "Franchise": f"FRA-{deductible}",
                "Prämie": premium,
            }
            for deductible, premium in premiums.items()
        ]
    )


def _result(premiums=None, environmental_rebate: float = 0.0, max_costs: int = 10000):
    data = get_data(_raw_data(premiums or PREMIUMS_ADULTS), age_groups=(ADULTS,))
    return compute_tipping_point(
        cheapest_premiums(data), environmental_rebate, max_costs
    )[0]


def test_get_data_normalises_deductible_and_premium():
    """FRA-300 has to become the number 300 - everything else hangs off that."""
    data = get_data(_raw_data(PREMIUMS_ADULTS), age_groups=(ADULTS,))
    assert sorted(data["Franchise"]) == [300, 1000, 2500]
    assert data["Franchise"].dtype.kind == "i", "deductible must be an integer"
    assert data["Zielgruppe"].unique().tolist() == [ADULTS]


def test_cheapest_premiums_takes_the_lowest_per_deductible():
    """Where several offers share a deductible, the cheapest wins."""
    # ignore_index, because the real data comes from a read_excel with a unique
    # index; cheapest_premiums uses .loc on the index values.
    raw = pd.concat(
        [_raw_data({300: 500.00}), _raw_data({300: 444.00}), _raw_data({2500: 380.00})],
        ignore_index=True,
    )
    cheapest = cheapest_premiums(get_data(raw, age_groups=(ADULTS,)))
    premium_300 = cheapest.loc[cheapest["Franchise"] == 300, "Prämie"].iloc[0]
    assert premium_300 == 444.00


def test_cost_formula_matches_the_hand_calculation():
    """Spot checks against values worked out by hand, cap of 700 included."""
    r = _result()
    # k = 0: premium only
    assert r.costs.loc[0, 300] == 12 * 500.00
    # k = 1900: 6000 + 300 deductible + 160 coinsurance
    assert r.costs.loc[1900, 300] == COSTS_AT_TIPPING_POINT
    # k = 1900 at D2500: 4560 + 1900, no coinsurance yet
    assert r.costs.loc[1900, 2500] == COSTS_AT_TIPPING_POINT
    # k = 10000 at D300: coinsurance at the cap (9700 · 0.1 > 700)
    assert r.costs.loc[10000, 300] == 12 * 500.00 + 300 + 700


def test_tipping_point_is_the_hand_calculated_value():
    r = _result()
    assert r.tipping_point == EXPECTED_TIPPING_POINT
    # Just below, the high deductible must win; just above, the low one.
    assert r.optimal.loc[EXPECTED_TIPPING_POINT - 1] == 2500
    assert r.optimal.loc[EXPECTED_TIPPING_POINT + 1] == 300


def test_middle_deductible_is_never_optimal():
    """The central finding of the README and the interface."""
    r = _result()
    assert r.never_optimal == [1000]
    assert sorted(set(r.optimal)) == [300, 2500]


def test_environmental_rebate_does_not_move_the_tipping_point():
    """It relieves every deductible equally and leaves the ordering untouched."""
    without = _result(environmental_rebate=0.0)
    with_rebate = _result(environmental_rebate=12.50)
    assert without.tipping_point == with_rebate.tipping_point
    # The absolute costs do fall, by 12 · 12.50 = 150.
    assert without.costs.loc[0, 300] - with_rebate.costs.loc[0, 300] == 150.0


def test_spread_and_advantage_measure_different_things():
    """max_advantage compares against the next best step, max_spread against the
    worst - confusing the two was once a false statement."""
    r = _result()
    assert r.max_spread > r.max_advantage
    # At k = 0, D300 is dearest and D2500 cheapest: 6000 − 4560.
    assert r.spread.loc[0] == 12 * 500.00 - 12 * 380.00


def test_family_cap_under_art_93_para_3_kvv():
    """Several children with the same insurer: at most 2 × (deductible + 350)."""
    # One child, CHF 5000 of costs, deductible 600:
    # 600 + min(4400 · 0.1, 350) = 600 + 350 = 950, uncapped.
    amount, capped = children_cost_sharing([5000.0], 600)
    assert (amount, capped) == (950.0, False)

    # Two children: 1900 - exactly the limit, so not yet capped.
    amount, capped = children_cost_sharing([5000.0] * 2, 600)
    assert amount == 1900.0 and not capped

    # Three children: 2850 uncapped, cut to 2 × (600 + 350) = 1900.
    amount, capped = children_cost_sharing([5000.0] * 3, 600)
    assert (amount, capped) == (1900.0, True)


def test_family_cap_without_deductible_follows_art_64_para_4_kvg():
    """Deductible 0: together at most an adult's 300 + 700, not 2 x 350."""
    assert family_cap(0) == 1000
    assert family_cap(600) == 2 * (600 + 350)
    # Three children at 0, each at the 350 coinsurance cap: 1050 -> 1000.
    amount, capped = children_cost_sharing([5000.0] * 3, 0)
    assert (amount, capped) == (1000.0, True)


def test_household_children_get_the_family_cap():
    """The cap enters the household figure, on a common deductible only.

    One insurer, tier K1, monthly premium 100 at deductible 0 and 80 at 600,
    three children with CHF 5000 of costs each, no environmental rebate:

    each on its own:   d=0: 1200 + 0 + 350 = 1550;  d=600: 960 + 600 + 350 = 1910
                       -> 3 x 1550 = 4650, uncapped
    all on d=0:        4650 - (1050 - 1000) = 4600
    all on d=600:      3 x 1910 = 5730, sharing 2850 capped to 1900 -> 4780
    cheapest:          all on 0, 4600, of which 50 is the family cap
    """
    data = pd.DataFrame({
        "Versicherername": ["A", "A"],
        "Tarifbezeichnung": ["T", "T"],
        "Altersuntergruppe": ["K1", "K1"],
        "Franchise": [0, 600],
        "Prämie": [100.0, 80.0],
    })
    best = children_with_one_insurer(data, [5000.0] * 3, 0.0)
    assert best["total"] == 4600.0
    assert best["family_cap_saving"] == 50.0
    assert best["family_cap"] == 1000
    assert [c["deductible"] for c in best["per_child"]] == [0, 0, 0]


def test_nothing_shadows_the_translation_function():
    """No loop, comprehension or assignment may bind the name t.

    Not arithmetic, but cheap to check and it bit once: a comprehension over
    tariffs named its loop variable t, so t("offers.current_marker") called a
    tariff name - a TypeError on the live site, only when the visitor's
    current contract was among the cheapest offers.
    """
    import ast
    from pathlib import Path

    for path in Path(__file__).parent.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "from i18n import" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            targets = []
            if isinstance(node, (ast.For, ast.comprehension)):
                targets = [node.target]
            elif isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for target in targets:
                for name in ast.walk(target):
                    assert not (isinstance(name, ast.Name) and name.id == "t"), (
                        f"{path.name}:{name.lineno} binds t, shadowing i18n.t")


def test_switch_saving_compares_today_with_the_cheapest():
    """Saving per year at the recommended deductible, from monthly premiums.

    Offers at 300, 340 and 410 a month; today's contract is B at 340:
    (340 - 300) x 12 = 480. On A, the cheapest, nothing to save. A contract
    not among the offers, or none at all, gives no figure.
    """
    from view_person import switch_saving

    offers = pd.DataFrame({
        "Versicherername": ["A", "B", "C"],
        "Tarifbezeichnung": ["HMO", "Telmed", "Base"],
        "Prämie": [300.0, 340.0, 410.0],
    })
    assert switch_saving(offers, ("B", "Telmed")) == 480.0
    assert switch_saving(offers, ("A", "HMO")) == 0.0
    assert switch_saving(offers, ("B", "Base")) is None
    assert switch_saving(offers, None) is None


def test_child_switch_is_measured_against_the_shared_recommendation():
    """Children placed together: today's premium against the recommended one.

    Recommendation: insurer A, QualiMed, tier K4, deductible 0, at 90 a month.
    Today on A BASE, which also has K4 (110): (110 - 90) x 12 = 240.
    Today on B, which has no K4 tier, so K1 (100): (100 - 90) x 12 = 120.
    Already on A QualiMed: 0. No contract or an unknown tariff: no figure.
    """
    data = pd.DataFrame({
        "Versicherername": ["A", "A", "A", "B"],
        "Tarifbezeichnung": ["QualiMed", "BASE", "BASE", "Other"],
        "Franchise": [0, 0, 0, 0],
        "Altersuntergruppe": ["K4", "K4", "K1", "K1"],
        "Prämie": [90.0, 110.0, 120.0, 100.0],
    })
    shared = {"insurer": "A", "tariff": "QualiMed",
              "per_child": [{"deductible": 0, "tier": "K4"}] * 2}
    assert shared_switch_saving(data, shared, 0, ("A", "BASE")) == 240.0
    assert shared_switch_saving(data, shared, 1, ("B", "Other")) == 120.0
    assert shared_switch_saving(data, shared, 0, ("A", "QualiMed")) == 0.0
    assert shared_switch_saving(data, shared, 0, None) is None
    assert shared_switch_saving(data, shared, 0, ("A", "Nope")) is None


def test_each_child_is_priced_with_its_own_accident_cover():
    """One child with accident cover, one without, both no healthcare costs.

    Monthly premium at deductible 0, tier K1: 100 with accident cover, 90
    without; no rebate. Correct: 12 x 100 + 12 x 90 = 2280. Pricing both with
    the first child's cover, as before, gave 2400 - which made one insurer for
    both look dearer than each child on its own.
    """
    data = pd.DataFrame({
        "Versicherername": ["A", "A"],
        "Tarifbezeichnung": ["T", "T"],
        "Altersuntergruppe": ["K1", "K1"],
        "Unfalleinschluss": ["MIT-UNF", "OHN-UNF"],
        "Franchise": [0, 0],
        "Prämie": [100.0, 90.0],
    })
    best = children_with_one_insurer(
        data, [0.0, 0.0], 0.0, accident_per_child=["MIT-UNF", "OHN-UNF"])
    assert best["total"] == 2280.0


def test_switch_with_todays_deductible_compares_whole_yearly_costs():
    """Adult, CHF 500 healthcare costs, no rebate, coinsurance 10% up to 700.

    Offers: A HMO at 300 a month with deductible 2500, 400 with 300;
    B BASE at 450 with 300. Recommendation A HMO 2500: 12 x 300 + 500 = 4100.
    Today B BASE 300:  12 x 450 + 300 + 20 = 5720 -> saves 1620, deductible
                       and insurer change.
    Today A HMO 300:   12 x 400 + 300 + 20 = 5120 -> saves 1020, deductible.
    Today A HMO, deductible unknown: premium difference at 2500 -> 0.
    """
    from view_person import contract_switch

    data = pd.DataFrame({
        "Versicherername": ["A", "A", "B"],
        "Tarifbezeichnung": ["HMO", "HMO", "BASE"],
        "Franchise": [2500, 300, 300],
        "Prämie": [300.0, 400.0, 450.0],
    })
    best = {"insurer": "A", "tariff": "HMO", "deductible": 2500,
            "annual_costs": 4100.0, "offers": data[data["Franchise"] == 2500]}
    args = (500.0, 0.0, ADULTS)
    assert contract_switch(data, ("B", "BASE", 300), best, *args)[:2] == (
        1620.0, ["deductible", "insurer"])
    assert contract_switch(data, ("A", "HMO", 300), best, *args)[:2] == (
        1020.0, ["deductible"])
    assert contract_switch(data, ("A", "HMO", None), best, *args)[:2] == (0.0, [])
    assert contract_switch(data, None, best, *args)[:2] == (None, [])


def test_switch_names_only_changes_worth_making():
    """The insurer change is left out when it adds less than 50 CHF.

    Adult, CHF 500 costs, no rebate. S TelMed at 2500: 12 x 300 + 500 = 4100,
    the cheapest. A QualiMed at 2500: 12 x 300.10 + 500 = 4101.2 -> 4101,
    one franc more; at 300: 12 x 390 + 300 + 20 = 5000. Today A QualiMed 300.
    Staying with A and only raising the deductible gets within a franc of the
    cheapest, so the advice is the deductible alone, saving 5000 - 4101 = 899.
    """
    from view_person import contract_switch

    data = pd.DataFrame({
        "Versicherername": ["S", "A", "A"],
        "Tarifbezeichnung": ["TelMed", "QualiMed", "QualiMed"],
        "Franchise": [2500, 2500, 300],
        "Prämie": [300.0, 300.10, 390.0],
    })
    best = {"insurer": "S", "tariff": "TelMed", "deductible": 2500,
            "annual_costs": 4100.0, "offers": data[data["Franchise"] == 2500]}
    saving, changes, advised = contract_switch(
        data, ("A", "QualiMed", 300), best, 500.0, 0.0, ADULTS)
    assert (saving, changes) == (899.0, ["deductible"])
    # The row then shows what to do: stay with A QualiMed, deductible 2500.
    assert (advised["insurer"], advised["tariff"], advised["deductible"],
            advised["annual_costs"]) == ("A", "QualiMed", 2500, 4101.0)


def test_age_class_follows_the_year_of_birth():
    """Premium year 2027 (Art. 61 para. 3 KVG, Art. 89 para. 3 KVV).

    Born 2009: 18 in 2027, a child all year. Born 2008: 19, young adult.
    Born 2002: 25, still a young adult. Born 2001: 26, an adult. Today's age
    would get the second and fourth wrong for anyone whose birthday has
    already passed this year.
    """
    from common import age_group_for_birth_year
    from constants import YOUNG_ADULTS

    assert age_group_for_birth_year(2009, 2027) == CHILDREN
    assert age_group_for_birth_year(2008, 2027) == YOUNG_ADULTS
    assert age_group_for_birth_year(2002, 2027) == YOUNG_ADULTS
    assert age_group_for_birth_year(2001, 2027) == ADULTS


def test_children_have_the_lower_coinsurance_cap():
    """For children the cap is 350 rather than 700 (Art. 103 para. 2 KVV)."""
    data = get_data(
        _raw_data({0: 120.00, 600: 90.00}, age_class="AKL-KIN"),
        age_groups=(CHILDREN,),
    )
    r = compute_tipping_point(cheapest_premiums(data), 0.0, 10000)[0]
    # k = 10000, deductible 0: 12 · 120 + 0 + min(1000, 350) = 1440 + 350
    assert r.costs.loc[10000, 0] == 12 * 120.00 + 350


def test_child_tiers_follow_the_official_conditions():
    """The four schemes of the BAG tariff list, worded identically in every
    language version:

    K1 no discount; K3 from the 3rd child; K4 from the 2nd child, valid for all
    children; K5 from the 3rd child, valid for all children. The qualifier
    "valid for all children" sits on K4 and K5, not on K3 - the whole assignment
    hangs off that.
    """
    all_tiers = {"K1", "K3", "K4", "K5"}

    # One child: no discount reachable, whatever the insurer carries.
    assert child_tier_schemes(1, all_tiers) == [["K1"]]

    # Two children: only K4 applies - and then to both, the first one included.
    schemes = child_tier_schemes(2, all_tiers)
    assert ["K4", "K4"] in schemes
    assert not any("K3" in s or "K5" in s for s in schemes)

    # Three children: K5 for all three, K3 only for the third.
    schemes = child_tier_schemes(3, all_tiers)
    assert ["K5", "K5", "K5"] in schemes
    assert ["K1", "K1", "K3"] in schemes

    # Every scheme is uniform: either one tier for all, or the K3 pattern. They
    # are never mixed - K4 for one child and K5 for the next is not something
    # that can be bought.
    for count in (2, 3, 4, 5):
        for scheme in child_tier_schemes(count, all_tiers):
            assert len(set(scheme)) == 1 or set(scheme) == {"K1", "K3"}

    # Where an insurer does not carry a tier, it does not appear.
    assert child_tier_schemes(3, {"K1"}) == [["K1", "K1", "K1"]]


def test_cheapest_child_combination_picks_the_cheapest():
    """Which tier wins depends on the premiums, not on the tier number."""
    # K4 is barely cheaper here, K5 markedly so: from three children K5 wins.
    premiums = {"K1": 120.0, "K3": 48.0, "K4": 118.0, "K5": 90.0}
    assert cheapest_child_combination(premiums, 1) == (120.0, ["K1"])
    assert cheapest_child_combination(premiums, 2) == (236.0, ["K4", "K4"])
    assert cheapest_child_combination(premiums, 3) == (270.0, ["K5", "K5", "K5"])

    # Without discount tiers it stays on the standard tariff.
    assert cheapest_child_combination({"K1": 100.0}, 3) == (300.0, ["K1"] * 3)

    # No children, no costs.
    assert cheapest_child_combination(premiums, 0) == (0.0, [])


def main() -> int:
    tests = [
        value for name, value in sorted(globals().items()) if name.startswith("test_")
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as problem:
            failures += 1
            print(f"FAILED  {test.__name__}\n        {problem}")
        else:
            print(f"ok      {test.__name__}")
    print(f"\n{len(tests) - failures} of {len(tests)} tests passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
