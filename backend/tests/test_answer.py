from rag import answer

HITS = [
    {"title": "Handbook", "section": "Leave policy", "chunk_index": 2, "type": "markdown", "text": "18 days of annual leave.",
     "source": "handbook.md", "doc_id": "d1", "score": 0.8},
    {"title": "Job: Data Analyst (Bengaluru)", "section": "", "chunk_index": 0, "type": "job",
     "text": "Job opening: Data Analyst.", "source": "job:1", "doc_id": "d2", "score": 0.4},
]


def test_source_label():
    assert answer.source_label(HITS[0]) == "Handbook · Leave policy"
    assert answer.source_label(HITS[1]) == "Job: Data Analyst (Bengaluru)"


def test_context_is_numbered():
    ctx = answer.build_context(HITS)
    assert ctx.startswith("[1] (Handbook · Leave policy)\n18 days")
    assert "\n\n[2] (Job: Data Analyst (Bengaluru))" in ctx


def test_citations_only_for_cited_passages():
    cites = answer.make_citations(HITS, "You get 18 days [1].")
    assert [c["n"] for c in cites] == [1]
    assert cites[0]["snippet"] == "18 days of annual leave."
    assert [c["n"] for c in answer.make_citations(HITS, "no markers")] == [1]   # none cited: best passage only
    assert [c["n"] for c in answer.make_citations(HITS, "x [2][9]")] == [2]   # out-of-range ignored


def test_answer_appends_sources():
    out = answer.answer("leave?", HITS, complete=lambda *a, **k: "You get 18 days of annual leave [1].")
    assert out["text"].endswith("**Sources**\n[1] Handbook · Leave policy")
    assert out["citations"][0]["title"] == "Handbook"


def test_not_found_and_no_hits():
    assert answer.answer("q", [], complete=lambda *a, **k: "x")["text"] == answer.NOT_IN_KB
    out = answer.answer("q", HITS, complete=lambda *a, **k: "NOT_FOUND")
    assert out["text"] == answer.NOT_IN_KB and out["type"] == "not_found" and out["citations"] == []
    assert out["suggestions"] == ["How many leaves do I get?"]          # related to what was retrieved


def test_clean_normalises_model_output():
    assert answer.clean("26 weeks of leave【1】") == "26 weeks of leave [1]"
    assert answer.clean("Senior‑level [2†L3]") == "Senior-level [2]"
    out = answer.answer("leave?", HITS, complete=lambda *a, **k: "You get 18 days 【1】.")
    assert out["text"].startswith("You get 18 days [1].") and [c["n"] for c in out["citations"]] == [1]
