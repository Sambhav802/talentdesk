from pathlib import Path

from rag.chunking import chunk_text, split_sentences

HANDBOOK = (Path(__file__).resolve().parents[1] / "seed" / "handbook.md").read_text(encoding="utf-8")


def test_empty_text_gives_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunks_respect_size_and_keep_sections():
    chunks = chunk_text(HANDBOOK, size=500, overlap=100)
    assert len(chunks) > 5
    assert all(len(c.text) <= 500 for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    sections = {c.section for c in chunks}
    assert {"Leave policy", "Probation", "Employee referral bonus"} <= sections
    leave = [c for c in chunks if c.section == "Leave policy"]
    assert any("18 days of paid annual leave" in c.text for c in leave)


def test_headings_are_not_chunk_text():
    chunks = chunk_text("# Title\n\nBody one.\n\n## Part\n\nBody two.")
    assert [c.text for c in chunks] == ["Body one.", "Body two."]
    assert [c.section for c in chunks] == ["Title", "Part"]


def test_overlap_carries_whole_sentences_within_a_section():
    sents = [f"Sentence number {i} talks about policy item {i}." for i in range(40)]
    chunks = chunk_text(" ".join(sents), size=300, overlap=120)
    assert len(chunks) > 3
    for a, b in zip(chunks, chunks[1:]):
        last = split_sentences(a.text)[-1]
        assert b.text.startswith(last) or last in b.text[:150]


def test_very_long_sentence_is_hard_wrapped():
    text = " ".join(["word"] * 1000)
    chunks = chunk_text(text, size=200, overlap=0)
    assert all(len(c.text) <= 200 for c in chunks)
    assert sum(c.text.count("word") for c in chunks) == 1000
