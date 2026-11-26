"""
usage.py - anonymous usage counter (privacy-friendly).

Sends ONLY an event name (e.g. "generate_ok") to a Supabase table that the app can
insert into but never read. No file contents, no amounts, no names, no IP stored by us.
Does nothing unless SUPABASE_URL and SUPABASE_KEY are set in Streamlit secrets.
Never blocks or breaks the app: runs in a background thread and swallows all errors.
"""
from __future__ import annotations

import json
import threading
import urllib.request

EVENTS = {"visit", "sample", "upload", "generate_ok", "generate_fail",
          "mapping_saved", "mapping_loaded", "download"}


def _config():
    try:
        import streamlit as st
        url, key = st.secrets.get("SUPABASE_URL"), st.secrets.get("SUPABASE_KEY")
    except Exception:          # no secrets file locally, or not running in Streamlit
        return None
    return (url.rstrip("/"), key) if url and key else None


def _post(url: str, key: str, event: str) -> int | None:
    req = urllib.request.Request(
        f"{url}/rest/v1/usage_events",
        data=json.dumps({"event": event}).encode(),
        method="POST",
        headers={"apikey": key, "Content-Type": "application/json", "Prefer": "return=minimal"},
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.status
    except Exception:
        return None


def track(event: str, sync: bool = False, config=None):
    """Record one anonymous event. Returns the HTTP status when sync=True (for tests)."""
    if event not in EVENTS:
        return None
    cfg = config or _config()
    if not cfg:
        return None
    if sync:
        return _post(*cfg, event)
    threading.Thread(target=_post, args=(*cfg, event), daemon=True).start()
    return None
