"""Annex A Source Precedence Policy - PURE functions, no I/O, no LLM. Unit-tested.

resolve() order (case study Annex A.2 - do not reorder):
  1 applicability  2 explicit supersession  3 authority  4 recency  5 unresolved->conflict_flagged
Level-5 docs are informational only and never win. Not-yet-effective rules -> upcoming.
DECISION A-1: within the SAME document a specific scope beats 'ALL' (isolated here:
change drop_all_scope_if_specific_in_same_doc if the mentor rules otherwise).
"""
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Doc:
    doc_id: str
    authority_level: int
    effective_from: str
    effective_to: str = ""
    supersedes: str = ""
    scope_categories: str = "ALL"
    scope_tiers: str = "ALL"

@dataclass
class Rule:
    rule_id: str
    parameter: str
    value: str
    scope_categories: str = "ALL"
    scope_tiers: str = "ALL"
    effective_from: str = ""
    effective_to: str = ""
    source_doc_id: str = ""
    source_section: str = ""
    operator: str = "="

@dataclass
class Resolution:
    winner: Rule | None
    status: str                                   # resolved | none | unresolved
    losers: list[dict] = field(default_factory=list)   # {rule_id, reason}
    upcoming: list[Rule] = field(default_factory=list)
    informational: list[Rule] = field(default_factory=list)
    tied: list[Rule] = field(default_factory=list)

def _scope_covers(scope: str, value: str | None) -> bool:
    if not scope or scope.upper() == "ALL": return True
    if not value: return False
    return value.upper() in [s.strip().upper() for s in scope.split(";")]

def _split_supersedes(s: str) -> list[str]:
    return [t.strip() for t in (s or "").split(";") if t.strip()]

def _effective_on(d: Doc, as_of: str) -> bool:
    if d.effective_from > as_of: return False
    return (not d.effective_to) or d.effective_to >= as_of

def drop_all_scope_if_specific_in_same_doc(app: list[Rule], losers: list[dict]) -> list[Rule]:
    """DECISION A-1: inside one document, a specific scope beats an 'ALL' scope."""
    keep: list[Rule] = []
    for r in app:
        specific_siblings = [x for x in app
                             if x.source_doc_id == r.source_doc_id
                             and x.parameter == r.parameter
                             and x.rule_id != r.rule_id
                             and (x.scope_categories != "ALL" or x.scope_tiers != "ALL")]
        if (r.scope_categories == "ALL" and r.scope_tiers == "ALL") and specific_siblings:
            losers.append({"rule_id": r.rule_id, "reason": "general scope in same document loses to specific (A-1)"})
        else:
            keep.append(r)
    return keep

def resolve(parameter: str, category: str | None, tier: str | None,
             as_of: str, rules: list[Rule], docs: dict[str, Doc]) -> Resolution:
    cands = [r for r in rules if r.parameter == parameter]
    upcoming = [r for r in cands if r.effective_from > as_of
                and _scope_covers(r.scope_categories, category) and _scope_covers(r.scope_tiers, tier)]
    app = [r for r in cands
           if r.effective_from <= as_of and (not r.effective_to or r.effective_to >= as_of)   # step 1
           and _scope_covers(r.scope_categories, category) and _scope_covers(r.scope_tiers, tier)]
    informational = [r for r in app if docs.get(r.source_doc_id) and docs[r.source_doc_id].authority_level == 5]
    app = [r for r in app if not docs.get(r.source_doc_id) or docs[r.source_doc_id].authority_level <= 4]

    # step 2: explicit supersession by an effective level 1-2 document
    # the superseding document must itself cover this request's scope (an electronics
    # circular cannot kill a fashion rule from the same superseded section)
    sup_docs = {d.doc_id: d for d in docs.values()
                if d.authority_level <= 2 and _effective_on(d, as_of)
                and _scope_covers(d.scope_categories, category)
                and _scope_covers(d.scope_tiers, tier)}
    def superseded_by(r: Rule) -> str | None:
        for d in sup_docs.values():
            for tok in _split_supersedes(d.supersedes):
                if tok == r.source_doc_id or tok == f"{r.source_doc_id}#{r.source_section}":
                    if d.doc_id != r.source_doc_id:
                        return d.doc_id
        return None
    losers: list[dict] = []
    keep: list[Rule] = []
    for r in app:
        s = superseded_by(r)
        if s: losers.append({"rule_id": r.rule_id, "reason": f"superseded by {s} (step 2)"})
        else: keep.append(r)
    app = keep

    # DECISION A-1 (same-document specific beats ALL)
    app = drop_all_scope_if_specific_in_same_doc(app, losers)

    if not app:
        return Resolution(None, "none" if not upcoming else "none", losers, upcoming, informational)

    # step 3: authority - LOWEST authority_level number wins
    best = min(docs[r.source_doc_id].authority_level for r in app if r.source_doc_id in docs)
    losers += [{"rule_id": r.rule_id, "reason": "lower authority (step 3)"}
               for r in app if r.source_doc_id in docs and docs[r.source_doc_id].authority_level != best]
    app = [r for r in app if r.source_doc_id in docs and docs[r.source_doc_id].authority_level == best]

    # step 4: recency - later effective_from wins
    latest = max(r.effective_from for r in app)
    losers += [{"rule_id": r.rule_id, "reason": "older effective_from (step 4)"}
               for r in app if r.effective_from != latest]
    app = [r for r in app if r.effective_from == latest]

    if len(app) == 1:
        return Resolution(app[0], "resolved", losers, upcoming, informational)
    values = {r.value.strip() for r in app}
    if len(values) > 1:
        return Resolution(None, "unresolved", losers, upcoming, informational, tied=app)  # -> conflict_flagged
    return Resolution(app[0], "resolved", losers, upcoming, informational)
