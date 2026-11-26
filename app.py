"""
app.py - Streamlit front end for owner_statement.py

Run locally:   streamlit run app.py
All parsing, mapping and math lives in owner_statement.py; styling lives in
ui_theme.py. This file only handles upload, user choices, display and downloads.
"""

from __future__ import annotations

import difflib
import re
import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

import owner_statement as core
import ui_theme as ui
from usage import track

SAMPLE_FILE = Path(__file__).parent / "maple_ridge_oct2026_gl_export.csv"
WALKTHROUGH_URL = "https://www.youtube.com/watch?v=8pOCphcHSV8"
NEW_INCOME = "Income → (new category)"
NEW_EXPENSE = "Expense → (new category)"
DISTRIBUTION = "Owner distribution (not an expense)"
CONTRIBUTION = "Owner contribution (not income)"
CHOOSE = "Choose a category…"
SAME_LINE = "Category's usual line (default)"

st.set_page_config(page_title="Owner Statement Reformatter", page_icon="📄",
                   layout="centered", initial_sidebar_state="collapsed")
st.markdown(ui.css(), unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Session state: the working mapping lives here for the whole browser session.
# -----------------------------------------------------------------------------
if "mapping" not in st.session_state:
    st.session_state.mapping = dict(core.GL_MAPPING)
if "source" not in st.session_state:
    st.session_state.source = None          # (filename, bytes)
if "bot" in st.query_params:                              # keep-awake job: don't count its visits
    track = lambda *a, **k: None  # noqa: E731
if not st.session_state.get("_visit_tracked"):          # one anonymous "visit" per browser session
    st.session_state._visit_tracked = True
    track("visit")
if "results" not in st.session_state:
    st.session_state.results = None         # (summary_df, sched_e_df, totals)


def reset_results():
    st.session_state.results = None


# -----------------------------------------------------------------------------
# Hero + export instructions
# -----------------------------------------------------------------------------
st.markdown(ui.hero(), unsafe_allow_html=True)

with st.expander("▶ Watch how it works (3-minute walkthrough)"):
    st.video(WALKTHROUGH_URL)

with st.expander("How to export the right report"):
    t_af, t_bd, t_cols = st.tabs(["AppFolio", "Buildium", "Columns needed"])
    with t_af:
        st.markdown("Reports → open **Owner Statement** (or **General Ledger**) → filter to one "
                    "owner/property and one month, **cash basis** → *Export* → CSV or Excel.")
    with t_bd:
        st.markdown("Reports → **Owner statement** (or **General ledger**) → choose the "
                    "owner/property and date range → export to CSV or Excel.")
    with t_cols:
        st.markdown("**Date, GL Account, Description, Cash In, Cash Out** (or one signed "
                    "**Amount** column), ideally plus **Balance**, **Unit** and **Type**. "
                    "Title lines above the table are fine.")
    st.caption("Menu names differ between software versions, so pick the closest match. "
               "You can delete tenant names, addresses and account numbers before uploading.")


# -----------------------------------------------------------------------------
# Step 1: upload (+ optional saved mapping / statement details)
# -----------------------------------------------------------------------------
st.markdown(ui.step(1, "Upload your export", "CSV or Excel · one owner, one month"),
            unsafe_allow_html=True)
with st.container(border=True):
    upload = st.file_uploader("Owner statement or GL export", type=["csv", "xlsx", "xls"],
                              on_change=reset_results, label_visibility="collapsed")
    c_sample, c_hint = st.columns([1, 2], vertical_alignment="center")
    with c_sample:
        if SAMPLE_FILE.exists() and st.button("Try the sample file", width="stretch"):
            st.session_state.source = (SAMPLE_FILE.name, SAMPLE_FILE.read_bytes())
            reset_results()
            track("sample")
    with c_hint:
        st.caption("No export handy? The sample is a duplex for one month.")

    with st.expander("Saved mapping & statement details (optional)"):
        m_load, m_save = st.columns(2)
        with m_load:
            saved = st.file_uploader("Load a saved mapping (.json)", type=["json"],
                                     key="mapping_upload")
        if saved is not None:
            sig = hashlib.md5(saved.getvalue()).hexdigest()
            if st.session_state.get("loaded_mapping_sig") != sig:
                try:
                    st.session_state.mapping = core.mapping_from_json(
                        saved.getvalue().decode("utf-8"), base=core.GL_MAPPING)
                    st.session_state.loaded_mapping_sig = sig
                    reset_results()
                    track("mapping_loaded")
                    st.success("Mapping loaded.")
                except (ValueError, UnicodeDecodeError) as exc:
                    st.error(f"Couldn't read that mapping file: {exc}")
        with m_save:
            st.write("")
            st.download_button(
                "💾 Save my mapping for next time",
                data=core.mapping_to_json(st.session_state.mapping),
                file_name="owner_statement_mapping.json", mime="application/json",
                width="stretch",
                help="Download your account → category choices and load them next month.",
            )
        st.caption("Shown on the owner summary (not in the export):")
        d1, d2 = st.columns(2)
        prop_display = d1.text_input("Property name to show", placeholder="e.g. 123 Main St (Duplex)")
        occupancy = d2.text_input("Occupancy", placeholder="e.g. 2 of 2 units occupied")
        highlights = st.text_area("Highlights for the owner",
                                  placeholder="e.g. Furnace serviced; Unit B renewed")

if upload is not None:
    _sig = hashlib.md5(upload.getvalue()).hexdigest()
    if st.session_state.get("_upload_sig") != _sig:      # count each new file once
        st.session_state._upload_sig = _sig
        track("upload")
    st.session_state.source = (upload.name, upload.getvalue())

if st.session_state.source is None:
    st.markdown(ui.footer(), unsafe_allow_html=True)
    st.stop()

filename, data = st.session_state.source
try:
    parsed = core.read_export_bytes(data, filename)
except Exception as exc:  # noqa: BLE001 - show any parse failure to the user
    st.error(
        f"**Couldn't read `{filename}`.** {exc}\n\n"
        "Check that it's the owner statement or general ledger export and that it "
        "has Date, GL Account and Cash In/Cash Out (or Amount) columns."
    )
    st.stop()

tx = parsed.transactions


# -----------------------------------------------------------------------------
# Step 2: what was detected
# -----------------------------------------------------------------------------
st.markdown(ui.step(2, "Check what was detected"), unsafe_allow_html=True)
with st.container(border=True):
    st.markdown(f"**{filename}** · {len(tx)} transactions · "
                f"{tx['date'].min():%b %d} – {tx['date'].max():%b %d, %Y} · "
                f"opening balance **${parsed.opening_balance:,.2f}**")
    with st.expander("Columns used and first transactions"):
        st.dataframe(
            pd.DataFrame({"Used as": [c.replace("_", " ").title() for c in parsed.columns],
                          "Column in your file": list(parsed.columns.values())}),
            hide_index=True, width="stretch")
        preview = tx[["date", "unit", "type", "gl", "description", "cash_in", "cash_out"]].head(8).copy()
        preview["date"] = preview["date"].dt.strftime("%m/%d/%Y")
        preview.columns = ["Date", "Unit", "Type", "GL Account", "Description", "Cash In", "Cash Out"]
        st.dataframe(core.format_money_columns(preview), hide_index=True, width="stretch")


# -----------------------------------------------------------------------------
# Step 3: map any unknown GL accounts
# -----------------------------------------------------------------------------
mapping = st.session_state.mapping
unmapped = core.find_unmapped(tx, mapping)
st.markdown(ui.step(3, "Map your accounts",
                    "all mapped" if not unmapped else f"{len(unmapped)} to map"),
            unsafe_allow_html=True)


def category_options(mp: dict) -> tuple[list[str], dict]:
    """Dropdown labels for every existing category, plus 'new' and equity choices.
    Returns (labels, label -> default Schedule E line)."""
    seen: dict[str, list[int]] = {}
    for rule in mp.values():
        if rule.get("role") in ("income", "expense") and rule.get("summary"):
            label = f"{rule['role'].title()} → {rule['summary']}"
            seen.setdefault(label, []).append(int(rule["schedule_e"]))
    labels = sorted(seen, key=lambda s: (not s.startswith("Income"), s))
    default_line = {lbl: max(set(lines), key=lines.count) for lbl, lines in seen.items()}
    return labels + [NEW_INCOME, NEW_EXPENSE, DISTRIBUTION, CONTRIBUTION], default_line


_GENERIC_WORDS = {"income", "expense", "expenses", "fee", "fees", "other", "general", "and",
                  "services", "service", "misc", "miscellaneous", "the", "of"}


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 2} - _GENERIC_WORDS


def best_guess(gl: str, mp: dict) -> dict | None:
    """Suggest an existing mapping only when we're fairly sure.

    1. Shared meaningful words ("pest services" -> "pest control").
    2. Otherwise a close spelling match (cutoff 0.8, e.g. typos / plurals).
    Returns None when unsure, so the user must choose (never a silent wrong guess)."""
    key = core.normalize_gl(gl)
    words = _words(key)
    scored = [(len(words & _words(k)), k) for k, r in mp.items() if r.get("summary")]
    scored = [s for s in scored if s[0] > 0]
    if scored:
        best = max(scored, key=lambda s: s[0])
        if sum(1 for s in scored if s[0] == best[0]) == 1:      # unambiguous winner only
            return mp[best[1]]
    match = difflib.get_close_matches(key, [k for k, r in mp.items() if r.get("summary")],
                                      n=1, cutoff=0.8)
    return mp[match[0]] if match else None


with st.container(border=True):
    if not unmapped:
        st.success("All GL accounts in this export are mapped.")
    else:
        st.warning(f"{len(unmapped)} account(s) aren't mapped yet. Choose where each one goes; "
                   "you only do this once.")
        labels, default_line = category_options(mapping)
        labels = [CHOOSE] + labels
        line_numbers = list(core.SCHEDULE_E_LINES)
        line_labels = [SAME_LINE] + [f"{n} – {name}" for n, name in core.SCHEDULE_E_LINES.items()]

        with st.form("map_accounts", border=False):
            choices = []
            for gl in unmapped:
                k = hashlib.md5(gl.encode()).hexdigest()[:8]
                rows = tx["gl"] == gl
                amount = core.dsum((tx.loc[rows, "cash_in"] - tx.loc[rows, "cash_out"]).abs())
                st.markdown(f"**{gl}** · {int(rows.sum())} transaction(s), ${amount:,.2f}")
                guess = best_guess(gl, mapping)
                guess_label = (f"{guess['role'].title()} → {guess['summary']}"
                               if guess and guess.get("summary") else CHOOSE)
                if guess_label != CHOOSE:
                    st.caption(f"Suggestion (from a similar account name): **{guess_label}**. "
                               "Pick it below if it's right.")
                a, b, c = st.columns(3)
                # Always start at "Choose…": a wrong pre-selected guess could silently
                # put an expense into income, so the user confirms every new account.
                cat = a.selectbox("Statement category", labels, index=0, key=f"cat_{k}")
                new_name = b.text_input("New category name (if new)", key=f"new_{k}")
                line = c.selectbox("Schedule E line", line_labels, index=0, key=f"line_{k}",
                                   help="Leave as default to use the category's usual line.")
                line_no = None if line == SAME_LINE else line_numbers[line_labels.index(line) - 1]
                choices.append((gl, cat, new_name.strip(), line_no))
                st.divider()
            submitted = st.form_submit_button("Save these mappings", type="primary")

        if submitted:
            errors, pending = [], {}
            for gl, cat, new_name, line_no in choices:
                key = core.normalize_gl(gl)
                if cat == CHOOSE:
                    errors.append(f"Choose a category for **{gl}**.")
                elif cat == DISTRIBUTION:
                    pending[key] = {"role": "distribution"}
                elif cat == CONTRIBUTION:
                    pending[key] = {"role": "contribution"}
                else:
                    role = "income" if cat.startswith("Income") else "expense"
                    is_new = cat in (NEW_INCOME, NEW_EXPENSE)
                    summary = new_name if is_new else cat.split("→", 1)[1].strip()
                    line_final = line_no or (3 if role == "income" and is_new else default_line.get(cat))
                    if not summary:
                        errors.append(f"Enter a new category name for **{gl}**.")
                    elif not line_final:
                        errors.append(f"Choose a Schedule E line for **{gl}** (new category).")
                    else:
                        pending[key] = {"role": role, "summary": summary,
                                        "schedule_e": int(line_final),
                                        "note_label": key.split(":")[-1]}
            if not errors:
                mapping.update(pending)   # only apply when every row is valid
            if errors:
                for e in errors:
                    st.error(e)
            else:
                st.session_state.mapping = mapping
                reset_results()
                track("mapping_saved")
                st.rerun()


# -----------------------------------------------------------------------------
# Step 4: generate
# -----------------------------------------------------------------------------
st.markdown(ui.step(4, "Generate statements"), unsafe_allow_html=True)
profile = core.load_profile(None)
profile.update({k: v for k, v in {"property_display": prop_display, "occupancy": occupancy,
                                  "highlights": highlights}.items() if v.strip()})

with st.container(border=True):
    if st.button("Generate owner statements", type="primary", disabled=bool(unmapped),
                 width="stretch"):
        try:
            st.session_state.results = core.build_outputs(parsed, st.session_state.mapping, profile)
            track("generate_ok")
        except core.ValidationError as exc:
            track("generate_fail")
            st.session_state.results = None
            st.error("**This export doesn't tie out, so no statement was produced.**")
            for p in exc.problems:
                st.markdown(f"- {p}")
            st.caption("Usually this means rows were deleted or edited after export, or the file "
                       "covers more than one owner. Re-export the report unchanged and try again.")
        except KeyError as exc:
            st.session_state.results = None
            st.error(f"Some accounts still need mapping: {exc}")
        except ValueError as exc:
            st.session_state.results = None
            st.error(f"Couldn't build the statements: {exc}")

    if unmapped:
        st.caption("Map the accounts above first.")

    if st.session_state.results:
        summary, sched_e, totals = st.session_state.results
        st.markdown(ui.tiles([
            ("Total income", f"${totals.income:,.2f}"),
            ("Total expenses", f"${totals.expenses:,.2f}"),
            ("Owner distribution", f"${totals.distributions:,.2f}"),
            ("Ending balance", f"${totals.computed_ending:,.2f}"),
        ]) + ui.ok_banner("Ties out: opening + income − expenses − distributions = ending "
                          "balance, and every running balance matches your export."),
            unsafe_allow_html=True)
        st.write("")

        stem = Path(filename).stem
        tab1, tab2 = st.tabs(["Owner summary", "Schedule E (CPA)"])
        with tab1:
            st.dataframe(core.format_money_columns(summary), hide_index=True,
                         width="stretch")
            st.download_button("⬇️ Download owner summary (CSV)", core.to_csv_bytes(summary),
                               file_name=f"{stem}_owner_summary.csv", mime="text/csv", on_click=track, args=("download",))
        with tab2:
            st.dataframe(core.format_money_columns(sched_e), hide_index=True,
                         width="stretch")
            st.download_button("⬇️ Download Schedule E (CSV)", core.to_csv_bytes(sched_e),
                               file_name=f"{stem}_schedule_e.csv", mime="text/csv", on_click=track, args=("download",))

st.markdown(ui.footer(), unsafe_allow_html=True)
