"""The total across all people."""

import io
from datetime import date

import pandas as pd
import streamlit as st

from common import chf, show_table
from constants import CHILDREN, coinsurance_cap, coinsurance_rate, noticeable_saving
from i18n import t


def household_total(
    results: list[dict], child_count: int, shared: dict | None = None,
    premium_year: int | None = None,
) -> None:
    """The total across all people - what the question comes down to in the end."""
    if not results:
        return

    children_separately = sum(
        r["annual_costs"] for r in results if r["age_group"] == CHILDREN
    )
    # Children placed together with one insurer (the box below) are shown and
    # counted with that recommendation; their own best offers would
    # contradict it.
    children_shared = bool(shared) and shared["total"] < children_separately
    rows = [advised(r, shared if children_shared else None, results) for r in results]
    # The total is what the rows say: per person the advised contract - the
    # cheapest offer, or where today's contract is given, the least change
    # worth making (or staying). Shared children count with the box's total,
    # which includes the family cap.
    total = sum(row["annual_costs"] for row, r in zip(rows, results)
                if not (children_shared and r["age_group"] == CHILDREN))
    if children_shared:
        total += shared["total"]
    premiums = sum(row["premium"] for row in rows)

    st.markdown("---")
    st.header(t("household.heading"))

    columns = st.columns(3)
    columns[0].metric(t("household.per_year"), f"{chf(total)} CHF")
    columns[1].metric(t("household.per_month"), f"{chf(total / 12, 2)} CHF")
    columns[2].metric(t("household.people"), str(len(results)))
    st.caption(t("household.caption", premiums=chf(premiums)))

    if shared and shared.get("unknown_tiers"):
        st.warning(
            t("household.unknown_tiers",
              tiers=", ".join(shared["unknown_tiers"]))
        )

    if shared:
        saving = children_separately - shared["total"]
        tiers = ", ".join(c["tier"] for c in shared["per_child"])
        # Each child's own cheapest offer already at the recommended insurer:
        # then there is nothing to choose - staying there together gets the
        # sibling tier anyway. "Each child separately, without discount" is
        # not an option anyone has, so it is not offered as one.
        same_insurer = all(
            r["insurer"] == shared["insurer"]
            for r in results if r["age_group"] == CHILDREN
        )
        if saving > 0.5:
            key = ("household.sibling_automatic" if same_insurer
                   else "household.sibling_discount")
            message = t(key,
                        saving=chf(saving), separate=chf(children_separately),
                        count=child_count, insurer=shared["insurer"],
                        tariff=shared["tariff"], tiers=tiers,
                        total=chf(shared["total"]))
            # Part of the saving can be the statutory family cap rather than a
            # discount - say so, and under which law, since it differs between
            # no deductible (KVG) and a chosen one (KVV).
            if shared.get("family_cap_saving", 0) > 0:
                law = ("law.family_cap_no_deductible"
                       if shared["per_child"][0]["deductible"] == 0
                       else "law.family_cap_chosen_deductible")
                message += "\n\n" + t("household.family_cap_applied",
                                       cap=chf(shared["family_cap"]), law=t(law),
                                       saving=chf(shared["family_cap_saving"]))
            st.info(message, icon="👪")
        elif saving < -0.5:
            # Only when the children's own cheapest offers are with different
            # insurers - otherwise one insurer can never cost more. Equal
            # amounts need no box at all.
            st.info(
                t("household.sibling_not_worth",
                  separate=chf(children_separately), insurer=shared["insurer"],
                  total=chf(shared["total"])),
                icon="👪",
            )

    def switch(r: dict, row: dict) -> tuple[str, str]:
        """The Ersparnis and Änderung cells: saving a year, and what to change."""
        saving, changes = row["saving"], row["changes"]
        if saving is None:
            return "–", ""
        if saving < noticeable_saving:
            return t("household.switch_no"), ""
        current = list(r.get("current") or []) + [None, None, None]
        parts = []
        for c in changes:
            if c == "deductible" and current[2] is not None:
                parts.append(t("change.deductible_detail", old=chf(current[2]),
                               new=chf(row["deductible"])))
            elif c == "model" and current[1]:
                parts.append(t("change.model_detail", old=current[1], new=row["tariff"]))
            else:
                parts.append(t(f"change.{c}"))
        what = " + ".join(parts)
        return t("household.switch_saves", saving=chf(saving)), what[:1].upper() + what[1:]

    overview = pd.DataFrame(
        [
            {
                # Number and age class kept apart: "1. Erwachsene" reads like a
                # female person, whereas the class is what is meant.
                "Nr.": i,
                "Altersklasse": t(f'age_class.{r["age_group"]}'),
                "Ort": r["town"],
                "Franchise": row["deductible"],
                "Versicherer": row["insurer"],
                "Tarif": row["tariff"],
                # Per year only: the monthly figure for the whole household is
                # in the metric above, and a second money column per row
                # next to the yearly saving read as a third kind of amount.
                "Kosten/Jahr": round(row["annual_costs"]),
                # What changes first, then what it saves - under one "Wechsel"
                # header in the table.
                "Änderung": switch(r, row)[1],
                "Ersparnis/Jahr": switch(r, row)[0],
            }
            for i, (r, row) in enumerate(zip(results, rows), start=1)
        ]
    )
    changed = [bool(a) for a in overview["Änderung"]]
    show_table(
        overview,
        {"Franchise": 0, "Kosten/Jahr": 0, "Ersparnis/Jahr": None},
        counters=("Nr.",),
        group=("Wechsel", ["Änderung", "Ersparnis/Jahr"]),
        marked=changed,
    )
    if any((r.get("switch") or (None,))[0] is not None for r in results):
        st.caption(t("household.switch_note", threshold=noticeable_saving))

    # The whole household as CSV - with a total row, so the file stands on its
    # own and does not have to be added up again.
    total_row = pd.DataFrame(
        [{
            "Nr.": None,
            "Altersklasse": t("household.total_row"),
            "Ort": "",
            "Franchise": None,
            "Versicherer": "",
            "Tarif": "",
            "Kosten/Jahr": round(total),
            "Änderung": "",
            "Ersparnis/Jahr": "",
        }]
    )
    st.download_button(
        t("household.xlsx_button"),
        household_workbook(pd.concat([overview, total_row], ignore_index=True),
                           results, premium_year),
        file_name=f"viaprima.ch {t('household.file_name')} {premium_year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def household_workbook(summary: pd.DataFrame, results: list[dict],
                       premium_year: int | None) -> bytes:
    """The household as an Excel file: a summary tab, then one per person.

    Excel rather than CSV, so everything fits in one file with a tab for
    each person - "Zusammenfassung", "Person 1", "Person 2" - and opens
    with umlauts and columns intact. Headers are in the page language; the
    first line names viaprima.ch, where the figures come from.
    """
    buffer = io.BytesIO()
    credit = t("xlsx.credit", year=premium_year, date=date.today().strftime("%d.%m.%Y"))
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        # Amounts the table shows as text ("1'254") go in as numbers, so
        # Excel can add them up; "nein" and "–" stay text.
        table = summary.apply(lambda col: col.map(_as_number)).rename(
            columns=lambda c: t(f"col.{c}"))
        table.to_excel(writer, sheet_name=t("xlsx.summary"), index=False, startrow=2)
        sheet = writer.sheets[t("xlsx.summary")]
        sheet["A1"] = credit
        _tidy(sheet, header_row=3)

        for i, r in enumerate(results, start=1):
            name = t("xlsx.person", n=i)
            matrix = r["matrix"].round(2)
            matrix.columns = [t("xlsx.deductible_column", deductible=chf(d))
                              for d in matrix.columns]
            matrix.index.name = t("xlsx.costs_axis")
            matrix.to_excel(writer, sheet_name=name, startrow=3)
            sheet = writer.sheets[name]
            sheet["A1"] = t(
                "xlsx.person_heading",
                age_class=t(f'age_class.{r["age_group"]}'), town=r.get("town", ""),
                costs=chf(r.get("costs", 0)), deductible=chf(r["deductible"]))
            sheet["A2"] = t("xlsx.matrix_note")
            _tidy(sheet, header_row=4)
    return buffer.getvalue()


def _tidy(sheet, header_row: int) -> None:
    """Readable column widths and Swiss-style number formats."""
    for column in sheet.iter_cols(min_row=header_row):
        values = [str(c.value) for c in column if c.value is not None]
        width = max((len(v) for v in values), default=8)
        sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 45)
        for cell in column[1:]:
            if isinstance(cell.value, float) and not cell.value.is_integer():
                cell.number_format = "#,##0.00"
            elif isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0"


def _as_number(value):
    if isinstance(value, str) and value.replace("'", "").isdigit():
        return int(value.replace("'", ""))
    return value



def advised(r: dict, shared: dict | None, results: list[dict]) -> dict:
    """The contract a person's household row shows, with saving and changes.

    Shared children (`shared` given): the box's recommendation for that child.
    Otherwise, with today's contract given, the advice from contract_switch -
    which is today's contract itself when switching saves too little - and
    without one, the cheapest offer.
    """
    if shared is not None and r["age_group"] == CHILDREN:
        children = [x for x in results if x["age_group"] == CHILDREN]
        placement = shared["per_child"][children.index(r)]
        saving, changes, _ = shared.get("switch_by_id", {}).get(r.get("id"), (None, [], None))
        sharing = (min(r["costs"], placement["deductible"])
                   + min(max(0.0, r["costs"] - placement["deductible"]) * coinsurance_rate,
                         coinsurance_cap[CHILDREN]))
        return {"insurer": shared["insurer"], "tariff": shared["tariff"],
                "deductible": placement["deductible"],
                "annual_costs": placement["costs"],
                "premium": placement["costs"] - sharing,
                "saving": saving, "changes": changes}
    saving, changes, target = r.get("switch") or (None, [], None)
    if target:
        return {**target, "saving": saving, "changes": changes}
    return {"insurer": r["insurer"], "tariff": r["tariff"], "deductible": r["deductible"],
            "annual_costs": r["annual_costs"], "premium": r["annual_premium"],
            "saving": saving, "changes": changes}
