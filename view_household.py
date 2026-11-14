"""The total across all people."""

import io
import re
from datetime import date

import pandas as pd
import streamlit as st
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

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
    # Children placed together with one insurer (the sibling paragraph below)
    # are shown and counted with that joint recommendation; their own best
    # offers would contradict it.
    children_shared = bool(shared) and shared["total"] < children_separately
    rows = [advised(r, shared if children_shared else None, results) for r in results]
    # The total is what the rows say: per person the advised contract - the
    # cheapest offer, or where today's contract is given, the least change
    # worth making (or staying). Shared children count with the joint total,
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
    # The paragraphs explaining the figures, collected so the Excel file
    # carries the same sentences as the page.
    notes = [t("household.caption", premiums=chf(premiums))]

    # The sibling discount as a second paragraph of that caption, not a box of
    # its own: it explains a figure above rather than adding a new one. Only
    # when it applies - when the children are counted together.
    if shared:
        saving = children_separately - shared["total"]
        tiers = ", ".join(c["tier"] for c in shared["per_child"])
        # Each child's own cheapest offer already at the recommended insurer:
        # then "each child separately" means the same insurer at the normal
        # tariff. Otherwise it means each child at its own cheapest insurer.
        same_insurer = all(
            r["insurer"] == shared["insurer"]
            for r in results if r["age_group"] == CHILDREN
        )
        if saving > 0.5:
            key = ("household.sibling_included" if same_insurer
                   else "household.sibling_included_switch")
            # The saving from the two rounded amounts, so the sentence adds up
            # exactly as read (2'852 - 2'815 = 37, never 38).
            message = t(key,
                        saving=chf(round(children_separately) - round(shared["total"])),
                        separate=chf(children_separately),
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
                message += " " + t("household.family_cap_applied",
                                    cap=chf(shared["family_cap"]), law=t(law),
                                    saving=chf(shared["family_cap_saving"]))
            notes.append(message)
        elif saving < -0.5:
            # Only when the children's own cheapest offers are with different
            # insurers - otherwise one insurer can never cost more. Then the
            # table shows each child on its own, and this says why.
            notes.append(
                t("household.sibling_not_worth",
                  separate=chf(children_separately), insurer=shared["insurer"],
                  total=chf(shared["total"])))
    for note in notes:
        st.caption(note)

    if shared and shared.get("unknown_tiers"):
        st.warning(
            t("household.unknown_tiers",
              tiers=", ".join(shared["unknown_tiers"]))
        )

    def switch(r: dict, row: dict) -> tuple[str, str]:
        """The Ersparnis and Änderung cells: saving a year, and what to change."""
        saving, changes = row["saving"], row["changes"]
        if saving is None:
            return "–", ""
        if saving < noticeable_saving:
            # "keine" only when a switch really saves nothing; a saving of 1 to
            # 49 francs exists, it is just not worth the paperwork.
            if round(saving) <= 0:
                return t("household.switch_none"), ""
            return t("household.switch_below", threshold=noticeable_saving), ""
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
                # female person, whereas the class is what is meant. The
                # person's own number, as in its heading above - not the row
                # position, which shifts when a person has no result yet.
                "Nr.": r.get("number", i),
                "Altersklasse": t(f'age_class.{r["age_group"]}'),
                "Ort": r["town"],
                # Same words as the form and the policies: "mit" / "ohne".
                "Unfalldeckung": t("form.accident_with") if r.get("accident") == "MIT-UNF"
                                 else t("form.accident_without"),
                "Franchise": row["deductible"],
                "Versicherer": row["insurer"],
                "Tarif": row["tariff"],
                # The premium as the policy bills it: per month, after the
                # environmental levy rebate, sibling discount included. The one
                # figure here that can be checked against a policy - Kosten/Jahr
                # adds deductible and coinsurance and cannot.
                "Prämie/Monat": round(row["monthly"], 2),
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
    # Each row carries its person's colour, the dot from the person heading.
    colours = [r.get("colour") for r in results]
    show_table(
        overview,
        {"Franchise": 0, "Prämie/Monat": 2, "Kosten/Jahr": 0, "Ersparnis/Jahr": None},
        counters=("Nr.",),
        group=("Wechsel", ["Änderung", "Ersparnis/Jahr"]),
        marked=changed,
        swatches=colours,
    )
    # How to read the "Wechsel" columns - only when there is something in them,
    # i.e. where today's contract is given.
    switch_notes = []
    if any((r.get("switch") or (None,))[0] is not None for r in results):
        switch_notes.append(t("household.switch_note", threshold=noticeable_saving))
        # The children's sentence only when they are counted together and at
        # least one of them has a saving shown - otherwise it explains nothing.
        if children_shared and any(
            row["saving"] is not None
            for r, row in zip(results, rows) if r["age_group"] == CHILDREN
        ):
            switch_notes.append(t("household.switch_note_children"))
    for note in switch_notes:
        st.caption(note)

    # The whole household as CSV - with a total row, so the file stands on its
    # own and does not have to be added up again.
    total_row = pd.DataFrame(
        [{
            "Nr.": None,
            "Altersklasse": t("household.total_row"),
            "Ort": "",
            "Unfalldeckung": "",
            "Franchise": None,
            "Versicherer": "",
            "Tarif": "",
            "Prämie/Monat": round(sum(row["monthly"] for row in rows), 2),
            "Kosten/Jahr": round(total),
            "Änderung": "",
            "Ersparnis/Jahr": "",
        }]
    )
    st.download_button(
        t("household.xlsx_button"),
        household_workbook(pd.concat([overview, total_row], ignore_index=True),
                           results, premium_year, notes=notes + switch_notes,
                           colours=colours),
        file_name=f"viaprima.ch {t('household.file_name')} {premium_year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def household_workbook(summary: pd.DataFrame, results: list[dict],
                       premium_year: int | None, notes: list[str] | None = None,
                       colours: list[str | None] | None = None) -> bytes:
    """The household as an Excel file: a summary tab, then one per person.

    Excel rather than CSV, so everything fits in one file with a tab for
    each person - "Zusammenfassung", "Person 1", "Person 2" - and opens
    with umlauts and columns intact. Headers are in the page language; the
    first line names viaprima.ch, where the figures come from. Below the
    table, the same explanatory paragraphs as on the page (`notes`), so the
    file explains its own figures. `colours` tints each person's number as
    the dot does on the page.
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
        _two_decimals(sheet, header_row=3, header=t("col.Prämie/Monat"))
        for row, colour in enumerate(colours or [], start=4):
            if colour and _HEX.fullmatch(colour):
                sheet.cell(row=row, column=1).font = Font(bold=True, color=colour[1:].upper())
        _paragraphs(sheet, notes or [], first_row=3 + len(table) + 2,
                    width=len(table.columns))

        for i, r in enumerate(results, start=1):
            name = t("xlsx.person", n=r.get("number", i))
            matrix = r["matrix"].round(2)
            matrix.columns = [t("xlsx.deductible_column", deductible=chf(d))
                              for d in matrix.columns]
            matrix.index.name = t("xlsx.costs_axis")
            matrix.to_excel(writer, sheet_name=name, startrow=3)
            sheet = writer.sheets[name]
            sheet["A1"] = t(
                "xlsx.person_heading",
                age_class=t(f'age_class.{r["age_group"]}'), town=r.get("town", ""),
                accident=t("xlsx.with_accident") if r.get("accident") == "MIT-UNF"
                else t("xlsx.without_accident"),
                costs=chf(r.get("costs", 0)), deductible=chf(r["deductible"]))
            sheet["A2"] = t("xlsx.matrix_note")
            _tidy(sheet, header_row=4)
    return buffer.getvalue()


_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _two_decimals(sheet, header_row: int, header: str) -> None:
    """Francs and centimes in the premium column, also for 88.00.

    _tidy formats by value, and 88.0 is an integer value - it would read 88
    next to 109.65.
    """
    for cell in sheet[header_row]:
        if cell.value == header:
            for row in range(header_row + 1, sheet.max_row + 1):
                target = sheet.cell(row=row, column=cell.column)
                if isinstance(target.value, (int, float)):
                    target.number_format = "#,##0.00"


def _paragraphs(sheet, notes: list[str], first_row: int, width: int) -> None:
    """Each note across the table's width, wrapped, one row apiece.

    Written after _tidy so the long sentences do not widen column A. Excel
    does not size merged rows by itself, so the height is estimated from the
    text length and the merged width.
    """
    columns = range(1, width + 1)
    chars_per_line = max(40, int(sum(
        (sheet.column_dimensions[get_column_letter(c)].width or 10) for c in columns) * 1.1))
    for offset, note in enumerate(notes):
        row = first_row + offset
        # Markdown is the page's; in a cell, bold markers go and list items
        # become bullets, one per line.
        text = note.replace("**", "").replace("\n\n", "\n").replace("\n* ", "\n• ")
        cell = sheet.cell(row=row, column=1, value=text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
        lines = sum(max(1, -(-len(line) // chars_per_line)) for line in text.split("\n"))
        sheet.row_dimensions[row].height = 15 * lines + 3


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

    Shared children (`shared` given): the joint recommendation for that child.
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
                "monthly": placement["monthly"],
                "saving": saving, "changes": changes}
    saving, changes, target = r.get("switch") or (None, [], None)
    if target:
        return {**target, "saving": saving, "changes": changes}
    return {"insurer": r["insurer"], "tariff": r["tariff"], "deductible": r["deductible"],
            "annual_costs": r["annual_costs"], "premium": r["annual_premium"],
            "monthly": r["monthly_premium"],
            "saving": saving, "changes": changes}
