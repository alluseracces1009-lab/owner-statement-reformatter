"""
ui_theme.py - visual styling for app.py (palettes, CSS, small HTML helpers).

Three variants share one layout. The active one is picked by the
OSR_VARIANT environment variable (default below); the matching Streamlit
base colors live in .streamlit/config.toml.
"""

from __future__ import annotations

import html
import os
import re

DEFAULT_VARIANT = "ledger"

PALETTES = {
    # Navy + white, serif headings: reads like a financial statement.
    "ledger": dict(
        base="light", primary="#1E3A5F", bg="#F6F7F9", card="#FFFFFF", soft="#EEF2F7",
        text="#1F2937", muted="#64748B", border="#E2E8F0", ok="#15803D", ok_bg="#ECFDF3",
        hero_from="#1E3A5F", hero_to="#2C5282", hero_text="#FFFFFF",
        head_font="'Source Serif 4', Georgia, serif", body_font="'Inter', system-ui, sans-serif",
        fonts="Source+Serif+4:wght@600;700&family=Inter:wght@400;500;600",
    ),
    # Warm off-white + teal, rounded and friendly.
    "fresh": dict(
        base="light", primary="#0F766E", bg="#FBFAF7", card="#FFFFFF", soft="#F1EEE7",
        text="#1C1917", muted="#78716C", border="#E7E5E4", ok="#0F766E", ok_bg="#ECFDF5",
        hero_from="#F0FDFA", hero_to="#FBFAF7", hero_text="#134E4A",
        head_font="'Plus Jakarta Sans', system-ui, sans-serif",
        body_font="'Plus Jakarta Sans', system-ui, sans-serif",
        fonts="Plus+Jakarta+Sans:wght@400;500;600;700;800",
    ),
    # Dark slate + emerald.
    "night": dict(
        base="dark", primary="#10B981", bg="#0B1220", card="#111A2E", soft="#16213A",
        text="#E5E7EB", muted="#94A3B8", border="#1F2A44", ok="#34D399", ok_bg="#0F2A22",
        hero_from="#111A2E", hero_to="#0B1220", hero_text="#F8FAFC",
        head_font="'Inter', system-ui, sans-serif", body_font="'Inter', system-ui, sans-serif",
        fonts="Inter:wght@400;500;600;700;800",
    ),
}


def active_variant() -> str:
    v = os.environ.get("OSR_VARIANT", DEFAULT_VARIANT).lower()
    return v if v in PALETTES else DEFAULT_VARIANT


def palette() -> dict:
    return PALETTES[active_variant()]


def css() -> str:
    """Page CSS. Blank lines and comments are stripped because Streamlit's
    markdown renderer ends an HTML block at the first blank line."""
    p = palette()
    raw = f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family={p['fonts']}&display=swap');
  html, body, [data-testid="stAppViewContainer"] {{
      background: {p['bg']}; color: {p['text']}; font-family: {p['body_font']};
  }}
  /* Hide Streamlit's top toolbar (Fork / GitHub / menu) for a cleaner page. */
  header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
  [data-testid="stToolbar"], [data-testid="stDecoration"] {{ display: none; }}
  .block-container {{ max-width: 980px; padding-top: 2rem; padding-bottom: 4rem; }}
  h1, h2, h3, h4 {{ font-family: {p['head_font']}; color: {p['text']}; letter-spacing: -0.01em; }}

  /* Hero */
  .osr-hero {{
      background: linear-gradient(135deg, {p['hero_from']}, {p['hero_to']});
      color: {p['hero_text']}; border: 1px solid {p['border']};
      border-radius: 20px; padding: 2.4rem 2.4rem 2rem; margin-bottom: 1.6rem;
  }}
  .osr-badge {{
      display: inline-block; font-size: .78rem; font-weight: 600; letter-spacing: .04em;
      text-transform: uppercase; padding: .3rem .7rem; border-radius: 999px;
      background: rgba(255,255,255,.14); border: 1px solid rgba(127,127,127,.35);
  }}
  .osr-hero h1 {{
      color: {p['hero_text']}; font-size: 2.5rem; line-height: 1.12; margin: .9rem 0 .7rem;
      padding: 0;
  }}
  .osr-hero p.lead {{ font-size: 1.08rem; line-height: 1.6; opacity: .9; max-width: 640px; margin: 0; }}
  .osr-chips {{ display: flex; flex-wrap: wrap; gap: .6rem; margin-top: 1.4rem; }}
  .osr-chip {{
      font-size: .9rem; padding: .45rem .8rem; border-radius: 10px;
      background: rgba(255,255,255,.12); border: 1px solid rgba(127,127,127,.3);
  }}

  .osr-watch {{
      display: inline-block; margin-top: 1.2rem; padding: .6rem 1.1rem; border-radius: 10px;
      background: #FACC15; color: #0B0B0F !important; font-weight: 700; text-decoration: none !important;
  }}
  .osr-watch:hover {{ background: #FDE047; }}
  /* Step headers */
  .osr-step {{ display: flex; align-items: center; gap: .75rem; margin: 1.6rem 0 .6rem; }}
  .osr-num {{
      width: 2rem; height: 2rem; border-radius: 999px; display: grid; place-items: center;
      background: {p['primary']}; color: {'#0B1220' if p['base'] == 'dark' else '#FFFFFF'};
      font-weight: 700; font-size: .95rem; flex: none;
  }}
  .osr-step h3 {{ margin: 0; padding: 0; font-size: 1.3rem; }}
  .osr-step .sub {{ color: {p['muted']}; font-size: .92rem; margin-left: auto; }}

  /* Bordered containers -> cards */
  [data-testid="stVerticalBlockBorderWrapper"] {{
      background: {p['card']}; border-radius: 16px !important; border-color: {p['border']} !important;
  }}

  /* Result tiles */
  .osr-tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: .8rem; }}
  .osr-tile {{
      background: {p['card']}; border: 1px solid {p['border']}; border-radius: 14px; padding: 1rem 1.1rem;
  }}
  .osr-tile .k {{ color: {p['muted']}; font-size: .85rem; }}
  .osr-tile .v {{ font-size: 1.55rem; font-weight: 700; margin-top: .2rem; color: {p['text']};
                  font-variant-numeric: tabular-nums; }}
  .osr-ok {{
      margin-top: .9rem; padding: .85rem 1rem; border-radius: 12px; font-weight: 500;
      background: {p['ok_bg']}; color: {p['ok']}; border: 1px solid {p['ok']}33;
  }}

  /* Buttons */
  .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
      border-radius: 10px; font-weight: 600; padding: .55rem 1.1rem;
  }}
  [data-testid="stFileUploaderDropzone"] {{ border-radius: 14px; }}
  [data-testid="stExpander"] details {{ border-radius: 14px; border-color: {p['border']}; background: {p['card']}; }}

  .osr-foot {{ color: {p['muted']}; font-size: .85rem; text-align: center; margin-top: 3rem; line-height: 1.6; }}
  @media (max-width: 640px) {{
      .osr-hero {{ padding: 1.6rem 1.3rem; }}
      .osr-hero h1 {{ font-size: 1.85rem; }}
      .osr-step .sub {{ display: none; }}
  }}
</style>
"""
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    return "\n".join(line for line in raw.splitlines() if line.strip())


def hero() -> str:
    return """
<div class="osr-hero">
  <span class="osr-badge">Free · No signup</span>
  <h1>Owner statements without the Excel weekend</h1>
  <p class="lead">Upload one month's AppFolio or Buildium owner statement / general ledger export.
  Get back a clean one-page owner summary and a Schedule E breakdown for the CPA.</p>
  <div class="osr-chips">
    <span class="osr-chip">✓ AppFolio &amp; Buildium exports</span>
    <span class="osr-chip">✓ Totals checked to the penny</span>
    <span class="osr-chip">✓ Files not stored</span>
  </div>
  <a class="osr-watch" href="https://www.youtube.com/watch?v=8pOCphcHSV8" target="_blank" rel="noopener">▶&nbsp; Watch the 3-min walkthrough</a>
</div>
"""


def step(num: int, title: str, sub: str = "") -> str:
    sub_html = f'<span class="sub">{html.escape(sub)}</span>' if sub else ""
    return (f'<div class="osr-step"><div class="osr-num">{num}</div>'
            f'<h3>{html.escape(title)}</h3>{sub_html}</div>')


def tiles(items: list[tuple[str, str]]) -> str:
    cells = "".join(f'<div class="osr-tile"><div class="k">{html.escape(k)}</div>'
                    f'<div class="v">{html.escape(v)}</div></div>' for k, v in items)
    return f'<div class="osr-tiles">{cells}</div>'


def ok_banner(text: str) -> str:
    return f'<div class="osr-ok">✅ {html.escape(text)}</div>'


def footer() -> str:
    return """
<div class="osr-foot">
  Files are processed in memory for your session only and are not saved. We count anonymous usage only (no file data).<br>
  Schedule E categories are a starting point. Confirm them with the owner's CPA.
</div>
"""
