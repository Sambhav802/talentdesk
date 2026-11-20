"""Pure ranking functions: BM25 (lexical), cosine similarity (vectors) and their hybrid fusion."""
import math
import re
from collections import Counter

import numpy as np

_STOP = set("""a an and are as at be but by can do does for from has have how i if in into is it its me my
no not of on or our so than that the their them then there these they this to us was we what when where which
who why will with you your""".split())

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and (len(t) > 1 or t.isdigit())]


class BM25:
    """Okapi BM25 over a small in-memory corpus (HR handbooks are tens to hundreds of chunks)."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.n = len(docs)
        self.avgdl = (sum(self.lens) / self.n) if self.n else 0.0
        df = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, dl in zip(self.tfs, self.lens):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / denom
            out.append(s)
        return out


def saturate(raw: float, k: float = 5.0) -> float:
    """Map an unbounded BM25 score to [0, 1) without normalising by the best hit, so a threshold still
    means something when nothing in the corpus is relevant."""
    return raw / (raw + k) if raw > 0 else 0.0


def cosine_matrix(query: list[float], vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    q = np.asarray(query, dtype=np.float32)
    m = np.asarray(vectors, dtype=np.float32)
    qn = np.linalg.norm(q) or 1.0
    mn = np.linalg.norm(m, axis=1)
    mn[mn == 0] = 1.0
    return (m @ q / (mn * qn)).tolist()


def fuse(vector_score: float | None, bm25_raw: float, alpha: float) -> float:
    """Hybrid score. Without a vector score (no embeddings), the lexical score stands alone."""
    lex = saturate(bm25_raw)
    if vector_score is None:
        return lex
    return alpha * max(vector_score, 0.0) + (1 - alpha) * lex


def rank(candidates: list[dict], top_k: int, min_score: float, relative: float = 0.0) -> list[dict]:
    """Sort by `score`, drop anything under `min_score` or under `relative` x the best score, keep `top_k`.
    The relative cut removes weak passages that only share a common word with the question."""
    kept = [c for c in candidates if c["score"] >= min_score]
    kept.sort(key=lambda c: c["score"], reverse=True)
    if kept and relative > 0:
        floor = kept[0]["score"] * relative
        kept = [c for c in kept if c["score"] >= floor]
    return kept[:top_k]
