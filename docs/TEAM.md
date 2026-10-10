# Team Contribution Statement (Section 8 & Section 9.4)

**Project:** AI-Powered Retail Customer Support Agent (ShopEasy)  
**Hackathon:** HCLTech Future Ready AI Engineer Hackathon  
**Team Members:** 4 Members  

---

## 1. Member Ownership Breakdown

| Member Name | Role & Component Ownership | Key Contributions & Modules Built |
| :--- | :--- | :--- |
| **Member 1 (Lead Architect)** | **Multi-Agent Orchestration & Core Architecture** | - Designed the LangGraph Multi-Agent Architecture (`app/agent/graph.py`, `app/agent/router.py`).<br>- Implemented `SupervisorAgent`, `CompositeMultiStepAgent`, and `SynthesisAgent`.<br>- Orchestrated end-to-end API pipeline and Section 6.1 contract adherence. |
| **Member 2 (AI/RAG Specialist)** | **Knowledge Retrieval & Precedence Engine** | - Implemented Annex A Source Precedence Resolver (`app/rules/resolver.py`).<br>- Built hybrid dense + keyword vector store (`app/retrieval/store.py`, `app/retrieval/retriever.py`).<br>- Handled live ingestion parser with auto-rule extraction (`app/ingestion/pipeline.py`). |
| **Member 3 (Backend & Tool Engineer)** | **Deterministic Tools & SQLite Database** | - Implemented deterministic tools (`orders.py`, `returns.py`, `warranty.py`).<br>- Enforced rule registry traceability and Decimal arithmetic without LLM drift.<br>- Developed Annex C SQLite schema and data loader (`scripts/load_data.py`). |
| **Member 4 (QA & Safety Engineer)** | **Security Guardrails & Evaluation Suite** | - Implemented prompt injection defense & customer authorization (`app/security.py`, `authz_node`).<br>- Built the evaluation harness and report (`eval/dataset.json`, `eval/evaluator.py`, `eval/EVAL_REPORT.md`).<br>- Developed synthetic data kit and validator (`scripts/validate_data.py`). |

---

## 2. Cross-Component Verification & Code Freeze

All team members actively reviewed cross-component boundaries, participated in integration testing, verified edge-case coverage, and validated live ingestion capabilities prior to code freeze.
