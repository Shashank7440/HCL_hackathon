"""Resolver unit tests - includes the case study's Annex A.3 worked example verbatim."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.rules.resolver import Doc, Rule, resolve

AS_OF = "2026-10-06"

def docs_a3():
    return {
        "RET-POL-2024": Doc("RET-POL-2024", 1, "2024-07-01"),
        "CIRC-26-07":   Doc("CIRC-26-07", 2, "2026-08-01", supersedes="RET-POL-2024#3.1", scope_categories="ELECTRONICS"),
        "FAQ":          Doc("FAQ", 4, "2026-09-15"),
        "FEST":         Doc("FEST", 2, "2026-11-01", scope_categories="FASHION"),
    }

def rules_a3():
    return [
        Rule("RET-WIN-ELEC-01", "return_window_days", "10", "ELECTRONICS", "ALL",
             "2024-07-01", "", "RET-POL-2024", "3.1"),
        Rule("CIRC-ELEC-02", "return_window_days", "7", "ELECTRONICS", "ALL",
             "2026-08-01", "", "CIRC-26-07", "1"),
        Rule("FAQ-ELEC", "return_window_days", "15", "ELECTRONICS", "ALL",
             "2026-09-15", "", "FAQ", "Q3"),
        Rule("RET-WIN-FASH-01", "return_window_days", "30", "FASHION", "ALL",
             "2024-07-01", "", "RET-POL-2024", "3.1"),
        Rule("FEST-FASH-02", "return_window_days", "45", "FASHION", "ALL",
             "2026-11-01", "", "FEST", "1"),
    ]

def test_annex_a3_electronics():
    """Worked example: electronics window at as_of 2026-10-06 -> 7 days (step 2)."""
    r = resolve("return_window_days", "ELECTRONICS", "STANDARD", AS_OF, rules_a3(), docs_a3())
    assert r.status == "resolved" and r.winner.rule_id == "CIRC-ELEC-02" and r.winner.value == "7"
    assert any("superseded" in l["reason"] for l in r.losers)        # old policy loses step 2
    assert any(l["rule_id"] == "FAQ-ELEC" and "authority" in l["reason"] for l in r.losers)

def test_annex_a3_fashion_festive_not_yet_effective():
    """Fashion unaffected by the 2026-11-01 circular; it appears in upcoming, never wins."""
    r = resolve("return_window_days", "FASHION", "STANDARD", AS_OF, rules_a3(), docs_a3())
    assert r.status == "resolved" and r.winner.rule_id == "RET-WIN-FASH-01" and r.winner.value == "30"
    assert any(u.rule_id == "FEST-FASH-02" for u in r.upcoming)
    assert all(u.rule_id != "FEST-FASH-02" for u in [r.winner] if r.winner)

def test_level5_informational_never_wins():
    docs = docs_a3(); docs["FORUM"] = Doc("FORUM", 5, "2026-01-01")
    rules = rules_a3() + [Rule("FORUM-1", "return_window_days", "90", "ELECTRONICS", "ALL",
                                "2026-01-01", "", "FORUM", "1")]
    r = resolve("return_window_days", "ELECTRONICS", "STANDARD", AS_OF, rules, docs)
    assert r.winner.rule_id == "CIRC-ELEC-02"
    assert any(i.rule_id == "FORUM-1" for i in r.informational)

def test_tie_same_value_ok_unresolved_different_value_flags_conflict():
    docs = {"A": Doc("A", 1, "2026-01-01"), "B": Doc("B", 1, "2026-01-01")}
    same = [Rule("A-1", "p", "5", "ALL", "ALL", "2026-01-01", "", "A", "1"),
            Rule("B-1", "p", "5", "ALL", "ALL", "2026-01-01", "", "B", "1")]
    assert resolve("p", None, None, AS_OF, same, docs).status == "resolved"     # same value: fine
    diff = same + [Rule("B-2", "p", "9", "ALL", "ALL", "2026-01-01", "", "B", "2")]
    r = resolve("p", None, None, AS_OF, diff, docs)
    assert r.status == "unresolved" and r.tied                          # -> conflict_flagged upstream

def test_tier_wafer_specific_beats_all_in_same_doc():
    """DECISION A-1: RET-FEE-02 (GOLD;PLATINUM) beats RET-FEE-01 (ALL) - same document."""
    docs = {"RET-POL-2024": Doc("RET-POL-2024", 1, "2024-07-01")}
    rules = [Rule("RET-FEE-01", "restocking_fee_pct", "10", "ALL", "ALL", "2024-07-01", "", "RET-POL-2024", "4.1"),
             Rule("RET-FEE-02", "restocking_fee_pct", "0", "ALL", "GOLD;PLATINUM", "2024-07-01", "", "RET-POL-2024", "4.2")]
    r = resolve("restocking_fee_pct", "ELECTRONICS", "GOLD", AS_OF, rules, docs)
    assert r.winner.rule_id == "RET-FEE-02" and r.winner.value == "0"
    r2 = resolve("restocking_fee_pct", "ELECTRONICS", "STANDARD", AS_OF, rules, docs)
    assert r2.winner.rule_id == "RET-FEE-01" and r2.winner.value == "10"

def test_not_effective_yet_excluded():
    docs = {"F": Doc("F", 1, "2026-11-01")}
    rules = [Rule("F-1", "p", "1", "ALL", "ALL", "2026-11-01", "", "F", "1")]
    r = resolve("p", None, None, AS_OF, rules, docs)
    assert r.status == "none" and r.winner is None
    assert any(u.rule_id == "F-1" for u in r.upcoming)

def test_recency_tiebreak():
    """Same authority, neither supersedes: later effective_from wins (step 4)."""
    docs = {"OLD": Doc("OLD", 1, "2026-01-01"), "NEW": Doc("NEW", 1, "2026-09-01")}
    rules = [Rule("OLD-1", "p", "10", "ALL", "ALL", "2026-01-01", "", "OLD", "1"),
             Rule("NEW-1", "p", "5", "ALL", "ALL", "2026-09-01", "", "NEW", "1")]
    r = resolve("p", None, None, AS_OF, rules, docs)
    assert r.winner.rule_id == "NEW-1" and r.winner.value == "5"
    assert any("recency" in l["reason"] or "effective_from" in l["reason"] for l in r.losers)

if __name__ == "__main__":
    for name, fn in sorted({k: v for k, v in globals().items() if k.startswith("test_")}.items()):
        fn(); print(f"PASS {name}")
    print("ALL RESOLVER TESTS PASSED")
