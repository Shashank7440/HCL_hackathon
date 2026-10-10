# AI Usage Disclosure (Section 8 & Section 10)

This document discloses the use of AI tools during the engineering of the ShopEasy Retail Customer Support Agent, in compliance with Hackathon Rule 10 and Deliverables Checklist Section 8.

---

## 1. AI Tools Utilized

- **AI Assistants Employed:** Google Antigravity / Gemini 3.8 Flash, Claude 3.5 Sonnet.
- **Scope of Assistance:**
  - Initial repository layout and schema scaffolding (SQLite schema, FastAPI contracts).
  - Code generation assistance for deterministic tools (`orders.py`, `returns.py`, `warranty.py`).
  - Unit test authoring and test suite assertions across the Annex A precedence resolver.
  - Evaluation harness (`evaluator.py`) and edge-case generation for the synthetic data set.

---

## 2. Human Verification & Engineering Validation

Every line of AI-assisted code was subjected to strict engineering verification:
1. **Mathematical & Deterministic Integrity:**
   - All monetary calculations (refund amount, restocking fee percentage, reverse shipping deductions) were verified using Python's `Decimal` module with explicit rounding modes (`ROUND_HALF_UP`).
   - Every threshold and return window was checked directly against SQLite `rule_registry` rows.
2. **Precedence Policy Verification:**
   - Annex A resolution rules (Applicability -> Explicit Supersession -> Authority Hierarchy -> Recency) were verified with unit tests (`tests/test_resolver.py`), including verbatim reproduction of the worked example in Annex A.3.
3. **Data Integrity & Privacy Verification:**
   - Synthetic customer and order data was validated using `scripts/validate_data.py` (52 assertions passed with 0 violations).
   - Zero real customer data was used anywhere.
4. **Security & Prompt Injection Hardening:**
   - Guardrails against prompt injection and cross-customer data leakage were independently tested (`tests/test_multiagent_advanced.py`).
