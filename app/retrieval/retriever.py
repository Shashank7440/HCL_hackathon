"""Retriever: hybrid search (semantic when Chroma available + keyword always), then
Annex A precedence filtering: drop superseded, order by authority asc / effective date desc."""
from __future__ import annotations
import re
from ..config import settings
from .store import VectorStore

EXPANSIONS = {"send back": "return", "give back": "return", "money back": "refund",
              "exchange": "return", "send it back": "return",
              "gadget": "electronics", "gadgets": "electronics"}

class Retriever:
    def __init__(self, conn, store: VectorStore | None = None):
        self.conn = conn
        self.store = store or VectorStore(conn)

    def search(self, question: str, category: str | None = None, tier: str | None = None,
               as_of: str = "", top_k: int | None = None) -> list[dict]:
        top_k = top_k or settings.TOP_K
        as_of_i = int(as_of.replace("-", "") or 0) if as_of else 99999999
        from ..agent.router import correct_typos
        q = correct_typos(question).lower()
        for k, v in EXPANSIONS.items():
            if k in q: q = q.replace(k, v)
        hits = self.store.semantic_search(q, as_of_i, top_k)
        if hits is None:
            hits = self.store.keyword_search(q, as_of_i, top_k)
        hits = self._precedence_filter(hits, category, tier, as_of_i)
        if self._asks_about_unknown_entity(question):
            return []
        return hits[:top_k]

    def _asks_about_unknown_entity(self, question: str) -> bool:
        """A capitalised, non-initial term found in NO ingested chunk/doc/product is something the sources
        cannot speak about (Antarctica, Amazon, CEO). Embedding similarity alone cannot catch this."""
        vocab = {w for (t,) in self.conn.execute("SELECT text FROM chunks")
                 for w in re.findall(r"[a-z]+", t.lower())}
        vocab |= {w for (n,) in self.conn.execute("SELECT name FROM products")
                  for w in re.findall(r"[a-z]+", n.lower())}
        vocab |= {w for r in self.conn.execute("SELECT doc_id, title, doc_type, issuer FROM documents")
                  for v in r for w in re.findall(r"[a-z]+", (v or "").lower())}
        tokens = re.findall(r"[A-Za-z]{3,}", re.sub(r"'s\b", "", question))
        return any(t[0].isupper() and t.lower() not in vocab for t in tokens[1:])

    def _precedence_filter(self, hits: list[dict], category, tier, as_of_i) -> list[dict]:
        """Drop superseded chunks with section-level precision and scope awareness:
        'DOC#3.1' kills only that section; bare 'DOC' kills the document; and a superseding
        circular scoped to ELECTRONICS cannot kill a FASHION section of the same document."""
        out = []
        dead = self._superseded_targets(category, tier, as_of_i)
        for h in hits:
            key_doc, key_sec = h["doc_id"], f"{h['doc_id']}#{h.get('section','')}"
            if key_doc in dead or key_sec in dead: continue
            if category and (h.get("scope_categories") or "ALL").upper() not in ("ALL", category.upper()): continue
            out.append(h)
        # relevance first; precedence (authority asc, then recency) breaks relevance ties
        out.sort(key=lambda h: (-h.get("score", 0.0), h.get("authority_level", 4), -h.get("eff_from_i", 0)))
        return out

    def _superseded_targets(self, category, tier, as_of_i: int = 99999999) -> set[str]:
        def covers(scope, val):
            if not val: return True
            scope = (scope or "ALL").upper()
            return scope == "ALL" or val.upper() in [s.strip() for s in scope.split(";")]
        dead = set()
        rows = self.conn.execute(
            "SELECT doc_id, authority_level, supersedes, effective_from, effective_to, "
            "scope_categories, scope_tiers FROM documents WHERE supersedes != ''").fetchall()
        for r in rows:
            if r["authority_level"] > 2: continue
            eff_from = int((r["effective_from"] or "0").replace("-", "") or 0)
            eff_to = int((r["effective_to"] or "99999999").replace("-", "") or 99999999)
            if eff_from > as_of_i or eff_to < as_of_i: continue       # superseding doc must be in effect
            if not covers(r["scope_categories"], category) or not covers(r["scope_tiers"], tier): continue
            for tok in (r["supersedes"] or "").split(";"):
                tok = tok.strip()
                if tok: dead.add(tok)
        return dead
