"""
app.py - Streamlit front end for owner_statement.py

Run locally:   streamlit run app.py
All parsing, mapping and math lives in owner_statement.py; this file only
handles upload, user choices, display and downloads.
"""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

import owner_statement as core

SAMPLE_FILE = Path(__file__).parent / "maple_ridge_oct2026_gl_export.csv"
NEW_INCOME = "Income → (new category)"
NEW_EXPENSE = "Expense → (new category)"
DISTRIBUTION = "Owner distribution (not an expense)"
CONTRIBUTION = "Owner contribution (not income)"

st.set_page_config(page_title="Owner Statement Reformatter", page_icon="📄", layout="wide")


# -----------------------------------------------------------------------------
# Session state: the working mapping lives here for the whole browser session.
# -----------------------------------------------------------------------------
if "mapping" not in st.session_state:
    st.session_state.mapping = dict(core.GL_MAPPING)
if "source" not in st.session_state:
    st.session_state.source = None          # (filename, bytes)
if "results" not in st.session_state:
    st.session_state.results = None         # (summary_df, sched_e_df, totals)


def reset_results():
    st.session_state.results = None


# -----------------------------------------------------------------------------
# Header + export instructions
# -----------------------------------------------------------------------------
st.title("Free AppFolio/Buildium owner statement reformatter")
st.write(
    "Upload one month's owner statement / general ledger export and get back a clean "
    "one-page owner summary plus a CPA-friendly Schedule E breakdown. "
    "Every total is checked to the penny against your export's running balance."
)

with st.expander("How to export the right report", expanded=False):
    st.markdown(
        """
**AppFolio**: Reports → open **Owner Statement** (or **General Ledger**) → filter to one
owner/property and one month, **cash basis** → *Export* → CSV or Excel.

**Buildium**: Reports → **Owner statement** (or **General ledger**) → choose the owner/property
and date range → export to CSV or Excel.

The tool needs these columns (names can vary slightly): **Date, GL Account, Description,
Cash In, Cash Out** (or one signed **Amount** column), and ideally **Balance**, **Unit** and **Type**.
Title lines above the table are fine; it finds the header itself.
Menu names differ between software versions, so pick the closest match.

**Privacy:** before uploading, you can delete tenant names, account numbers and addresses.
Files are processed in memory for this session only and are not saved.
"""
    )


# -----------------------------------------------------------------------------
# Sidebar: saved mapping + optional statement details
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("Your saved mapping")
    saved = st.file_uploader("Load a mapping you saved last time (.json)", type=["json"],
                             key="mapping_upload")
    if saved is not None:
        sig = hashlib.md5(saved.getvalue()).hexdigest()
        if st.session_state.get("loaded_mapping_sig") != sig:
            try:
                st.session_state.mapping = core.mapping_from_json(
                    saved.getvalue().decode("utf-8"), base=core.GL_MAPPING)
                st.session_state.loaded_mapping_sig = sig
                reset_results()
                st.success("Mapping loaded.")
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(f"Couldn't read that mapping file: {exc}")

    st.download_button(
        "💾 Save my mapping for next time",
        data=core.mapping_to_json(st.session_state.mapping),
        file_name="owner_statement_mapping.json",
        mime="application/json",
        help="Download your account → category choices. Load this file next month "
             "and you won't have to map the same accounts again.",
    )

    st.header("Statement details (optional)")
    st.caption("Shown on the owner summary. Not in the export, so add them here.")
    prop_display = st.text_input("Property name to show", placeholder="123 Main St (Duplex)")
    occupancy = st.text_input("Occupancy", placeholder="2 of 2 units occupied")
    highlights = st.text_area("Highlights for the owner", placeholder="Furnace serviced; Unit B renewed")


# -----------------------------------------------------------------------------
# Step 1: upload
# -----------------------------------------------------------------------------
st.subheader("1. Upload your export")
col_up, col_sample = st.columns([3, 1])
with col_up:
    upload = st.file_uploader("CSV or Excel export", type=["csv", "xlsx", "xls"],
                              on_change=reset_results)
with col_sample:
    st.write("")
    st.write("")
    if SAMPLE_FILE.exists() and st.button("Try the sample file"):
        st.session_state.source = (SAMPLE_FILE.name, SAMPLE_FILE.read_bytes())
        reset_results()

if upload is not None:
    st.session_state.source = (upload.name, upload.getvalue())

if st.session_state.source is None:
    st.info("Upload an export, or click **Try the sample file** to see how it works.")
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
st.success(f"Read **{filename}**: {len(tx)} transactions, "
           f"{tx['date'].min():%b %d} – {tx['date'].max():%b %d, %Y}, "
           f"opening balance ${parsed.opening_balance:,.2f}.")


# -----------------------------------------------------------------------------
# Step 2: preview detected columns
# -----------------------------------------------------------------------------
st.subheader("2. Check what was detected")
c1, c2 = st.columns([1, 2])
with c1:
    st.caption("Columns found")
    st.dataframe(
        pd.DataFrame({"Used as": [c.replace("_", " ").title() for c in parsed.columns],
                      "Column in your file": list(parsed.columns.values())}),
        hide_index=True, width="stretch")
    if parsed.meta:
        st.caption("Report info")
        st.dataframe(pd.DataFrame({"Item": list(parsed.meta), "Value": list(parsed.meta.values())}),
                     hide_index=True, width="stretch")
with c2:
    st.caption("First transactions")
    preview = tx[["date", "unit", "type", "gl", "description", "cash_in", "cash_out"]].head(8).copy()
    preview["date"] = preview["date"].dt.strftime("%m/%d/%Y")
    preview.columns = ["Date", "Unit", "Type", "GL Account", "Description", "Cash In", "Cash Out"]
    st.dataframe(core.format_money_columns(preview), hide_index=True, width="stretch")


# -----------------------------------------------------------------------------
# Step 3: map any unknown GL accounts
# -----------------------------------------------------------------------------
st.subheader("3. Map your accounts")
mapping = st.session_state.mapping
unmapped = core.find_unmapped(tx, mapping)


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


def best_guess(gl: str, mp: dict) -> dict | None:
    """Closest existing mapping entry by name (pure string similarity)."""
    key = core.normalize_gl(gl)
    match = difflib.get_close_matches(key, list(mp), n=1, cutoff=0.5)
    return mp[match[0]] if match else None


if not unmapped:
    st.success("All GL accounts in this export are mapped.")
else:
    st.warning(f"{len(unmapped)} account(s) in this export aren't mapped yet. "
               "Choose where each one goes; this only needs doing once.")
    labels, default_line = category_options(mapping)
    line_labels = [f"{n} – {name}" for n, name in core.SCHEDULE_E_LINES.items()]
    line_numbers = list(core.SCHEDULE_E_LINES)

    with st.form("map_accounts"):
        choices = []
        for gl in unmapped:
            k = hashlib.md5(gl.encode()).hexdigest()[:8]
            amount = core.dsum((tx.loc[tx["gl"] == gl, "cash_in"] - tx.loc[tx["gl"] == gl, "cash_out"]).abs())
            st.markdown(f"**{gl}**  ·  {int((tx['gl'] == gl).sum())} transaction(s), ${amount:,.2f}")
            guess = best_guess(gl, mapping)
            guess_label = (f"{guess['role'].title()} → {guess['summary']}"
                           if guess and guess.get("summary") else NEW_EXPENSE)
            a, b, c = st.columns([2, 2, 2])
            cat = a.selectbox("Statement category", labels,
                              index=labels.index(guess_label) if guess_label in labels else 0,
                              key=f"cat_{k}")
            new_name = b.text_input("New category name (if new)", key=f"new_{k}")
            dflt = (guess or {}).get("schedule_e") or default_line.get(cat, 19)
            line = c.selectbox("Schedule E line", line_labels,
                               index=line_numbers.index(dflt) if dflt in line_numbers else len(line_numbers) - 1,
                               key=f"line_{k}")
            choices.append((gl, cat, new_name.strip(), line_numbers[line_labels.index(line)]))
            st.divider()
        submitted = st.form_submit_button("Save these mappings", type="primary")

    if submitted:
        errors = []
        for gl, cat, new_name, line in choices:
            key = core.normalize_gl(gl)
            if cat == DISTRIBUTION:
                mapping[key] = {"role": "distribution"}
            elif cat == CONTRIBUTION:
                mapping[key] = {"role": "contribution"}
            else:
                role = "income" if cat.startswith("Income") else "expense"
                summary = new_name if cat in (NEW_INCOME, NEW_EXPENSE) else cat.split("→", 1)[1].strip()
                if not summary:
                    errors.append(f"Enter a new category name for **{gl}**.")
                    continue
                mapping[key] = {"role": role, "summary": summary, "schedule_e": int(line),
                                "note_label": key.split(":")[-1]}
        if errors:
            for e in errors:
                st.error(e)
        else:
            st.session_state.mapping = mapping
            reset_results()
            st.rerun()


# -----------------------------------------------------------------------------
# Step 4: generate
# -----------------------------------------------------------------------------
st.subheader("4. Generate statements")
profile = core.load_profile(None)
profile.update({k: v for k, v in {"property_display": prop_display, "occupancy": occupancy,
                                  "highlights": highlights}.items() if v.strip()})

if st.button("Generate owner statements", type="primary", disabled=bool(unmapped)):
    try:
        st.session_state.results = core.build_outputs(parsed, st.session_state.mapping, profile)
    except core.ValidationError as exc:
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
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total income", f"${totals.income:,.2f}")
    m2.metric("Total expenses", f"${totals.expenses:,.2f}")
    m3.metric("Owner distribution", f"${totals.distributions:,.2f}")
    m4.metric("Ending balance", f"${totals.computed_ending:,.2f}")
    st.success("✅ Ties out: opening + income − expenses − distributions = ending balance, "
               "and every running balance matches your export.")

    stem = Path(filename).stem
    tab1, tab2 = st.tabs(["Owner summary", "Schedule E (CPA)"])
    with tab1:
        st.dataframe(core.format_money_columns(summary), hide_index=True, width="stretch")
        st.download_button("⬇️ Download owner summary (CSV)", core.to_csv_bytes(summary),
                           file_name=f"{stem}_owner_summary.csv", mime="text/csv")
    with tab2:
        st.dataframe(core.format_money_columns(sched_e), hide_index=True, width="stretch")
        st.download_button("⬇️ Download Schedule E (CSV)", core.to_csv_bytes(sched_e),
                           file_name=f"{stem}_schedule_e.csv", mime="text/csv")
    st.caption("Schedule E line choices are a starting point. Confirm categories with the owner's CPA.")
