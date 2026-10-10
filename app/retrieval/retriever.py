"""Retriever: hybrid search (semantic when Chroma available + keyword always), then
Annex A precedence filtering: drop superseded, order by authority asc / effective date desc."""
from __future__ import annotations
from ..config import settings
from .store import VectorStore

EXPANSIONS = {"send back": "return", "give back": "return", "money back": "refund",
              "exchange": "return", "send it back": "return"}

class Retriever:
    def __init__(self, conn, store: VectorStore | None = None):
        self.conn = conn
        self.store = store or VectorStore(conn)

    def search(self, question: str, category: str | None = None, tier: str | None = None,
               as_of: str = "", top_k: int | None = None) -> list[dict]:
        top_k = top_k or settings.TOP_K
        as_of_i = int(as_of.replace("-", "") or 0) if as_of else 99999999
        q = question.lower()
        for k, v in EXPANSIONS.items():
            if k in q: q = q.replace(k, v)
        hits = self.store.semantic_search(q, as_of_i, top_k) or self.store.keyword_search(q, as_of_i, top_k)
        hits = self._precedence_filter(hits, category, tier, as_of_i)
        return hits[:top_k]

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
