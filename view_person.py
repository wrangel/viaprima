"""The view of a single person: inputs, chart, tables.

person_form() takes the details, person_view() draws the report and
person_summary() returns the same figures without any user interface - for
people whose report is currently collapsed but who still belong in the
household total.

German text in this module is user-facing and stays until the translation layer
arrives. So do the DataFrame column labels, which are shown as table headers and
chart axes.
"""

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from common import (
    age_group_for_birth_year,
    premium_year_of,
    chf,
    excel_csv,
    choose_location,
    show_table,
    with_gap_to_cheapest,
)
from i18n import per_language_key, t
from constants import (
    ADULTS,
    CHILD_SUBGROUPS,
    DEDUCTIBLES,
    TARIFF_TYPES,
    coinsurance_cap,
    coinsurance_rate,
    min_cost_range,
    noticeable_saving,
)
from calculation import (
    available_tariff_types,
    cheapest_premiums,
    compute_tipping_point,
    annual_costs,
    get_data,
)


def person_summary(
    raw, canton, region, age_group, accident_cover, tariff_types,
    child_subgroups, environmental_rebate, expected_costs, current=None,
) -> dict | None:
    """The key figures for one person, without drawing anything.

    Needed for collapsed people: the household total has to include everyone,
    including those whose report is currently folded away - otherwise the total
    changes just because somebody closed a section.
    """
    data = get_data(
        raw, canton=canton, region=region, age_groups=(age_group,),
        accident_cover=accident_cover, child_subgroups=tuple(child_subgroups),
        tariff_types=tuple(tariff_types) if tariff_types else None,
    )
    cheapest = cheapest_premiums(data)
    if cheapest.empty:
        return None
    results = compute_tipping_point(
        cheapest, environmental_rebate, max(min_cost_range, int(expected_costs) + 2000)
    )
    if not results:
        return None

    r = results[0]
    at_expected = r.costs.loc[expected_costs]
    best_deductible = int(at_expected.idxmin())
    at_deductible = data[
        (data["Zielgruppe"] == age_group) & (data["Franchise"] == best_deductible)
    ]
    offer = at_deductible.nsmallest(1, "Prämie")
    if offer.empty:
        return None
    row = offer.iloc[0]
    return {
        "age_group": age_group,
        "deductible": best_deductible,
        "matrix": r.costs,
        "annual_costs": float(at_expected.min()),
        "insurer": row["Versicherername"],
        "tariff": row["Tarifbezeichnung"],
        "annual_premium": (float(row["Prämie"]) - environmental_rebate) * 12,
        "switch": contract_switch(
            data[data["Zielgruppe"] == age_group], current,
            {"insurer": row["Versicherername"], "tariff": row["Tarifbezeichnung"],
             "deductible": best_deductible, "annual_costs": float(at_expected.min()),
             "offers": at_deductible},
            expected_costs, environmental_rebate, age_group),
    }


def switch_saving(offers: pd.DataFrame, current) -> float | None:
    """What switching from today's contract to the cheapest offer saves a year.

    `offers` are the offers at the recommended deductible. None when there is
    no current contract to compare, or it is not among those offers - the
    figure would then rest on a deductible the visitor never told us about.
    """
    if not current:
        return None
    hit = offers[(offers["Versicherername"] == current[0])
                 & (offers["Tarifbezeichnung"] == current[1])]
    if hit.empty:
        return None
    # From the yearly amounts rounded as the table shows them, so the saving
    # always equals the difference of the two figures on screen.
    return float(round(float(hit["Prämie"].min()) * 12)
                 - round(float(offers["Prämie"].min()) * 12))


# The other deductibles, in muted tones - slate, sand, sage, lavender, each
# dark and light - so the cheapest one, in the person's saturated colour,
# stands out in every chart. The same deductible gets the same tone in every
# person's chart.
_FRANCHISE_COLOURS = ["#7f8c9d", "#a9b6c6", "#9c8b7a", "#c6b8a8",
                      "#7d9a8f", "#a9c4b9", "#9a8fb0", "#c4bbd6"]


def contract_switch(
    data: pd.DataFrame, current, best: dict, healthcare_costs: float,
    environmental_rebate: float, age_group: str,
) -> tuple[float | None, list[str]]:
    """What leaving today's contract saves a year, and what would change.

    `best` holds the recommendation: insurer, tariff, deductible, annual
    costs and the offers at its deductible. With today's deductible known,
    whole yearly costs are compared - premium, deductible and coinsurance at
    the expected healthcare costs - so a better deductible counts as much as a
    cheaper insurer. Without it, premiums at the recommended deductible.

    The change named is the least effort that gets within noticeable_saving
    of the cheapest: only the deductible at today's insurer and model, else a
    model (and deductible) at today's insurer, else the full switch. A new
    insurer for one franc is not advice anyone needs. Changes are
    "deductible", "model" and "insurer".
    """
    if not current:
        return None, []
    insurer, tariff, deductible = (list(current) + [None])[:3]
    own = data[data["Versicherername"] == insurer]

    if deductible is None:
        offers = best["offers"]
        today = switch_saving(offers, (insurer, tariff))
        if today is None:
            return None, []
        # Premium differences against the cheapest offer, per tariff of
        # today's insurer, at the recommended deductible.
        same_insurer = offers[offers["Versicherername"] == insurer]
        model_gap = float(round(float(same_insurer["Prämie"].min()) * 12)
                          - round(float(offers["Prämie"].min()) * 12))
        if model_gap < noticeable_saving:
            cheapest_own = same_insurer.loc[same_insurer["Prämie"].idxmin(),
                                            "Tarifbezeichnung"]
            return today - model_gap, ([] if cheapest_own == tariff else ["model"])
        return today, ["insurer"]

    def yearly(rows: pd.DataFrame) -> pd.Series:
        """Rounded yearly costs per row, as the tables show them."""
        return rows.apply(lambda row: round(annual_costs(
            float(row["Prämie"]), int(row["Franchise"]), healthcare_costs,
            environmental_rebate, age_group)), axis=1)

    rows = own[(own["Tarifbezeichnung"] == tariff) & (own["Franchise"] == deductible)]
    if rows.empty:
        return None, []
    today = float(yearly(rows).min())
    cheapest = float(round(best["annual_costs"]))

    same_model = own[own["Tarifbezeichnung"] == tariff]
    stay = yearly(same_model)
    if stay.min() - cheapest < noticeable_saving:
        chosen = same_model.loc[stay.idxmin()]
        return today - float(stay.min()), (
            ["deductible"] if int(chosen["Franchise"]) != deductible else [])

    any_model = yearly(own)
    if any_model.min() - cheapest < noticeable_saving:
        chosen = own.loc[any_model.idxmin()]
        changes = ["deductible"] if int(chosen["Franchise"]) != deductible else []
        return today - float(any_model.min()), changes + ["model"]

    changes = ["deductible"] if best["deductible"] != deductible else []
    return today - cheapest, changes + ["insurer"]


def person_view(
    raw, canton, region, age_group, accident_cover, tariff_types,
    child_subgroups, environmental_rebate, expected_costs, key, current=None,
    colour=None,
):
    """Draw one person and return their key figures for the household total."""
    data = get_data(
        raw,
        canton=canton,
        region=region,
        age_groups=(age_group,),
        accident_cover=accident_cover,
        child_subgroups=tuple(child_subgroups),
        tariff_types=tuple(tariff_types) if tariff_types else None,
    )
    cheapest = cheapest_premiums(data)
    if cheapest.empty:
        st.warning(t("warn.no_premiums"))
        return None

    # The computation always covers a range that includes the costs entered -
    # otherwise a high value would fall outside the cost matrix.
    premium_year = int(raw["Geschäftsjahr"].max())
    cost_range = max(min_cost_range, int(expected_costs) + 2000)
    results = compute_tipping_point(cheapest, environmental_rebate, cost_range)
    if not results:
        st.warning(t("warn.nothing_to_compute"))
        return None
    r = results[0]

    # The top only states what holds at the costs entered. The tipping point
    # itself explains the dashed line in the chart and is therefore stated there.
    at_expected = r.costs.loc[expected_costs]
    best_deductible = int(at_expected.idxmin())
    left, right = st.columns(2)
    left.metric(t("metric.cheapest_deductible"), f"{best_deductible} CHF")
    right.metric(t("metric.total_per_year"), f"{chf(at_expected.min())} CHF")
    st.caption(t("metric.caption"))

    st.subheader(t("chart.heading"))
    curves = r.costs.reset_index().melt(
        id_vars="Krankheitskosten", var_name="Franchise", value_name="Jahreskosten"
    )
    # Vectorised: these used to be Python loops over every one of the some
    # 70,000 points, on every rerun.
    dominated = curves["Franchise"].isin(set(r.never_optimal))
    curves["Rolle"] = np.where(dominated, t("chart.role_never"), t("chart.role_relevant"))
    is_best = curves["Franchise"] == best_deductible
    curves["Gewicht"] = np.where(is_best, "best", np.where(dominated, "never", "other"))
    # The deductible that is cheapest at the current costs is drawn in bold - so
    # you can see at a glance which curve is yours.
    curves["Auswahl"] = np.where(curves["Franchise"] == best_deductible,
                                 t("chart.choice_best"), t("chart.choice_other"))
    curves["Franchise"] = curves["Franchise"].astype(str)

    # Fixed colours per deductible, so the cheapest one can take the person's
    # colour - the bold line then matches the border of the person's box, and
    # the legend still matches the lines. The others keep Streamlit's own
    # categorical colours, in the same order as before.
    palette = {
        str(d): ((colour or "#4da6ff") if d == best_deductible
                 else _FRANCHISE_COLOURS[i % len(_FRANCHISE_COLOURS)])
        for i, d in enumerate(r.costs.columns)
    }

    # A window rather than the whole range: what is shown is the neighbourhood
    # of the two vertical lines. A fixed margin around your own costs alone
    # would push the tipping point out of the picture as soon as the two sit far
    # apart - and so take away precisely the orientation it is there to give.
    margin = 2000
    anchors = [expected_costs] + (
        [r.tipping_point] if r.tipping_point is not None else []
    )
    window_from = max(0, min(anchors) - margin)
    window_to = min(cost_range, max(anchors) + margin)
    curves = curves[curves["Krankheitskosten"].between(window_from, window_to)]

    # Thin out for drawing. The curves are piecewise linear, so every single
    # franc is nothing but payload: within the window that is some 23,000 points
    # or 900 KB of JSON - per chart, per person, on every rerun. At steps of 25
    # that leaves 36 KB for the same picture.
    #
    # The kinks have to survive, though, or the curve gets cut off exactly where
    # it is interesting: where the deductible is exhausted, where the
    # coinsurance reaches its cap, at the tipping point, and at the window
    # edges.
    cap = coinsurance_cap[age_group]
    kinks = {window_from, window_to, int(expected_costs)}
    if r.tipping_point is not None:
        kinks.update({r.tipping_point - 1, r.tipping_point})
    for deductible in r.costs.columns:
        kinks.add(int(deductible))
        kinks.add(int(deductible + cap / coinsurance_rate))
    step = max(1, (window_to - window_from) // 400)
    keep = curves["Krankheitskosten"].isin(kinks) | (
        curves["Krankheitskosten"] % step == 0
    )
    curves = curves[keep]

    chart = (
        alt.Chart(curves)
        .mark_line()
        .encode(
            x=alt.X("Krankheitskosten:Q", title=t("chart.x_axis")),
            y=alt.Y(
                "Jahreskosten:Q",
                title=t("chart.y_axis"),
                scale=alt.Scale(zero=False),
            ),
            color=alt.Color(
                "Franchise:N", sort=None, title="Franchise",
                scale=alt.Scale(domain=list(palette), range=list(palette.values())),
            ),
            strokeWidth=alt.StrokeWidth(
                "Auswahl:N",
                scale=alt.Scale(
                    domain=[t("chart.choice_best"), t("chart.choice_other")],
                    range=[4, 1.5],
                ),
                # Only the bold entry, in the person's colour - the line it
                # stands for. Vega colours all entries of one legend alike, so
                # "andere" went: the thin muted lines are plainly the others.
                legend=alt.Legend(
                    title=t("chart.legend_choice"),
                    values=[t("chart.choice_best")],
                    symbolStrokeColor=colour or "#4da6ff",
                ),
            ),
            opacity=alt.Opacity(
                "Gewicht:N",
                scale=alt.Scale(domain=["best", "other", "never"],
                                range=[1.0, 0.75, 0.3]),
                legend=None,
            ),
            tooltip=[
                "Krankheitskosten",
                "Franchise",
                alt.Tooltip("Jahreskosten", format=".2f"),
                "Rolle",
            ],
        )
        .properties(height=360)
    )
    if r.tipping_point is not None:
        chart += (
            alt.Chart(pd.DataFrame({"k": [r.tipping_point]}))
            .mark_rule(strokeDash=[6, 4], color="#9aa0a6", size=2)
            .encode(x="k:Q")
        )
    here = pd.DataFrame(
        {"k": [expected_costs], "beschriftung": [t("chart.your_costs")]}
    )
    chart += alt.Chart(here).mark_rule(color="#ff4b4b", size=3).encode(x="k:Q")
    chart += (
        alt.Chart(here)
        .mark_text(
            align="left", dx=6, dy=-6, baseline="top", color="#ff4b4b",
            fontSize=12, fontWeight="bold",
        )
        .encode(x="k:Q", y=alt.value(0), text="beschriftung:N")
    )

    # The chart is read-only. Expected costs are set in the number field, the
    # same way as age and accident cover - one way in, not two.
    st.altair_chart(chart, width="stretch")

    # One caption instead of two: both explained the same picture - the vertical
    # lines and the faded curves - and two paragraphs in a row read like two
    # separate topics.
    parts = [t("chart.cap_red_line", amount=chf(expected_costs))]
    if r.tipping_point is None:
        parts.append(t("chart.cap_no_tipping", deductible=r.lowest_deductible))
    else:
        parts.append(
            t(
                "chart.cap_tipping",
                tipping=chf(r.tipping_point),
                low=r.lowest_deductible,
                other=r.segments.iloc[0]["Franchise"],
                spread=chf(r.max_spread),
            )
        )
        if expected_costs > r.tipping_point:
            parts.append(t("chart.cap_above_tipping"))
    if r.never_optimal:
        winners = sorted(set(r.optimal))
        parts.append(
            t(
                "chart.cap_never_optimal",
                winners=t("chart.and").join(f"{w} CHF" for w in winners),
                never=", ".join(str(d) for d in r.never_optimal),
            )
        )
    else:
        parts.append(t("chart.cap_all_optimal"))
    st.caption(" ".join(parts))

    # ------------------------------- Deductibles compared at the given costs
    st.subheader(t("table.costs_per_deductible"))
    comparison = (
        at_expected.rename("Kosten/Jahr")
        .reset_index()
        .rename(columns={"index": "Franchise"})
        .sort_values("Kosten/Jahr")
        .reset_index(drop=True)
    )
    comparison["Franchise"] = comparison["Franchise"].astype(int)
    comparison["Kosten/Jahr"] = comparison["Kosten/Jahr"].round(0)
    comparison = with_gap_to_cheapest(comparison, "Kosten/Jahr", "Mehrkosten/Jahr")
    # Per year only. Franchise and Selbstbehalt are yearly amounts; spread over
    # twelve months they make a figure nobody pays. Monthly figures appear
    # only where they are real: the premium per offer, the household total.
    show_table(comparison, {"Franchise": 0, "Kosten/Jahr": 0, "Mehrkosten/Jahr": 0})

    group_data = data[data["Zielgruppe"] == age_group]

    # ----------------------- The best offers for the deductible that applies
    st.subheader(t("offers.heading", deductible=best_deductible))
    st.caption(t("offers.caption", costs=chf(expected_costs)))
    # The full ranking for this deductible - seven are shown, but today's
    # contract should appear even when it sits further down. Otherwise you only
    # see what is on offer, never where you stand.
    ranking = (
        group_data[group_data["Franchise"] == best_deductible]
        .sort_values("Prämie")
        .reset_index(drop=True)
    )
    ranking["Rang"] = ranking.index + 1

    current_row, current_rank, hit = None, None, None
    if current:
        hit = ranking[
            (ranking["Versicherername"] == current[0])
            & (ranking["Tarifbezeichnung"] == current[1])
        ]
        if not hit.empty:
            current_row = hit.iloc[0]
            current_rank = int(current_row["Rang"])

    shown = ranking.head(7)
    if current_rank is not None and current_rank > 7:
        shown = pd.concat([shown, hit], ignore_index=True)

    offers = shown[
        ["Rang", "Versicherername", "Tarifbezeichnung", "Tariftyp", "Prämie"]
    ].reset_index(drop=True)
    if offers.empty:
        st.info(t("offers.none"))
    else:
        offers = offers.rename(
            columns={
                "Versicherername": "Versicherer",
                "Tarifbezeichnung": "Tarif",
                "Tariftyp": "Typ",
            }
        )
        # Net of the environmental levy rebate, as priminfo shows it ("Total")
        # and as footnote * says: the costs were always computed net, the
        # premiums shown here were gross - 503.50 instead of 498.75.
        net = offers["Prämie"] - environmental_rebate
        offers["Prämie/Jahr"] = (net * 12).round(0)
        offers = with_gap_to_cheapest(offers, "Prämie/Jahr", "Mehrkosten/Jahr")
        offers["Prämie/Monat"] = net.round(2)
        offers["Typ"] = offers["Typ"].map(lambda c: t(f"tariff_short.{c}"))
        columns = ["Rang", "Versicherer", "Tarif", "Typ", "Prämie/Jahr",
                   "Mehrkosten/Jahr", "Prämie/Monat"]
        # Today's contract is marked by a tinted row rather than an extra
        # column: that column had an empty header, so Streamlit sized it to
        # nothing and cut the marker text off. The accent at low alpha reads
        # on black and on white alike.
        # Not "t" for the tariff: that would shadow the translation function.
        is_current = [
            bool(current) and insurer == current[0] and tariff == current[1]
            for insurer, tariff in zip(shown["Versicherername"],
                                       shown["Tarifbezeichnung"])
        ]
        offers = offers[columns]
        show_table(
            offers,
            {"Prämie/Jahr": 0, "Mehrkosten/Jahr": 0, "Prämie/Monat": 2},
            highlight=is_current,
            counters=("Rang",),
        )

        if current and current_rank is None:
            st.caption(
                t("offers.current_missing", insurer=current[0],
                  tariff=current[1], deductible=best_deductible)
            )
        elif current_rank == 1:
            st.success(
                t("offers.current_best", year=premium_year,
                  insurer=current[0], tariff=current[1])
            )
        elif current_rank is not None:
            st.info(
                t("offers.current_rank", insurer=current[0], tariff=current[1],
                  rank=current_rank, total=len(ranking),
                  saving=chf(switch_saving(ranking, current[:2])))
            )

        free_choice = group_data[
            (group_data["Tariftyp"] == "BASE")
            & (group_data["Franchise"] == best_deductible)
        ]
        # offers carries the short form in the column "Typ"; group_data still
        # holds the raw value in "Tariftyp".
        if not free_choice.empty and offers["Typ"].iloc[0] != t("tariff_short.BASE"):
            cheapest_monthly = float(offers["Prämie/Monat"].iloc[0])
            free_monthly = float(free_choice["Prämie"].min()) - environmental_rebate
            # Only the number gets the Swiss thousands separator - a replace on
            # the whole sentence would also swap out the commas in the text.
            surcharge_year = chf((free_monthly - cheapest_monthly) * 12)
            st.caption(
                t("offers.restricted_choice", surcharge=surcharge_year,
                  free=f"{free_monthly:.2f}", cheapest=f"{cheapest_monthly:.2f}")
            )

    st.download_button(
        t("download.cost_matrix"),
        excel_csv(r.costs),
        # The code, not the label: a download name should not change
        # when the interface language does.
        file_name=f"viaprima.ch_kostenmatrix_{age_group.removeprefix('AKL-').lower()}_{canton}.csv",
        mime="text/csv",
        key=f"csv_{key}",
    )

    best_offer = offers.iloc[0] if not offers.empty else None
    return {
        "age_group": age_group,
        "deductible": best_deductible,
        "matrix": r.costs,
        "annual_costs": float(at_expected.min()),
        "switch": contract_switch(
            group_data, current,
            {"insurer": best_offer["Versicherer"] if best_offer is not None else None,
             "tariff": best_offer["Tarif"] if best_offer is not None else None,
             "deductible": best_deductible, "annual_costs": float(at_expected.min()),
             "offers": ranking},
            expected_costs, environmental_rebate, age_group),
        "insurer": best_offer["Versicherer"] if best_offer is not None else "—",
        "tariff": best_offer["Tarif"] if best_offer is not None else "—",
        "annual_premium": (
            float(best_offer["Prämie/Jahr"]) if best_offer is not None else 0.0
        ),
    }


def insurers_and_models(
    raw, canton: str, region: str, age_group: str, accident: str
) -> dict[str, list[str]]:
    """Insurers at this location and their tariff names, for the dropdowns."""
    data = get_data(
        raw, canton=canton, region=region, age_groups=(age_group,),
        accident_cover={age_group: accident},
        child_subgroups=tuple(CHILD_SUBGROUPS),
    )
    if data.empty:
        return {}
    grouped = (
        data.groupby("Versicherername")["Tarifbezeichnung"]
        .apply(lambda s: sorted(s.unique()))
        .to_dict()
    )
    return dict(sorted(grouped.items()))


def person_form(person: dict, person_count: int, raw) -> dict | None:
    """Every detail of one person. Returns the updated entry.

    Location and tariff models sit here rather than in a shared sidebar: a
    household can be spread across municipal boundaries, and someone who wants
    free choice of doctor for themselves does not necessarily want it for
    everyone else.
    """
    person_id = person["id"]
    top = st.columns([3, 2, 3, 3])

    location = choose_location(person_id, top[0])

    # The year of birth, not the age: the premium class is set by the year
    # (age_group_for_birth_year). Seeded, never value= next to key=.
    premium_year = premium_year_of(raw)
    birth_key = f"birth_year_{person_id}"
    st.session_state.setdefault(birth_key, int(person["birth_year"]))
    birth_year = top[1].number_input(
        t("form.birth_year"), min_value=premium_year - 120, max_value=premium_year,
        step=1, format="%d", key=birth_key, help=t("form.birth_year_help"),
    )
    age_group = age_group_for_birth_year(int(birth_year), premium_year)

    # Seeded from the stored entry like the age. An index= by age group alone
    # ignored it, so a child entered without accident cover came back with it
    # after every reload - and was priced with it.
    accident_key = f"accident_{person_id}"
    st.session_state.setdefault(
        accident_key,
        person.get("accident") or ("OHN-UNF" if age_group == ADULTS else "MIT-UNF"),
    )
    accident = top[2].radio(
        t("form.accident"),
        ["MIT-UNF", "OHN-UNF"],
        format_func=lambda a: t("form.accident_with") if a == "MIT-UNF" else t("form.accident_without"),
        horizontal=True,
        key=accident_key,
        help=t("form.accident_help"),
    )

    costs_key = f"costs_{person_id}"
    st.session_state.setdefault(costs_key, int(person["costs"]))
    costs = top[3].number_input(
        t("form.expected_costs"),
        min_value=0, step=100, key=costs_key,
        help=t("form.expected_costs_help"),
    )

    offered = available_tariff_types(raw)
    # Seeded rather than passed as default=, for the same reason as the
    # postcode and the age: default= next to key= makes Streamlit guess which
    # of the two should win when a restored selection is already in state.
    # Keyed per language: see i18n.per_language_key.
    models_key = f"models_{person_id}"
    # A stored selection only seeds the widget if it is still on offer.
    if models_key in st.session_state:
        st.session_state[models_key] = [
            m for m in st.session_state[models_key] if m in offered] or offered
    tariff_types = st.multiselect(
        t("form.tariff_models"),
        offered,
        format_func=lambda m: t(f"tariff.{m}"),
        key=per_language_key(models_key, offered),
        placeholder=t("form.tariff_models_placeholder"),
        help=t("form.tariff_models_help"),
    )
    st.session_state[models_key] = tariff_types

    # Today's contract - so the evaluation can say whether switching is worth it
    # at all, instead of only showing the theoretically cheapest.
    current_insurer, current_model, current_deductible = None, None, None
    if location is not None:
        available = insurers_and_models(
            raw, location[0], location[1], age_group, accident
        )
        if available:
            today = st.columns(3)
            insurer_key = f"current_insurer_{person_id}"
            if st.session_state.get(insurer_key) not in (None, *available):
                st.session_state[insurer_key] = None  # not offered here
            current_insurer = today[0].selectbox(
                t("form.current_insurer"),
                [None, *available],
                format_func=lambda v: t("form.current_insurer_none") if v is None else v,
                key=per_language_key(f"current_insurer_{person_id}"),
                # Shown while nothing is chosen; otherwise Streamlit's own
                # English "Choose an option" appears, whatever the language.
                placeholder=t("form.current_insurer_none"),
                help=t("form.current_insurer_help"),
            )
            st.session_state[f"current_insurer_{person_id}"] = current_insurer
            if current_insurer:
                models = available[current_insurer]
                # A restored model only seeds the dropdown if this insurer
                # still offers it here; otherwise the first one is shown.
                model_key = f"current_model_{person_id}"
                if st.session_state.get(model_key) not in (None, *models):
                    del st.session_state[model_key]
                current_model = today[1].selectbox(
                    t("form.current_model"), models,
                    key=f"current_model_{person_id}",
                    placeholder=t("form.current_model_placeholder"),
                )
                # Optional, and unknown by default like the insurer. With it,
                # the Wechsel column compares whole yearly costs; without it,
                # only insurer and model at the recommended deductible.
                deductibles = DEDUCTIBLES[age_group]
                deductible_key = f"current_deductible_{person_id}"
                if st.session_state.get(deductible_key) not in (None, *deductibles):
                    st.session_state[deductible_key] = None
                current_deductible = today[2].selectbox(
                    t("form.current_deductible"),
                    [None, *deductibles],
                    format_func=lambda d: (t("form.current_deductible_none")
                                           if d is None else f"{chf(d)} CHF"),
                    key=per_language_key(deductible_key),
                    placeholder=t("form.current_deductible_none"),
                    help=t("form.current_deductible_help"),
                )
                st.session_state[deductible_key] = current_deductible

    if location is None:
        st.warning(t("form.no_postcode_warning"))

    # The delete button used to sit in the same row as the tariff models, right
    # next to their own delete and expand icons - a misclick there removes the
    # whole person without asking. It now stands on its own, bottom right.
    if person_count > 1:
        if st.container(horizontal_alignment="right").button(
                t("form.remove_person"), key=f"remove_{person_id}"):
            st.session_state["people"] = [
                p for p in st.session_state["people"] if p["id"] != person_id
            ]
            st.rerun()

    return {
        "id": person_id,
        "birth_year": int(birth_year),
        "accident": accident,
        "costs": int(costs),
        "location": location,
        "tariff_types": tariff_types,
        "age_group": age_group,
        "current": ((current_insurer, current_model, current_deductible)
                    if current_insurer else None),
    }
