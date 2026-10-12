"""Page settings and appearance.

Everything that concerns the page as a whole: title, width, and the few style
rules that override Streamlit's defaults.
"""

import streamlit as st

from i18n import t


def configure_page() -> None:
    """Call once per run, before anything else."""
    st.set_page_config(
        page_title=t("page_title"),
        page_icon="seo/favicon.png",  # the same "v" the static page serves
        layout="wide",
    )

    # The multiselect's chips arrive in the theme's accent colour. That belongs
    # to buttons which trigger something - a list of chosen tariff models is a
    # statement, not a warning. Hence neutral grey.
    st.markdown(
        """
        <style>
          /* The grey bar across the top of the page.
             It is the streamlit_js_eval component - the bridge that reads
             saved entries out of localStorage - rendering as an 8px iframe.
             It has no visual job whatsoever.
             Collapsed rather than display:none, because the iframe has to stay
             in the document and keep running its JavaScript; hiding it
             outright risks the browser never loading it, which would take
             persistence down with it. Verified afterwards that entries still
             survive a reload. */
          iframe[data-testid="stCustomComponentV1"] {
              height: 0 !important;
              min-height: 0 !important;
              border: none !important;
              visibility: hidden;
          }
          .stElementContainer:has(> div > iframe[data-testid="stCustomComponentV1"]) {
              margin: 0 !important;
              padding: 0 !important;
              min-height: 0 !important;
          }

          /* The banner carries three facts and a disclaimer, so it earns its
             place - but not the padding Streamlit gives an alert by default.
             Tighter box, tighter line spacing between its two paragraphs, same
             16px text. */
          [data-testid="stAlertContainer"] {
              padding: 0.85rem 1rem !important;
          }
          [data-testid="stAlertContainer"] p { margin-bottom: 0.35rem !important; }
          [data-testid="stAlertContainer"] p:last-child { margin-bottom: 0 !important; }
          /* Streamlit pulls the text block up by 1rem to cancel the last
             paragraph's bottom margin. That margin is already 0 here, so the
             pull-up ate the bottom padding: 14px above the text, -2px below. */
          [data-testid="stAlertContainer"] [data-testid="stMarkdownContainer"] {
              margin-bottom: 0 !important;
          }

          /* Input fields came out at 14px while every label around them was
             16px. The values someone types - postcode, age, expected costs -
             are the most important text on the page and were the smallest on
             it. */
          [data-testid="stTextInput"] input,
          [data-testid="stNumberInput"] input,
          [data-testid="stSelectbox"] input,
          [data-testid="stMultiSelect"] input,
          [data-baseweb="select"] div {
              font-size: 1rem !important;
          }

          /* One text size for the whole page.
             Streamlit renders st.caption at 0.875rem and markdown at 1rem, so
             the explanatory paragraphs - which carry most of the meaning here -
             came out visibly smaller than the info box right beneath them. The
             captions are not asides; they are the text. Same size, and a little
             more contrast than the default muted grey so a long paragraph is
             comfortable rather than merely legible. */
          [data-testid="stCaptionContainer"],
          [data-testid="stCaptionContainer"] p,
          [data-testid="stCaptionContainer"] li {
              font-size: 1rem !important;
              line-height: 1.65 !important;
              /* Muted relative to the theme's own text colour, not a fixed
                 white: the near-white this used to be vanished in light mode.
                 The muting is in the colour, not in opacity - opacity also
                 fades the links, which then fall below 4.5:1 on white.
                 (currentColor inside "color" is the inherited colour.) */
              color: color-mix(in srgb, currentColor 85%, transparent) !important;
          }
          [data-testid="stCaptionContainer"] {
              opacity: 1 !important;
          }
          [data-testid="stMarkdownContainer"] p,
          [data-testid="stMarkdownContainer"] li {
              font-size: 1rem;
              line-height: 1.65;
          }
          /* The wordmark. Larger and tighter than a heading, because it is a
             name rather than a sentence: tracking pulled in so the letters sit
             as one shape, and "prima" in the accent so the two words that make
             up the name are legible as two words. No logo needed. */
          h1.wordmark {
              font-size: 3.6rem !important;
              font-weight: 700 !important;
              letter-spacing: -0.035em !important;
              line-height: 1 !important;
              margin: 0 0 0.1rem 0 !important;
              padding: 0 !important;
          }
          /* .accent, not "span": Streamlit wraps heading text in a span of
             its own, which a bare descendant selector matches - and then the
             whole wordmark turns blue instead of half of it. */
          h1.wordmark .accent { color: #4da6ff; }

          h1 { font-size: 2.1rem !important; line-height: 1.25 !important; }
          h2 { font-size: 1.6rem !important; }
          h3 { font-size: 1.25rem !important; }

          /* The footer, shared with abstractaltitudes. Same measurements as
             its .finalFooter / .footerContent / .creditsList / .copyright:
             centred, capped at 800px, a hairline rule above, links at 0.9rem
             and 70% opacity brightening to the accent, copyright at 0.8rem,
             40% opacity and a letterspace. Taken from that project rather than
             invented, so the two sites recede in the same way. */
          .brand-footer {
              max-width: 800px;
              margin: 5rem auto 0 auto;
              padding: 4rem 1rem;
              border-top: 1px solid rgba(128, 128, 128, 0.25);
              text-align: center;
          }
          .brand-footer-row {
              display: flex;
              flex-wrap: wrap;
              justify-content: center;
              gap: 1.5rem;
              margin-bottom: 1.5rem;
              font-size: 0.9rem;
              font-weight: 300;
          }
          .brand-footer-row a {
              color: inherit !important;
              text-decoration: none !important;
              opacity: 0.7;
              transition: opacity 0.3s, color 0.3s;
          }
          .brand-footer-row a:hover {
              opacity: 1;
              color: #4da6ff !important;
          }
          /* The leading word of the "also by me" row: a label, not a link, so
             dimmer than the entries it introduces. */
          .brand-footer-label { opacity: 0.4; }
          .brand-footer .brand-footer-copyright {
              font-size: 0.8rem !important;
              font-weight: 300;
              opacity: 0.4;
              letter-spacing: 1px;
              margin: 0;
          }
          @media (max-width: 768px) {
              .brand-footer-row {
                  flex-direction: column;
                  gap: 1rem;
              }
          }

          /* The result tables (common.show_table). Full width like every
             other block; number columns shrink to their content (width: 1%
             with nowrap is the classic way) and sit right, header included,
             so text columns take the spare width and no name is cut. Colours
             are theme-relative; the header band matches the light/dark
             dataframeHeaderBackgroundColor in config.toml in weight. */
          .vp-table-wrap { overflow-x: auto; margin: 0.25rem 0 1rem 0; }
          .vp-table {
              width: 100%;
              border-collapse: collapse;
              font-size: 0.9rem;
              font-variant-numeric: tabular-nums;
          }
          .vp-table th, .vp-table td {
              padding: 0.45rem 0.75rem;
              text-align: left;
              white-space: nowrap;
              border: none;
              border-bottom: 1px solid rgba(128, 128, 128, 0.18);
          }
          .vp-table th {
              font-weight: 400;
              color: color-mix(in srgb, currentColor 70%, transparent);
              background: rgba(128, 128, 128, 0.12);
          }
          .vp-table .num { text-align: right; width: 1%; }
          .vp-table .counter { width: 1%; }
          /* Short of room, a long name wraps onto a second line rather than
             pushing the money columns off the edge. Only the long names -
             insurer, tariff, the change - may wrap; "8057 Zürich", numbers
             and the like stay on one line. */
          .vp-table td.wrap { white-space: normal; }
          .vp-table tr.current td { background: rgba(77, 166, 255, 0.18); }
          .vp-table th.group {
              text-align: center;
              border-bottom: 1px solid rgba(128, 128, 128, 0.3);
          }
          /* A change worth making: the same green as "Weitere Person
             hinzufügen", faint, on the two Wechsel cells. */
          .vp-table td.changed { background: rgba(95, 185, 122, 0.18); }

          /* The season line under the info box: when switching is possible.
             Quieter than an alert, but set apart by the brand accent. */
          .season {
              border-left: 3px solid #4da6ff;
              background: rgba(77, 166, 255, 0.08);
              border-radius: 0.5rem;
              padding: 0.75rem 1rem;
              margin: 0 0 1rem 0;
              line-height: 1.6;
          }

          /* The language switch reads as text, not as a control: muted grey,
             no border, no fill, brightening to the accent on hover. */
          [class*="st-key-lang_"] button {
              background: transparent !important;
              border: none !important;
              color: inherit !important;
              opacity: 0.55;
              font-size: 0.9rem !important;
              padding: 0 !important;
              min-height: 0 !important;
              transition: color 0.3s;
          }
          [class*="st-key-lang_"] button:hover { color: #4da6ff !important; opacity: 1; }
          /* Right-aligned and tight, so three stacked links read as one small
             block in the corner rather than three loose buttons. */
          [class*="st-key-lang_"] button div,
          [class*="st-key-lang_"] button p { text-align: right !important; }
          [class*="st-key-lang_"] { margin-bottom: -0.55rem !important; }
          /* Smaller than the wordmark it sits beside, so the eye reaches the
             name first. */
          [class*="st-key-lang_"] button,
          [class*="st-key-lang_"] button p { font-size: 0.82rem !important; }
          [class*="st-key-lang_"] button p {
              font-weight: 300 !important;
              font-size: 0.9rem !important;
          }

          [data-testid="stMultiSelectTagsContainer"] span[data-tag] {
              /* Mid-grey at low alpha reads on black and on white alike. */
              background-color: rgba(128, 128, 128, 0.2) !important;
              color: inherit !important;
          }
          [data-testid="stMultiSelectTagsContainer"] span[data-tag] svg {
              fill: currentColor !important;
          }
          /* Adding green, removing red - the colour should say what happens.
             Streamlit appends the widget key as a class st-key-… on the
             container, which is the only reliable hook onto one specific
             button. */
          .st-key-add_person button {
              background-color: #1b7f4d !important;
              border-color: #1b7f4d !important;
              color: #ffffff !important;
          }
          .st-key-add_person button:hover {
              background-color: #166b41 !important;
          }
          [class*="st-key-remove_"] button {
              background-color: transparent !important;
              border-color: #c2341f !important;
              color: #e06552 !important;
          }
          [class*="st-key-remove_"] button:hover {
              background-color: rgba(194, 52, 31, 0.15) !important;
          }
          /* The selected radio button, neutral for the same reason. The circle
             only: "div div" would also hit the label beside it. */
          [data-testid="stRadioOption"][data-selected="true"] > div > div:first-child {
              background-color: currentColor !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


# One colour per person, so the boxes can be told apart once there are more than
# two. Tones that stay readable on black and on white. The cheapest deductible
# in each person's chart is drawn in the same colour (view_person.person_view).
PERSON_COLOURS = [
    "#4da6ff",  # brand blue - the first person carries the viaprima colour
    "#5fb97a",  # green
    "#c9a227",  # gold
    "#e8913a",  # orange
    "#a97bc9",  # violet
    "#d3756b",  # salmon
    "#d0679f",  # magenta
    "#9aa84a",  # olive
]


def colour_for_person(number: int) -> str:
    """Colour of the nth person, 1-based. Repeats after eight people."""
    return PERSON_COLOURS[(number - 1) % len(PERSON_COLOURS)]


def apply_person_colours(count: int) -> None:
    """Tint the border of each person's box.

    Streamlit appends the container key as a class st-key-…; that is how each
    box can be addressed individually.
    """
    rules = []
    for number in range(1, count + 1):
        colour = colour_for_person(number)
        rules.append(
            f".st-key-person_box_{number} {{ "
            f"border-color: {colour} !important; "
            f"border-left-width: 4px !important; }}"
        )
    st.markdown("<style>" + "\n".join(rules) + "</style>", unsafe_allow_html=True)
