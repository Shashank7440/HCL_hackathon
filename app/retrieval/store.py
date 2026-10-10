"""Vector store. ChromaDB when available; SQLite-backed keyword fallback so the pipeline
runs end-to-end before pip install / offline. Same interface either way."""
from __future__ import annotations
import re, sqlite3
from ..config import settings

try:
    import chromadb
    from chromadb.utils import embedding_functions
    _HAS_CHROMA = True
except ImportError:
    _HAS_CHROMA = False

class VectorStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ensure_table()
        self.client = None
        self.last_error = None
        if _HAS_CHROMA:
            try:
                self.client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
                try:
                    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=settings.EMBED_MODEL)
                except Exception:
                    embed_fn = embedding_functions.DefaultEmbeddingFunction()
                self.col = self.client.get_or_create_collection(
                    "policies",
                    embedding_function=embed_fn,
                    metadata={"hnsw:space": "cosine"})
            except Exception as e:
                self.client = None
                self.last_error = repr(e)

    def _ensure_table(self):
        self.conn.execute("""CREATE TABLE IF NOT EXISTS chunks(
            chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, title TEXT, section TEXT,
            page INTEGER DEFAULT 1, version TEXT, authority_level INTEGER DEFAULT 4,
            effective_from TEXT, effective_to TEXT, eff_from_i INTEGER, eff_to_i INTEGER,
            scope_categories TEXT DEFAULT 'ALL', scope_tiers TEXT DEFAULT 'ALL',
            text TEXT NOT NULL)""")
        self.conn.commit()

    def upsert_chunks(self, chunks: list[dict]) -> int:
        with self.conn:
            for c in chunks:
                self.conn.execute("INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c["chunk_id"], c["doc_id"], c.get("title", ""), c.get("section", ""), c.get("page", 1),
                     c.get("version", ""), c.get("authority_level", 4), c.get("effective_from", ""),
                     c.get("effective_to", ""), int(c.get("effective_from", "00000000").replace("-", "") or 0),
                     int(c.get("effective_to", "99999999").replace("-", "") or 99999999),
                     c.get("scope_categories", "ALL"), c.get("scope_tiers", "ALL"), c["text"]))
        if self.client is not None:
            try:
                self.col.upsert(ids=[c["chunk_id"] for c in chunks],
                                documents=[c["text"] for c in chunks],
                                metadatas=[self._chroma_meta(c) for c in chunks])
            except Exception as e:                     # never swallow silently: surface in /health
                self.last_error = repr(e)
        return len(chunks)

    @staticmethod
    def _chroma_meta(c: dict) -> dict:
        """Chroma `where` compares numbers only, so dates are YYYYMMDD ints. No None values allowed."""
        i = lambda d, dflt: int((d or "").replace("-", "") or dflt)
        return {"doc_id": c["doc_id"], "title": c.get("title", ""), "section": c.get("section", ""),
                "page": int(c.get("page", 1)), "version": c.get("version", ""),
                "authority_level": int(c.get("authority_level", 4)),
                "eff_from_i": i(c.get("effective_from"), 0), "eff_to_i": i(c.get("effective_to"), 99999999),
                "scope_categories": c.get("scope_categories", "ALL"), "scope_tiers": c.get("scope_tiers", "ALL")}

    def delete_doc(self, doc_id: str):
        with self.conn: self.conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        if self.client is not None:                    # re-ingest must not leave stale vectors
            try: self.col.delete(where={"doc_id": doc_id})
            except Exception: pass

    STOPWORDS = {"the","what","how","you","your","for","are","can","does","did","have","has",
                 "with","when","where","who","this","that","from","will","would","should",
                 "could","about","into","out","and","but","not","any","all","more","most",
                 "than","then","them","they","its","his","her","our","their","please","need",
                 "want","know","tell","show","list","was","were","been","being","there","here"}

    def keyword_search(self, question: str, as_of_i: int, top_k: int) -> list[dict]:
        """Fallback ranking: CONTENT-word coverage, effective-window filtered.
        A single accidental term match (e.g. 'deliver' in a generic FAQ) must not leak
        an answer: with >=2 content words in the question, at least 2 must match."""
        words = {w for w in re.findall(r"[a-z]{3,}", question.lower())} - self.STOPWORDS
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE eff_from_i <= ? AND eff_to_i >= ?", (as_of_i, as_of_i)).fetchall()
        scored = []
        for r in rows:
            text = r["text"].lower()
            # word-boundary + light stemming: 'return' matches 'returns'/'returned'
            # but 'deliver' must NOT match 'delivery'
            matched = sum(1 for w in words
                          if re.search(r"\b" + re.escape(w) + r"(s|es|ed|ing)?\b", text))
            need = 2 if len(words) >= 2 else 1
            if matched < need or not words:
                continue
            score = matched / len(words)
            # Domain relevance boost for category-specific matches
            for cat_w in ("fashion", "electronics", "grocery", "beauty", "home", "warranty"):
                if cat_w in words and re.search(r"\b" + re.escape(cat_w) + r"\b", text):
                    score += 0.25
            if "window" in words and "days" in text:
                score += 0.15
            if score >= 0.34:
                d = dict(r); d["score"] = score
                scored.append(d)
        scored.sort(key=lambda h: (-h["score"], h["authority_level"], -h["eff_from_i"]))
        return scored[:top_k]

    def semantic_search(self, question: str, as_of_i: int, top_k: int) -> list[dict] | None:
        if self.client is None: return None
        try:
            res = self.col.query(query_texts=[question], n_results=top_k * 2,
                                 where={"$and": [{"eff_from_i": {"$lte": as_of_i}},
                                                 {"eff_to_i": {"$gte": as_of_i}}]})
            out = []
            for i, cid in enumerate(res["ids"][0]):
                score = 1.0 - float(res["distances"][0][i])          # cosine similarity
                if score < settings.MIN_SCORE: continue
                row = self.conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (cid,)).fetchone()
                if row:
                    d = dict(row); d["score"] = round(score, 4)
                    out.append(d)
            return out[:top_k]
        except Exception as e:
            self.last_error = repr(e)
            return None
