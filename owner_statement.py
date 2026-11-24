"""
owner_statement.py
------------------
Turn an AppFolio / Buildium style "owner statement - GL detail (cash basis)"
CSV export into:
    1. a simple one-page owner summary
    2. a CPA / Schedule E style summary

Design rules
    * All money math uses decimal.Decimal (never floats) so totals tie to the penny.
    * Nothing is silently dropped: any GL account that is not in the mapping
      raises an error listing exactly which accounts need mapping.
    * The GL -> category mapping is a plain dict (GL_MAPPING) that can be edited
      here or loaded from a JSON file (see load_mapping()).

Usage
    python owner_statement.py export.csv [--mapping mapping.json]
                              [--profile profile.json] [--outdir out/]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


# =============================================================================
# 1. CONFIGURATION
# =============================================================================

# GL account -> statement category mapping.
#
# Keys are *normalized* GL names: lowercase, account code removed, extra
# separators collapsed (see normalize_gl()). So "4100 Rent Income",
# "Rent Income" and "4100 - Rent Income" all match the key "rent income".
# Nested names keep their parent ("other income:pet rent"); if the full
# nested name isn't mapped, the leaf ("pet rent") is tried next.
#
# Fields:
#   role        income | expense | distribution | contribution | ignore
#   summary     line item on the simple owner summary
#   schedule_e  Schedule E line number (int)
#   note_label  short label used when building breakdown notes
#   note_by_unit  True -> breakdown note splits this account by unit
#
# The ORDER of entries matters: it controls the order of components inside
# each note (e.g. "Water/sewer $286.55 + electric $48.17 + trash $64.25").
GL_MAPPING: dict[str, dict] = {
    # ---- income ------------------------------------------------------------
    "rent income":            {"role": "income", "summary": "Rent", "schedule_e": 3,
                               "note_label": "rent", "note_by_unit": True},
    "other income:pet rent":  {"role": "income", "summary": "Other Income", "schedule_e": 3,
                               "note_label": "pet rent"},
    "late fee income":        {"role": "income", "summary": "Other Income", "schedule_e": 3,
                               "note_label": "late fee"},
    "utility reimbursement":  {"role": "income", "summary": "Other Income", "schedule_e": 3,
                               "note_label": "water billback"},
    # ---- expenses ----------------------------------------------------------
    "repairs - plumbing":     {"role": "expense", "summary": "Repairs & Maintenance", "schedule_e": 14,
                               "note_label": "plumbing"},
    "repairs & maintenance:hvac": {"role": "expense", "summary": "Repairs & Maintenance", "schedule_e": 7,
                               "note_label": "HVAC"},
    "repairs":                {"role": "expense", "summary": "Repairs & Maintenance", "schedule_e": 15,
                               "note_label": "general repairs/supplies"},
    "utilities:water/sewer":  {"role": "expense", "summary": "Utilities", "schedule_e": 17,
                               "note_label": "water/sewer"},
    "electric":               {"role": "expense", "summary": "Utilities", "schedule_e": 17,
                               "note_label": "electric"},
    "trash removal":          {"role": "expense", "summary": "Utilities", "schedule_e": 17,
                               "note_label": "trash"},
    "landscaping/snow removal": {"role": "expense", "summary": "Landscaping & Pest Control", "schedule_e": 7,
                               "note_label": "lawn/leaf"},
    "pest control":           {"role": "expense", "summary": "Landscaping & Pest Control", "schedule_e": 7,
                               "note_label": "pest"},
    "management fees":        {"role": "expense", "summary": "Management Fees", "schedule_e": 11,
                               "note_label": "management fee"},
    "maint coordination fee": {"role": "expense", "summary": "Management Fees", "schedule_e": 11,
                               "note_label": "maintenance coordination"},
    "licenses & permits":     {"role": "expense", "summary": "Licenses & Permits", "schedule_e": 19,
                               "note_label": "licenses & permits"},
    # ---- equity (not income / expense) ------------------------------------
    "owner distributions":    {"role": "distribution"},
    "owner contributions":    {"role": "contribution"},
}

# Order of line items on the owner summary. Categories that are mapped but
# missing here are appended at the end of their section automatically.
SUMMARY_INCOME_ORDER = ["Rent", "Other Income"]
SUMMARY_EXPENSE_ORDER = ["Repairs & Maintenance", "Utilities", "Landscaping & Pest Control",
                         "Management Fees", "Licenses & Permits"]

# Schedule E (Form 1040) Part I expense lines. Check against the current
# year's form before relying on the line numbers.
SCHEDULE_E_LINES = {
    3: "Rents received", 5: "Advertising", 6: "Auto and travel",
    7: "Cleaning and maintenance", 8: "Commissions", 9: "Insurance",
    10: "Legal and other professional fees", 11: "Management fees",
    12: "Mortgage interest paid to banks", 13: "Other interest", 14: "Repairs",
    15: "Supplies", 16: "Taxes", 17: "Utilities",
    18: "Depreciation expense or depletion", 19: "Other",
}

# Per-owner presentation details that are NOT in the export. Load from JSON
# per owner (see load_profile()). Everything here is optional.
DEFAULT_PROFILE: dict = {
    "owner": None,              # falls back to "Owner:" line in the export
    "property_display": None,   # falls back to the Property column
    "occupancy": None,
    "reserve_label": "Operating reserve",
    "highlights": None,
    "summary_notes": {},        # {"Licenses & Permits": "City rental registration renewal"}
    "schedule_e_notes": {
        3: "Utility billbacks and late fees included as rental income",
        9: "Paid directly by owner - not on PM ledger",
        12: "From owner's Form 1098 - not on PM ledger",
        16: "Property tax paid by owner/escrow - not on PM ledger",
        18: "CPA calculates",
    },
}

# Column-name aliases (normalized: lowercase, punctuation removed).
COLUMN_ALIASES = {
    "date":        ["date", "trans date", "transaction date", "post date", "posted"],
    "property":    ["property", "property name", "building"],
    "unit":        ["unit", "unit number", "unit name"],
    "payee":       ["payee payer", "payee", "payer", "name", "vendor tenant"],
    "type":        ["type", "transaction type", "txn type"],
    "reference":   ["reference", "ref", "ref no", "check no", "reference number"],
    "gl":          ["gl account", "account", "gl account name", "account name", "gl"],
    "description": ["description", "memo", "remarks", "details"],
    "cash_in":     ["cash in", "cashin", "receipts", "income", "deposit", "money in"],
    "cash_out":    ["cash out", "cashout", "payments", "expense", "withdrawal", "money out"],
    "amount":      ["amount", "net amount"],   # signed alternative to in/out
    "balance":     ["balance", "running balance", "cash balance"],
}


# =============================================================================
# 2. SMALL HELPERS
# =============================================================================

def norm_header(text: str) -> str:
    """'Payee / Payer ' -> 'payee payer'."""
    text = re.sub(r"[^a-z0-9 ]+", " ", str(text).lower())
    return re.sub(r"\s+", " ", text).strip()


_GL_CODE = re.compile(r"^\s*\d{3,6}(\.\d+)?\s*[-–:]?\s*")


def normalize_gl(raw: str) -> str:
    """'4105 - Late Fee Income' -> 'late fee income'; keeps ':' nesting."""
    s = _GL_CODE.sub("", str(raw or ""))
    s = re.sub(r"\s*:\s*", ":", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def parse_money(value) -> Decimal:
    """'1,450.00' / '$1,450.00' / '(48.17)' / '-48.17' / '' -> Decimal."""
    if value is None:
        return ZERO
    s = str(value).strip()
    if s in ("", "-", "nan", "None"):
        return ZERO
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "").strip()
    if s.endswith("-"):                       # trailing minus, e.g. '48.17-'
        negative, s = True, s[:-1]
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse amount: {value!r}") from exc
    d = -d if negative else d
    return d.quantize(CENT)


def dsum(values) -> Decimal:
    """Sum Decimals; returns 0.00 for an empty series."""
    return sum(values, ZERO).quantize(CENT)


def fmt_amount(d: Decimal | None) -> str:
    """Amount column format: 2,845.00"""
    return "" if d is None else f"{d:,.2f}"


def fmt_note(d: Decimal) -> str:
    """Note format: $2845.00 (no thousands separator, matches sample files)."""
    return f"${d:.2f}"


def cap_first(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


_WO = re.compile(r"WO\s*#?\s*(\d+)", re.I)


def work_orders(descriptions) -> list[str]:
    found = []
    for d in descriptions:
        for m in _WO.findall(str(d)):
            if f"WO #{m}" not in found:
                found.append(f"WO #{m}")
    return found


# =============================================================================
# 3. READING THE EXPORT
# =============================================================================

@dataclass
class ParsedExport:
    meta: dict                 # key/value lines above the header ("Owner": ...)
    transactions: pd.DataFrame # real transactions only (incl. distributions)
    opening_balance: Decimal
    ending_balance: Decimal | None      # from 'Ending ... Balance' footer, if present
    report_totals: tuple | None         # (cash_in, cash_out) from 'Total' footer
    columns: dict = field(default_factory=dict)  # canonical -> original header


def _match_columns(header_cells: list[str]) -> dict:
    """Map canonical column names to their index in the header row."""
    found = {}
    normed = [norm_header(c) for c in header_cells]
    for canon, aliases in COLUMN_ALIASES.items():
        for i, cell in enumerate(normed):
            if cell in aliases and canon not in found:
                found[canon] = i
                break
    return found


def find_header_row(rows: list[list[str]], max_scan: int = 60) -> int:
    """Return the index of the first row that looks like the real header:
    it must contain a date column, a GL/account column and either
    Cash In + Cash Out or a single Amount column."""
    for i, row in enumerate(rows[:max_scan]):
        cols = _match_columns(row)
        has_money = ("cash_in" in cols and "cash_out" in cols) or "amount" in cols
        if "date" in cols and "gl" in cols and has_money:
            return i
    raise ValueError("Could not find a header row with Date, GL Account and "
                     "Cash In/Cash Out (or Amount) columns in the first "
                     f"{max_scan} lines.")


def read_export(path: str | Path) -> ParsedExport:
    """Read an export from disk (.csv, .xlsx or .xls)."""
    p = Path(path)
    return read_export_bytes(p.read_bytes(), p.name)


def read_export_bytes(data: bytes, filename: str = "export.csv") -> ParsedExport:
    """Read an export from raw bytes (e.g. a web upload). CSV or Excel."""
    if filename.lower().endswith((".xlsx", ".xls")):
        import io
        sheet = pd.read_excel(io.BytesIO(data), header=None, dtype=str).fillna("")
        rows = [[str(c).strip() for c in r] for r in sheet.values.tolist()]
    else:
        import io
        text = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text, newline="")))
    return read_export_rows(rows)


def read_export_rows(rows: list[list[str]]) -> ParsedExport:
    """Core parser: takes raw rows (title lines included) and finds the header."""
    rows = [[str(c) for c in r] for r in rows]
    h = find_header_row(rows)
    header = rows[h]
    colidx = _match_columns(header)

    # --- metadata from the junk title lines ("Owner: Dana & Marcus ...") ----
    meta = {}
    for r in rows[:h]:
        line = ",".join(c for c in r if c).strip()
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
        elif line:
            meta.setdefault("title", line)

    # --- build a DataFrame with canonical column names ----------------------
    width = len(header)
    body = [(r + [""] * width)[:width] for r in rows[h + 1:] if any(c.strip() for c in r)]
    df = pd.DataFrame(body, columns=header)
    df = df.rename(columns={header[i]: canon for canon, i in colidx.items()})
    for canon in COLUMN_ALIASES:
        if canon not in df.columns:
            df[canon] = ""
    for c in ("date", "property", "unit", "payee", "type", "reference", "gl", "description"):
        df[c] = df[c].astype(str).str.strip()

    # --- money columns -------------------------------------------------------
    if colidx.get("cash_in") is not None:
        df["cash_in"] = df["cash_in"].map(parse_money)
        df["cash_out"] = df["cash_out"].map(parse_money)
    else:  # single signed Amount column: positive = in, negative = out
        amt = df["amount"].map(parse_money)
        df["cash_in"] = amt.map(lambda d: d if d > 0 else ZERO)
        df["cash_out"] = amt.map(lambda d: -d if d < 0 else ZERO)
    df["balance"] = df["balance"].map(lambda v: parse_money(v) if str(v).strip() else None)

    # --- split special rows from real transactions --------------------------
    text = (df["type"] + " " + df["description"]).str.lower()
    is_opening = text.str.contains("beginning balance|beginning cash balance|opening balance")
    is_footer = df["date"].eq("") | text.str.contains(r"^\s*total\b|ending (?:cash )?balance")

    opening = dsum(df.loc[is_opening, "balance"].dropna()) if is_opening.any() else ZERO

    ending, totals = None, None
    for _, r in df[is_footer].iterrows():
        d = r["description"].lower() + " " + r["type"].lower()
        if "ending" in d and r["balance"] is not None:
            ending = r["balance"]
        elif "total" in d:
            totals = (r["cash_in"], r["cash_out"])

    tx = df[~is_opening & ~is_footer].copy()
    tx["date"] = pd.to_datetime(tx["date"], errors="raise")
    tx = tx.reset_index(drop=True)

    columns = {canon: header[i] for canon, i in colidx.items()}  # canonical -> original name
    return ParsedExport(meta, tx, opening, ending, totals, columns)


# =============================================================================
# 4. MAPPING
# =============================================================================

def load_mapping(path: str | Path | None) -> dict:
    """Load a JSON mapping {normalized_gl: {...}}; keys are re-normalized so
    users can paste raw GL names like '4100 Rent Income' as keys."""
    if not path:
        return dict(GL_MAPPING)
    return mapping_from_json(Path(path).read_text(encoding="utf-8"))


VALID_ROLES = {"income", "expense", "distribution", "contribution"}


def mapping_from_json(text: str, base: dict | None = None) -> dict:
    """Parse a saved mapping JSON. If `base` is given, the saved entries are
    layered on top of it (saved file wins). Raises ValueError on bad input."""
    raw = json.loads(text)
    if isinstance(raw, dict) and "mapping" in raw:   # file written by mapping_to_json
        raw = raw["mapping"]
    if not isinstance(raw, dict):
        raise ValueError("Mapping file must be a JSON object of GL account -> rule.")
    merged = dict(base or {})
    for k, v in raw.items():
        if not isinstance(v, dict) or v.get("role") not in VALID_ROLES:
            raise ValueError(f"Bad mapping entry for {k!r}: needs a 'role' in {sorted(VALID_ROLES)}.")
        if v["role"] in ("income", "expense") and not (v.get("summary") and v.get("schedule_e")):
            raise ValueError(f"Mapping entry {k!r} needs 'summary' and 'schedule_e'.")
        merged[normalize_gl(k)] = v
    return merged


def mapping_to_json(mapping: dict) -> str:
    """Serialize a mapping so it can be downloaded and re-loaded next month."""
    return json.dumps({"version": 1, "mapping": mapping}, indent=2)


def find_unmapped(tx: pd.DataFrame, mapping: dict) -> list[str]:
    """Raw GL names in the export that the mapping does not cover."""
    missing = []
    for gl, typ in zip(tx["gl"], tx["type"]):
        key = normalize_gl(gl)
        if key in mapping or key.split(":")[-1] in mapping:
            continue
        if re.search("owner (distribution|contribution)", typ, re.I):
            continue
        if gl not in missing:
            missing.append(gl)
    return missing


def load_profile(path: str | Path | None) -> dict:
    prof = json.loads(json.dumps(DEFAULT_PROFILE))  # deep copy
    prof["schedule_e_notes"] = {int(k): v for k, v in prof["schedule_e_notes"].items()}
    if path:
        user = json.loads(Path(path).read_text(encoding="utf-8"))
        if "schedule_e_notes" in user:
            user["schedule_e_notes"] = {int(k): v for k, v in user["schedule_e_notes"].items()}
            prof["schedule_e_notes"].update(user.pop("schedule_e_notes"))
        prof.update(user)
    return prof


def apply_mapping(tx: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Attach role / summary / schedule_e / net amount to each transaction.
    Raises if any GL account is unmapped (never guess with money)."""
    tx = tx.copy()
    tx["gl_key"] = tx["gl"].map(normalize_gl)

    def lookup(row) -> tuple[str, dict | None]:
        """Return (mapping key used, rule). Full nested name first, then leaf."""
        key = row["gl_key"]
        for candidate in (key, key.split(":")[-1]):
            if candidate in mapping:
                return candidate, mapping[candidate]
        # Safety net: equity rows identified by Type even if GL isn't mapped.
        t = row["type"].lower()
        if "owner distribution" in t:
            return key, {"role": "distribution"}
        if "owner contribution" in t:
            return key, {"role": "contribution"}
        return key, None

    found = tx.apply(lookup, axis=1)
    rules = found.map(lambda kr: kr[1])
    unmapped = sorted(set(tx.loc[rules.isna(), "gl"]))
    if unmapped:
        raise KeyError("Unmapped GL accounts (add them to the mapping): "
                       + "; ".join(repr(u) for u in unmapped))

    tx["rule_key"] = found.map(lambda kr: kr[0])
    tx["role"] = rules.map(lambda r: r["role"])
    tx["summary"] = rules.map(lambda r: r.get("summary"))
    tx["schedule_e"] = rules.map(lambda r: r.get("schedule_e"))
    tx["note_label"] = rules.map(lambda r: r.get("note_label", ""))
    tx["note_by_unit"] = rules.map(lambda r: bool(r.get("note_by_unit")))
    tx["mapping_order"] = tx["rule_key"].map(lambda k: list(mapping).index(k) if k in mapping else 999)

    # Net amount in the account's natural direction. Refunds/reversals net out:
    #   income  = cash in  - cash out
    #   expense / distribution = cash out - cash in
    #   contribution = cash in - cash out
    def net(row):
        if row["role"] in ("income", "contribution"):
            return row["cash_in"] - row["cash_out"]
        if row["role"] in ("expense", "distribution"):
            return row["cash_out"] - row["cash_in"]
        return ZERO
    tx["net"] = tx.apply(net, axis=1)
    return tx


# =============================================================================
# 5. TOTALS + VALIDATION
# =============================================================================

@dataclass
class Totals:
    opening: Decimal
    income: Decimal
    expenses: Decimal
    distributions: Decimal
    contributions: Decimal

    @property
    def net_operating(self) -> Decimal:
        return self.income - self.expenses

    @property
    def computed_ending(self) -> Decimal:
        return (self.opening + self.income - self.expenses
                - self.distributions + self.contributions)


def compute_totals(parsed: ParsedExport, tx: pd.DataFrame) -> Totals:
    by_role = lambda r: dsum(tx.loc[tx["role"] == r, "net"])
    return Totals(parsed.opening_balance, by_role("income"), by_role("expense"),
                  by_role("distribution"), by_role("contribution"))


def validate(parsed: ParsedExport, tx: pd.DataFrame, totals: Totals) -> list[str]:
    """Return a list of problems (empty list = everything ties out).

    Checks:
      1. opening + income - expenses - distributions + contributions == ending
      2. every running Balance in the export matches our recomputed balance
      3. export's own 'Total' row matches the summed Cash In / Cash Out
    """
    problems = []

    # 1. Core identity
    ending = parsed.ending_balance
    if ending is None:
        last = tx["balance"].dropna()
        ending = last.iloc[-1] if len(last) else None
    if ending is None:
        problems.append("No ending balance found in export; cannot verify cash identity.")
    elif totals.computed_ending != ending:
        problems.append(
            f"Cash identity fails: opening {totals.opening} + income {totals.income} "
            f"- expenses {totals.expenses} - distributions {totals.distributions} "
            f"+ contributions {totals.contributions} = {totals.computed_ending}, "
            f"but export ending balance is {ending}.")

    # 2. Running balance, row by row
    # Report only the FIRST row that drifts (later rows inherit the same error).
    running = parsed.opening_balance
    first_bad, bad_count = None, 0
    for i, r in tx.iterrows():
        running += r["cash_in"] - r["cash_out"]
        if r["balance"] is not None and running != r["balance"]:
            bad_count += 1
            if first_bad is None:
                first_bad = (f"Balance stops matching at row {i + 1} ({r['description']!r}): "
                             f"expected {running}, export shows {r['balance']}. "
                             "Check that row's amount.")
    if first_bad:
        extra = bad_count - 1
        problems.append(first_bad + (f" ({extra} later row(s) are off by the same amount.)"
                                     if extra else ""))

    # 3. Report footer totals
    if parsed.report_totals:
        tin, tout = dsum(tx["cash_in"]), dsum(tx["cash_out"])
        if (tin, tout) != parsed.report_totals:
            problems.append(f"Footer totals {parsed.report_totals} != summed "
                            f"cash in/out ({tin}, {tout}).")
    return problems


# =============================================================================
# 6. OUTPUT BUILDERS
# =============================================================================

def _breakdown_note(group: pd.DataFrame) -> str:
    """'Water/sewer $286.55 + electric $48.17 + trash $64.25' (mapping order)."""
    parts = []
    for _, g in group.sort_values(["mapping_order", "date"]).groupby("rule_key", sort=False):
        if g["note_by_unit"].iloc[0] and g["unit"].ne("").any():
            for unit, gu in g.groupby("unit", sort=True):
                parts.append(f"Unit {unit} {fmt_note(dsum(gu['net']))}")
            continue
        wos = work_orders(g["description"])
        part = f"{g['note_label'].iloc[0]} {fmt_note(dsum(g['net']))}"
        parts.append(part + (f" ({', '.join(wos)})" if wos else ""))
    return cap_first(" + ".join(parts)) if len(parts) > 1 or group["note_by_unit"].any() else (
        cap_first(parts[0]) if parts else "")


def _ordered_categories(tx: pd.DataFrame, role: str, preferred: list[str]) -> list[str]:
    present = list(dict.fromkeys(tx.loc[tx["role"] == role]
                                 .sort_values("mapping_order")["summary"].dropna()))
    return [c for c in preferred if c in present] + [c for c in present if c not in preferred]


def period_label(parsed: ParsedExport, tx: pd.DataFrame) -> str:
    start, end = tx["date"].min(), tx["date"].max()
    if start.to_period("M") == end.to_period("M"):
        return start.strftime("%B %Y")
    return f"{start:%b %d, %Y} - {end:%b %d, %Y}"


def build_owner_summary(parsed: ParsedExport, tx: pd.DataFrame, totals: Totals,
                        profile: dict) -> pd.DataFrame:
    rows = []
    add = lambda sec, item, amt=None, note="": rows.append(
        {"Section": sec, "Line Item": item, "Amount": amt, "Notes": note})

    owner = profile.get("owner") or parsed.meta.get("owner", "")
    prop = profile.get("property_display") or "; ".join(sorted(set(tx["property"]) - {""}))
    add("Header", "Owner", note=owner)
    add("Header", "Property", note=prop)
    add("Header", "Period", note=period_label(parsed, tx))
    if profile.get("occupancy"):
        add("Header", "Occupancy", note=profile["occupancy"])

    add("Balance", "Opening Balance", totals.opening, profile.get("reserve_label", ""))

    notes_override = profile.get("summary_notes", {})
    for role, section, preferred, total_label, total in (
        ("income", "Income", SUMMARY_INCOME_ORDER, "Total Income", totals.income),
        ("expense", "Expenses", SUMMARY_EXPENSE_ORDER, "Total Expenses", totals.expenses),
    ):
        for cat in _ordered_categories(tx, role, preferred):
            g = tx[(tx["role"] == role) & (tx["summary"] == cat)]
            note = notes_override.get(cat, _breakdown_note(g))
            add(section, cat, dsum(g["net"]), note)
        add(section, total_label, total)

    add("Result", "Net Operating Cash Flow", totals.net_operating, "Total Income - Total Expenses")

    dist = tx[tx["role"] == "distribution"]
    if len(dist):
        how = "; ".join(f"{(r['reference'].split('-')[0] or 'Paid').upper()} {r['date']:%m/%d}"
                        for _, r in dist.iterrows())
        add("Result", f"Owner Distribution ({how})", totals.distributions)
    if totals.contributions:
        add("Result", "Owner Contributions", totals.contributions)

    ending = totals.computed_ending
    add("Balance", "Ending Balance", ending,
        "Reserve maintained" if ending == totals.opening else "")
    if profile.get("highlights"):
        add("Notes", "Highlights", note=profile["highlights"])
    return pd.DataFrame(rows)


def build_schedule_e(parsed: ParsedExport, tx: pd.DataFrame, totals: Totals,
                     profile: dict) -> pd.DataFrame:
    period = period_label(parsed, tx)
    notes = profile.get("schedule_e_notes", {})
    ops = tx[tx["role"].isin(["income", "expense"])]

    # Show each source GL with the spelling that carries its account code.
    display = {}
    for key, g in ops.groupby("rule_key"):
        coded = [n for n in g["gl"] if _GL_CODE.match(n)]
        display[key] = coded[0] if coded else g["gl"].iloc[0]

    def sources(line: int) -> str:
        g = ops[ops["schedule_e"] == line].sort_values(["mapping_order", "date"])
        out = []
        for key, gk in g.groupby("rule_key", sort=False):
            wos = work_orders(gk["description"])
            out.append(f"{display[key]}{' - ' + ', '.join(wos) if wos else ''} "
                       f"({fmt_note(dsum(gk['net']))})")
        return "; ".join(out)

    rows = []
    for line, name in SCHEDULE_E_LINES.items():
        amt = dsum(ops.loc[ops["schedule_e"] == line, "net"])
        rows.append({"Schedule E Line": str(line), "Category": name, period: amt,
                     "Source GL Accounts / Transactions": sources(line),
                     "Notes": notes.get(line, "")})

    expense_total = dsum(ops.loc[ops["schedule_e"].isin(range(5, 20)), "net"])
    rows.append({"Schedule E Line": "20", "Category": "Total expenses", period: expense_total,
                 "Source GL Accounts / Transactions": "Sum of lines 5-19", "Notes": ""})
    rows.append({"Schedule E Line": "21", "Category": "Net income (loss) before owner-paid items",
                 period: totals.income - expense_total,
                 "Source GL Accounts / Transactions": "Line 3 - Line 20", "Notes": ""})
    dist_src = "; ".join(sorted(set(tx.loc[tx["role"] == "distribution", "gl"])))
    rows.append({"Schedule E Line": "Excluded", "Category": "Owner distributions",
                 period: totals.distributions, "Source GL Accounts / Transactions": dist_src,
                 "Notes": "Not income or expense - equity transfer"})
    rows.append({"Schedule E Line": "Excluded", "Category": "Operating reserve (ending balance)",
                 period: totals.computed_ending,
                 "Source GL Accounts / Transactions":
                     f"Beginning {fmt_note(totals.opening)} / Ending {fmt_note(totals.computed_ending)}",
                 "Notes": "Balance-sheet item"})
    df = pd.DataFrame(rows)

    # Schedule E must agree with the cash totals (guards against mapping gaps).
    if expense_total != totals.expenses:
        raise ValueError(f"Schedule E expenses {expense_total} != ledger expenses "
                         f"{totals.expenses}: some expense accounts lack a schedule_e line.")
    return df


def format_money_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of df with Decimal cells rendered as 1,234.56 strings (blank if none).
    Used for CSV output and for display (Decimal/None mixes don't render well)."""
    out = df.copy()
    for col in out.columns:
        if out[col].map(lambda v: isinstance(v, Decimal)).any():
            out[col] = out[col].map(lambda v: fmt_amount(v) if isinstance(v, Decimal) else "")
    return out


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return format_money_columns(df).to_csv(index=False).encode("utf-8")


def write_csv(df: pd.DataFrame, path: Path) -> None:
    """Write with money formatted as 1,234.56 (blank for header rows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_csv_bytes(df))


# =============================================================================
# 7. PIPELINE
# =============================================================================

class ValidationError(ValueError):
    """Raised when the export does not tie out. .problems holds the details."""
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Validation failed:\n  - " + "\n  - ".join(problems))


def build_outputs(parsed: ParsedExport, mapping: dict, profile: dict):
    """Parsed export + mapping + profile -> (summary_df, schedule_e_df, totals).
    Raises KeyError (unmapped GL) or ValidationError (doesn't tie out)."""
    tx = apply_mapping(parsed.transactions, mapping)
    totals = compute_totals(parsed, tx)
    problems = validate(parsed, tx, totals)
    if problems:
        raise ValidationError(problems)
    summary = build_owner_summary(parsed, tx, totals, profile)
    sched_e = build_schedule_e(parsed, tx, totals, profile)
    return summary, sched_e, totals


def run(export_path, mapping_path=None, profile_path=None, outdir="output"):
    parsed = read_export(export_path)
    mapping = load_mapping(mapping_path)
    profile = load_profile(profile_path)
    summary, sched_e, totals = build_outputs(parsed, mapping, profile)

    outdir = Path(outdir)
    write_csv(summary, outdir / "owner_summary.csv")
    write_csv(sched_e, outdir / "schedule_e.csv")
    return summary, sched_e, totals


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export")
    ap.add_argument("--mapping", help="JSON GL mapping (defaults to built-in GL_MAPPING)")
    ap.add_argument("--profile", help="JSON owner profile (occupancy, highlights, notes)")
    ap.add_argument("--outdir", default="output")
    a = ap.parse_args()
    s, e, t = run(a.export, a.mapping, a.profile, a.outdir)
    pd.set_option("display.width", 200, "display.max_colwidth", 70)
    print(s.to_string(index=False), "\n")
    print(e.to_string(index=False), "\n")
    print(f"OK - ties out. Income {t.income}  Expenses {t.expenses}  "
          f"Distributions {t.distributions}  Ending {t.computed_ending}")
