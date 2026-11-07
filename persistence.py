"""Keeping what someone typed across a page reload.

Streamlit's session_state lives exactly as long as the websocket does. Press F5
and a new session starts, so every postcode, age and cost estimate is gone -
for a household of four that is a lot of retyping for an accidental reload.

**Why localStorage and not a cookie.** A cookie is attached to every request,
so it would pass through Cloudflare, which sits in front of the app, and any
proxy log on the way.
What people enter here - postcode, age, what they expect to spend on doctors -
is health-adjacent, and SECURITY.md says plainly that it is never written
anywhere. localStorage never leaves the browser, so that statement stays true.
Query parameters were rejected for the same reason: they would sit in the URL,
in the browser history, in Cloudflare's request logs, and would leak through the Referer
header the moment somebody clicked one of the footer links.

**The round trip.** streamlit_js_eval runs the expression in the browser and
sends the result back, which means the value is not available on the first run
- it arrives on the next. Two consequences the code below has to handle:

* `None` is ambiguous: it means both "the browser has not answered yet" and
  "nothing is stored". The read therefore appends `|| ''` so an empty string
  means "nothing stored" and only `None` means "not answered yet".
* The component caches per `key`, so a fixed key evaluates once per session.
  Writing uses a key derived from the payload, so a changed payload is a new
  component and actually runs.
"""

import json
from datetime import date

import streamlit as st
from streamlit_js_eval import streamlit_js_eval

from constants import DEFAULT_PERSON, DEFAULT_POSTCODE
from i18n import FALLBACK, current_language, set_language

STORAGE_KEY = "viaprima.inputs.v1"

# Only what the visitor typed. Deliberately not the computed results: those are
# cheap to recompute and would go stale against new premium data.
_PERSON_FIELDS = ("id", "birth_year", "accident", "costs")

# What a stored person has to look like to be trusted. The JSON being
# well-formed says nothing about its contents: a payload written by an older
# version of this app is perfectly valid JSON and can still carry a value the
# current code will never understand. That happened during development, when a
# half-finished change wrote the accident cover as the German word "ohne"
# instead of the code OHN-UNF - and the form then restored it without a
# murmur. Anything that fails these checks is dropped and the defaults apply.
_ACCIDENT_VALUES = {"MIT-UNF", "OHN-UNF"}


def _valid_person(person: object) -> bool:
    if not isinstance(person, dict):
        return False
    try:
        person_id, birth_year, costs = person["id"], person["birth_year"], person["costs"]
        accident = person["accident"]
    except (KeyError, TypeError):
        return False
    return (
        isinstance(person_id, int) and person_id > 0
        and isinstance(birth_year, int) and 1900 <= birth_year <= date.today().year + 1
        and isinstance(costs, int) and 0 <= costs <= 10_000_000
        and accident in _ACCIDENT_VALUES
    )


def _migrate(person: object) -> object:
    """An entry stored before the year of birth replaced the age.

    Without this, everyone who used the app before would lose their whole
    household on the first visit after the update. The year is approximate
    (birthday unknown) - which is why the field changed - but close enough to
    carry the entry over; the visitor sees it and can correct it.
    """
    if isinstance(person, dict) and "birth_year" not in person and isinstance(person.get("age"), int):
        person = {**person, "birth_year": date.today().year - person["age"]}
        person.pop("age")
    return person

_RESTORED = "_restore_done"
_PENDING = "_restore_pending"
_FORGET = "_forget_requested"
_FORGET_RUN = "_forget_counter"
# Whether this browser holds an entry (restored, or written this session), and
# a counter so each removal gets a fresh component key.
_HAS_STORED = "_inputs_stored"
_CLEARS = "_inputs_cleared"


def _widget_keys(person_id: int) -> tuple[str, ...]:
    """The widget state worth keeping that is not already in the person entry."""
    return (f"postcode_{person_id}", f"town_{person_id}", f"models_{person_id}",
            f"current_insurer_{person_id}", f"current_model_{person_id}",
            f"current_deductible_{person_id}")


def _collect() -> dict:
    """The current entries, in the shape they are stored."""
    people = st.session_state.get("people", [])
    widgets: dict[str, object] = {}
    for person in people:
        for key in _widget_keys(person["id"]):
            # None is "no current contract" - the default, not worth storing,
            # and storing it would make an untouched form look edited.
            if st.session_state.get(key) is not None:
                widgets[key] = st.session_state[key]
    return {
        "people": [
            {k: p[k] for k in _PERSON_FIELDS if k in p} for p in people
        ],
        "widgets": widgets,
        "language": current_language(),
    }


def restore(offered_tariff_types: list[str]) -> bool:
    """Put the stored entries back into session_state. Call before any widget.

    Returns True once the browser has answered, whether or not anything was
    stored. While it returns False the caller should not draw the input form:
    it would show defaults for a moment and then visibly replace them.
    """
    if st.session_state.get(_RESTORED):
        return True

    stored = streamlit_js_eval(
        js_expressions=f"localStorage.getItem('{STORAGE_KEY}') || ''",
        key="restore_inputs",
    )
    if stored is None:
        return False  # the browser has not answered yet

    st.session_state[_RESTORED] = True
    if not stored:
        return True  # answered, and there was nothing stored
    st.session_state[_HAS_STORED] = True

    try:
        data = json.loads(stored)
        # The language is restored even if the rest turns out unusable: it is
        # the one choice that should survive regardless.
        if isinstance(data, dict) and data.get("language"):
            set_language(data["language"])
        people = [_migrate(p) for p in data["people"]]
        assert isinstance(people, list) and people
        assert all(_valid_person(p) for p in people)
        assert len({p["id"] for p in people}) == len(people)
    except (ValueError, KeyError, AssertionError, TypeError):
        # Written by an older version, hand-edited, or truncated. Not worth a
        # message to the visitor - they simply get the defaults.
        return True

    st.session_state["people"] = [
        {k: p[k] for k in _PERSON_FIELDS if k in p} for p in people
    ]
    valid_ids = {p["id"] for p in people}
    for key, value in data.get("widgets", {}).items():
        person_id = key.rsplit("_", 1)[-1]
        if not person_id.isdigit() or int(person_id) not in valid_ids:
            continue
        if key.startswith("postcode_"):
            if not (isinstance(value, str) and value.isdigit() and len(value) == 4):
                continue
        if key.startswith("town_"):
            # The chosen town where one postcode spans several premium
            # regions - an entry from data/premium_regions.json.
            if not (isinstance(value, dict) and {"canton", "region", "town"} <= set(value)):
                continue
        if key.startswith("current_deductible_"):
            # One of the statutory deductibles; which ones fit the age class
            # is checked where the dropdown is drawn.
            if not (isinstance(value, int) and 0 <= value <= 2500):
                continue
        if key.startswith(("current_insurer_", "current_model_")):
            # Whether it is still on offer is checked where the dropdown is
            # drawn; here only that it is a plausible name.
            if not (isinstance(value, str) and 0 < len(value) <= 200):
                continue
        if key.startswith("models_"):
            if not isinstance(value, list):
                continue
            # A tariff category can disappear between visits - PHARM did. A
            # multiselect raises if its default is not among the options.
            value = [m for m in value if m in offered_tariff_types]
            if not value:
                continue
        st.session_state[key] = value
    return True


def _is_pristine(data: dict, offered_tariff_types: list[str]) -> bool:
    """True when nothing has been entered that is worth keeping.

    Without this, "Eingaben löschen" would delete the entry and the very next
    run would write the blank form straight back, leaving something behind
    after a button that promises nothing will be. A visitor who has typed
    nothing also gets nothing stored.
    """
    if data.get("language", FALLBACK) != FALLBACK:
        return False  # a chosen language is worth remembering on its own
    if data["people"] != [DEFAULT_PERSON]:
        return False
    person_id = DEFAULT_PERSON["id"]
    for key, value in data["widgets"].items():
        if key == f"postcode_{person_id}" and value == DEFAULT_POSTCODE:
            continue
        if key == f"models_{person_id}" and list(value) == list(offered_tariff_types):
            continue
        return False
    return True


def save(offered_tariff_types: list[str]) -> None:
    """Write the current entries to the browser. Call after the form is drawn."""
    data = _collect()
    if _is_pristine(data, offered_tariff_types):
        # Back to the defaults - typically German chosen again after English.
        # Writing nothing is not enough then: the earlier entry would still be
        # there, and the next visit would come back in English.
        if st.session_state.get(_HAS_STORED):
            st.session_state[_HAS_STORED] = False
            st.session_state[_PENDING] = None
            streamlit_js_eval(
                js_expressions=f"localStorage.removeItem('{STORAGE_KEY}')",
                key=f"clear_inputs_{st.session_state.get(_CLEARS, 0)}",
            )
            st.session_state[_CLEARS] = st.session_state.get(_CLEARS, 0) + 1
        return
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if st.session_state.get(_PENDING) == payload:
        return
    st.session_state[_PENDING] = payload
    st.session_state[_HAS_STORED] = True
    streamlit_js_eval(
        js_expressions=(
            f"localStorage.setItem('{STORAGE_KEY}', {json.dumps(payload)})"
        ),
        # Keyed on the payload, because the component evaluates once per key.
        key=f"save_inputs_{abs(hash(payload))}",
    )


def request_forget() -> None:
    """Note that the visitor wants their entries dropped.

    The erasing itself happens on the next run, in handle_forget(). It cannot
    happen here: st.rerun() ends the script immediately, and a component whose
    script never finished is never rendered, so its JavaScript never runs. The
    first version of this called removeItem and rerun together, and silently
    did nothing at all.
    """
    st.session_state[_FORGET] = True


def handle_forget() -> bool:
    """Erase browser storage and reset the form. Call before any widget.

    Returns True when this run is a forget run, in which case the caller must
    not call save() - it would immediately write the defaults back and the
    entry would never actually leave the browser.
    """
    if not st.session_state.pop(_FORGET, False):
        return False

    # Erase, then reload the page from the browser itself.
    #
    # Clearing session_state here is not enough and was tried first: Streamlit
    # keeps widget state outside session_state, so deleting the keys left the
    # form showing the old postcode and age, and the person list came back with
    # a stray third entry. A reload starts a genuinely new session, which then
    # reads the now-empty storage and falls back to the defaults.
    #
    # parent.window because the component runs inside its own iframe. A fresh
    # key every time, because the component evaluates once per key and somebody
    # may well press the button twice.
    run = st.session_state.get(_FORGET_RUN, 0) + 1
    st.session_state[_FORGET_RUN] = run
    streamlit_js_eval(
        js_expressions=(
            f"(function(){{ localStorage.removeItem('{STORAGE_KEY}'); "
            f"parent.window.location.reload(); }})()"
        ),
        key=f"forget_inputs_{run}",
    )
    return True
