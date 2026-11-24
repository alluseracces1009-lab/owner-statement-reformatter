"""App tests: python3 -m pytest -q test_app.py"""
from streamlit.testing.v1 import AppTest
import owner_statement as core

def start():
    at = AppTest.from_file("app.py", default_timeout=30).run()
    at.button[0].click().run()          # "Try the sample file"
    return at

def test_sample_file_generates_and_ties_out():
    at = start()
    assert not at.exception
    assert any("All GL accounts" in s.value for s in at.success)
    gen = next(b for b in at.button if b.label == "Generate owner statements")
    gen.click().run()
    assert not at.exception, at.exception
    assert any("Ties out" in s.value for s in at.success)
    vals = {m.label: m.value for m in at.metric}
    assert vals["Total expenses"] == "$1,629.49" and vals["Ending balance"] == "$500.00"

def test_unmapped_account_flow():
    at = AppTest.from_file("app.py", default_timeout=30)
    # Remove one account from the starting mapping to simulate a new GL.
    m = dict(core.GL_MAPPING); m.pop("pest control")
    at.session_state["mapping"] = m
    at.run(); at.button[0].click().run()
    assert any("aren't mapped" in w.value for w in at.warning)
    gen = next(b for b in at.button if b.label == "Generate owner statements")
    assert gen.disabled
    cat = at.selectbox(key=next(s.key for s in at.selectbox if s.key and s.key.startswith("cat_")))
    cat.select("Expense → Landscaping & Pest Control")
    line = at.selectbox(key=next(s.key for s in at.selectbox if s.key and s.key.startswith("line_")))
    line.select("7 – Cleaning and maintenance")
    next(b for b in at.button if b.label == "Save these mappings").click().run()
    assert not at.exception, at.exception
    assert any("All GL accounts" in s.value for s in at.success)
    next(b for b in at.button if b.label == "Generate owner statements").click().run()
    assert {m.label: m.value for m in at.metric}["Total expenses"] == "$1,629.49"

def test_mapping_round_trip():
    text = core.mapping_to_json(core.GL_MAPPING)
    assert core.mapping_from_json(text) == {k: v for k, v in core.GL_MAPPING.items()}
