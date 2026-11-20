import pytest

from rag import scoring

DOCS = [
    "Employees receive 18 days of paid annual leave per year.",
    "The referral bonus is INR 25,000 for junior roles.",
    "Probation lasts six months and can be extended once.",
]


def test_tokenize_drops_stopwords_and_punctuation():
    assert scoring.tokenize("What is the Leave-Policy, for 2026?") == ["leave", "policy", "2026"]


def test_bm25_ranks_the_matching_document_first():
    scores = scoring.BM25(DOCS).scores("how many days of annual leave")
    assert scores.index(max(scores)) == 0
    assert scores[1] == 0 and scores[2] == 0


def test_bm25_irrelevant_query_scores_zero():
    assert max(scoring.BM25(DOCS).scores("salary of astronauts on mars")) == 0


def test_saturate_is_bounded_and_monotonic():
    assert scoring.saturate(0) == 0
    assert 0 < scoring.saturate(1) < scoring.saturate(5) < scoring.saturate(50) < 1


def test_cosine_matrix():
    sims = scoring.cosine_matrix([1, 0], [[1, 0], [0, 1], [-1, 0], [2, 2]])
    assert sims == pytest.approx([1.0, 0.0, -1.0, 0.7071], abs=1e-4)
    assert scoring.cosine_matrix([1, 0], []) == []


def test_fuse_weights_vector_and_lexical():
    assert scoring.fuse(None, 5.0, 0.6) == pytest.approx(0.5)            # lexical only
    assert scoring.fuse(0.8, 0.0, 0.6) == pytest.approx(0.48)            # vector only
    assert scoring.fuse(0.8, 5.0, 0.6) == pytest.approx(0.48 + 0.2)      # hybrid
    assert scoring.fuse(-0.5, 0.0, 0.6) == 0                             # negative cosine clipped


def test_rank_applies_threshold_and_top_k():
    cands = [{"id": i, "score": s} for i, s in enumerate([0.1, 0.9, 0.5, 0.3, 0.7])]
    out = scoring.rank(cands, top_k=2, min_score=0.2)
    assert [c["id"] for c in out] == [1, 4]
    assert scoring.rank(cands, top_k=5, min_score=0.95) == []
    # relative cut: keep hits at >= 60 % of the best (0.9 -> floor 0.54)
    assert [c["id"] for c in scoring.rank(cands, top_k=5, min_score=0.2, relative=0.6)] == [1, 4]
