"""CRUD on rule_registry + document metadata, bridging SQLite rows to resolver dataclasses."""
from __future__ import annotations
from .resolver import Doc, Rule, Resolution, resolve

def load_docs(conn) -> dict[str, Doc]:
    return {r["doc_id"]: Doc(r["doc_id"], r["authority_level"], r["effective_from"],
                             r["effective_to"] or "", r["supersedes"] or "",
                             r["scope_categories"] or "ALL", r["scope_tiers"] or "ALL")
            for r in conn.execute("SELECT * FROM documents")}

def load_rules(conn, parameter: str | None = None) -> list[Rule]:
    # auto_extracted=1 rules are unapproved proposals: retrievable/citable as informational
    # but NEVER applied by tools (v3 TDD section 8)
    base = "SELECT * FROM rule_registry WHERE coalesce(auto_extracted,0) = 0"
    q = base + (" AND parameter = ?" if parameter else "")
    rows = conn.execute(q, (parameter,) if parameter else ()).fetchall()
    return [Rule(r["rule_id"], r["parameter"], r["value"], r["scope_categories"] or "ALL",
                 r["scope_tiers"] or "ALL", r["effective_from"], r["effective_to"] or "",
                 r["source_doc_id"], r["source_section"] or "", r["operator"] or "=")
            for r in rows]

def get_rule(conn, parameter: str, category: str | None, tier: str | None,
             as_of: str) -> Resolution:
    """Tool entry point: resolve a parameter at request time. Missing rule -> status 'none'."""
    return resolve(parameter, category, tier, as_of, load_rules(conn, parameter), load_docs(conn))

def rule_citation(conn, r: Rule) -> dict:
    row = conn.execute("SELECT title, version FROM documents WHERE doc_id = ?",
                       (r.source_doc_id,)).fetchone()
    return {"rule_id": r.rule_id, "value": r.value, "source_doc_id": r.source_doc_id,
            "source_section": r.source_section, "title": row["title"] if row else "",
            "version": row["version"] if row else "",
            "effective_from": r.effective_from}
