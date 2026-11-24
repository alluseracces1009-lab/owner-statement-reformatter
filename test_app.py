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
    html = " ".join(m.value for m in at.markdown)
    assert "Ties out" in html
    assert "$1,629.49" in html and "$500.00" in html

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
    assert "$1,629.49" in " ".join(m.value for m in at.markdown)

def test_mapping_round_trip():
    text = core.mapping_to_json(core.GL_MAPPING)
    assert core.mapping_from_json(text) == {k: v for k, v in core.GL_MAPPING.items()}

def test_best_guess_is_safe():
    import importlib, sys
    m = dict(core.GL_MAPPING)
    # Reuse the app's helper without running the page.
    src = open("app.py").read()
    ns = {}
    start = src.index("_GENERIC_WORDS"); end = src.index("with st.container(border=True):\n    if not unmapped")
    exec("import difflib, re\nimport owner_statement as core\n" + src[start:end], ns)
    g = ns["best_guess"]
    assert g("6630 Pest Services", m)["summary"] == "Landscaping & Pest Control"
    assert g("Snow Plowing Contract", m)["summary"] == "Landscaping & Pest Control"
    assert g("Zzz Unknown Thing", m) is None          # unsure -> user must choose

def test_unmapped_requires_choice_when_unsure():
    at = AppTest.from_file("app.py", default_timeout=30)
    m = dict(core.GL_MAPPING); m.pop("licenses & permits")
    at.session_state["mapping"] = m
    at.run(); at.button[0].click().run()
    cat = at.selectbox(key=next(s.key for s in at.selectbox if s.key and s.key.startswith("cat_")))
    assert cat.value == "Choose a category…"          # never pre-selected
    next(b for b in at.button if b.label == "Save these mappings").click().run()
    assert any("Choose a category" in e.value for e in at.error)
    gen = next(b for b in at.button if b.label == "Generate owner statements")
    assert gen.disabled                                 # nothing was saved
