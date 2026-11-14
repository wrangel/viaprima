"""Shared building blocks: loading data, formatting numbers, location, age class.

Everything several views need that is not a view of its own.
"""

import html
import json
import re

import pandas as pd
import streamlit as st

from constants import ADULTS, CHILDREN, DEFAULT_POSTCODE, REGIONS_FILE, YOUNG_ADULTS
from i18n import t
from calculation import load_premiums


# The message says why it takes a moment and that it only takes it once. On the
# first call after a restart the BAG file is parsed - noticeably slow on the
# Synology - and is then held ready in parsed form.
# cache_resource rather than cache_data: cache_data hands every run its own
# copy of the 220,000-row table, cache_resource the same object. Nothing
# modifies it - get_data and friends filter into new frames.
@st.cache_resource(show_spinner=False)
def _premiums(max_age_days: int):
    return load_premiums(max_age_days)


def premiums_cached():
    """The table already loaded - for cached helpers that must not spin."""
    return _premiums(7)


def premiums(max_age_days: int):
    # The spinner text is translated, so it cannot sit in the cache decorator,
    # which is evaluated once at import time before a language is known.
    with st.spinner(t("loading.premiums")):
        return _premiums(max_age_days)


def chf(amount: float, decimals: int = 0) -> str:
    return f"{amount:,.{decimals}f}".replace(",", "'")


def excel_csv(df: pd.DataFrame, index: bool = True) -> bytes:
    """CSV that Excel opens correctly as it is, on a Swiss machine.

    UTF-8 with a byte-order mark - without it Excel reads the file as Mac
    Roman and "Zürich" becomes "Z√ºrich" - and semicolons, the list separator
    of Swiss and German Excel; with commas everything landed in column A.
    """
    return df.to_csv(sep=";", index=index).encode("utf-8-sig")


# Columns whose entries are long enough to wrap onto a second line.
_WRAPPING = {"Versicherer", "Tarif", "Änderung"}

# A swatch colour goes into a style attribute, so only a plain #rrggbb passes.
_HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


def show_table(
    df: pd.DataFrame,
    numbers: dict[str, int | None],
    highlight: list[bool] | None = None,
    counters: tuple[str, ...] = (),
    group: tuple[str, list[str]] | None = None,
    marked: list[bool] | None = None,
    swatches: list[str | None] | None = None,
) -> None:
    """Draw `df` as a plain HTML table, styled by .vp-table in theme.py.

    Not st.dataframe: that draws on a canvas and either cut long insurer
    names or, stretched to the page, spread spare width over every column
    and left right-set numbers far from their left-set headers - and its
    headers cannot be right-aligned at all. Here the browser sizes the
    columns: number columns shrink to their content and sit right, header
    included; text columns take the remaining width, so the table runs flush
    with the page like everything else and no name is ever cut.

    `numbers` maps the right-aligned columns to their decimals for the Swiss
    format (1'318), or to None for a column that is already text ("nein").
    Headers are the translated col.* labels; the DataFrame keeps its German
    column names for the CSV exports. `highlight` tints rows, e.g. today's
    contract. `counters` (Rang, Nr.) stay left but as narrow as numbers.
    `group` puts one header (a col.* key) over adjacent columns; `marked`
    tints those grouped cells in the rows where it is true. `swatches` puts a
    coloured dot before the first counter, per row - the person's colour, as
    in the person headings.
    """

    def css(c: str) -> str:
        if c in numbers:
            return ' class="num"'
        if c in counters:
            return ' class="counter"'
        return ' class="wrap"' if c in _WRAPPING else ""

    def label(c: str) -> str:
        return html.escape(t(f"col.{c}"))

    grouped = group[1] if group else []
    if grouped:
        top, sub = [], []
        for c in df.columns:
            if c not in grouped:
                top.append(f'<th rowspan="2"{css(c)}>{label(c)}</th>')
            elif c == grouped[0]:
                top.append(f'<th colspan="{len(grouped)}" class="group">'
                           f"{label(group[0])}</th>")
            if c in grouped:
                sub.append(f"<th{css(c)}>{label(c)}</th>")
        head = f"{''.join(top)}</tr><tr>{''.join(sub)}"
    else:
        head = "".join(f"<th{css(c)}>{label(c)}</th>" for c in df.columns)
    rows = []
    for i, (_, row) in enumerate(df.iterrows()):
        cells = []
        for c in df.columns:
            value = row[c]
            if not isinstance(value, str) and pd.isna(value):
                text = ""
            elif c in numbers and numbers[c] is not None:
                text = chf(float(value), numbers[c])
            else:
                text = str(value)
            cell_css = css(c)
            if marked and marked[i] and c in grouped:
                cell_css = cell_css.replace('class="', 'class="changed ') if cell_css \
                    else ' class="changed"'
            content = html.escape(text)
            colour = swatches[i] if swatches and i < len(swatches) else None
            if counters and c == counters[0] and colour and _HEX_COLOUR.fullmatch(colour):
                content = f'<span class="swatch" style="color:{colour}">●</span>&nbsp;{content}'
            cells.append(f"<td{cell_css}>{content}</td>")
        current = ' class="current"' if highlight and highlight[i] else ""
        rows.append(f"<tr{current}>{''.join(cells)}</tr>")
    st.markdown(
        f'<div class="vp-table-wrap"><table class="vp-table"><thead><tr>{head}'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


@st.cache_data
def regions_by_postcode() -> dict[str, list[dict]]:
    """Postcode -> possible canton/region combinations (refresh_regions.py)."""
    if not REGIONS_FILE.exists():
        return {}
    return json.loads(REGIONS_FILE.read_text(encoding="utf-8"))


def age_group_for_age(age: int) -> str:
    """The premium age class under the KVG.

    For premiums the KVG knows exactly three classes (Art. 61 para. 3 KVG,
    names per the BAG's "Erläuterungen zu den Prämiendaten"):

        up to 18    Kinder             (AKA_01_KIN)
        19 - 25     Junge Erwachsene   (AKA_02_JUG)
        26 and up   Erwachsene         (AKA_03_ERW)

    There is no class called "Jugendliche", and for premium purposes a
    fourteen-year-old is a child - not only up to 12. `age` is the age reached
    in the premium year; see age_group_for_birth_year.
    """
    if age <= 18:
        return CHILDREN
    if age <= 25:
        return YOUNG_ADULTS
    return ADULTS


def age_group_for_birth_year(birth_year: int, premium_year: int) -> str:
    """The premium age class for a premium year, from the year of birth.

    The class changes at the start of the calendar year after someone turns
    18 or 25 (Art. 61 para. 3 KVG, Art. 89 para. 3 KVV), so what counts is the
    age reached in the premium year: born 2009, 18 in 2027, a child for all
    of 2027; born 2008, 19 in 2027, a young adult. Asking for today's age got
    this wrong for everyone at the boundary - an 18-year-old was priced as a
    child for a year in which they are a young adult.
    """
    return age_group_for_age(premium_year - birth_year)


def premium_year_of(raw: pd.DataFrame) -> int:
    """The premium year of the loaded data, worked out once per table."""
    if "premium_year" not in raw.attrs:
        raw.attrs["premium_year"] = int(raw["Geschäftsjahr"].max())
    return raw.attrs["premium_year"]


def choose_location(key: int, column=None) -> tuple[str, str, str] | None:
    """Ask for the postcode and look up canton and premium region.

    The premium region helps determine the premium, but hardly anyone knows
    which one they live in - everyone knows their postcode. Roughly every
    twelfth postcode does lie in more than one region or canton, though; in that
    case the town is asked for as well, rather than silently taking the first.

    Returns (canton, region, label) or None if nothing matches.
    """
    target = column if column is not None else st
    mapping = regions_by_postcode()
    if not mapping:
        target.error(t("form.regions_missing"))
        return None

    # Seed session_state once instead of passing value= alongside key=.
    # Streamlit warns when a widget is given both, and it is right to: the
    # restored entry and the default disagree, and which one wins is not
    # obvious from the call. Seeding makes session_state the single source and
    # leaves a restored postcode untouched.
    postcode_key = f"postcode_{key}"
    st.session_state.setdefault(postcode_key, DEFAULT_POSTCODE)
    postcode = target.text_input(
        t("form.postcode"), max_chars=4, key=postcode_key
    ).strip()
    entries = mapping.get(postcode)
    if not entries:
        if postcode:
            target.warning(t("form.postcode_unknown", plz=postcode))
        return None

    variants = {(e["canton"], e["region"]) for e in entries}
    if len(variants) > 1:
        # A restored town only stands if it belongs to this postcode.
        if st.session_state.get(f"town_{key}") not in (None, *entries):
            del st.session_state[f"town_{key}"]
        chosen = target.selectbox(
            t("form.town"),
            entries,
            format_func=lambda e: f"{e['town']} ({e['canton']}, {e['region']})",
            key=f"town_{key}",
            help=t("form.town_help"),
        )
    else:
        chosen = entries[0]

    return (
        chosen["canton"],
        f"PR-REG CH{chosen['region']}",
        f"{postcode} {chosen['town']} ({chosen['canton']}, Region {chosen['region']})",
    )


def with_gap_to_cheapest(
    table: pd.DataFrame, column: str, new_column: str
) -> pd.DataFrame:
    """Insert, right next to `column`, the gap to the cheapest offer.

    The cheapest gets 0, every other one the surcharge against it. Only that
    makes it visible whether a rank is a real lead or a rounding difference.
    """
    values = table[column]
    table.insert(
        table.columns.get_loc(column) + 1,
        new_column,
        (values - values.min()).round(2),
    )
    return table
