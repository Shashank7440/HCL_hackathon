"""ShopEasy Retail Support Agent - Modern Streamlit Interface.
Ultra-fast, typo-tolerant, thin client connecting to the FastAPI backend (Section 6 contract).
Supports live chat, order disambiguation, audit inspection, and panelist document ingestion.
"""
import json, os, re, requests
import streamlit as st

st.set_page_config(
    page_title="ShopEasy Retail AI Support Agent",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Design System & CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }
    
    .main-header {
        background: linear-gradient(135deg, #0F172A 0%, #1E293B 50%, #334155 100%);
        padding: 22px 28px;
        border-radius: 14px;
        margin-bottom: 20px;
        color: white;
        box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.25);
        border: 1px solid rgba(255, 255, 255, 0.08);
    }
    
    .customer-badge {
        background: rgba(59, 130, 246, 0.08) !important;
        border: 1px solid rgba(59, 130, 246, 0.25) !important;
        border-left: 4px solid #3B82F6 !important;
        padding: 14px 16px !important;
        border-radius: 10px !important;
        margin-top: 10px !important;
        margin-bottom: 14px !important;
    }
    
    .audit-card {
        background: rgba(255, 255, 255, 0.04) !important;
        border: 1px solid rgba(128, 128, 128, 0.2) !important;
        border-radius: 10px !important;
        padding: 16px !important;
        margin-bottom: 12px !important;
    }
    
    .stMetric {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(128, 128, 128, 0.22) !important;
        padding: 12px 16px !important;
        border-radius: 10px !important;
    }

    [data-testid="stMetricLabel"] p {
        font-size: 0.82rem !important;
        opacity: 0.85 !important;
    }

    [data-testid="stMetricValue"] div {
        font-size: 1.15rem !important;
        font-weight: 700 !important;
    }
</style>
""", unsafe_allow_html=True)

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
try:
    if hasattr(st, "secrets"):
        API_BASE = st.secrets.get("API_BASE", API_BASE)
except BaseException:
    API_BASE = os.getenv("API_BASE", "http://localhost:8000")

ADMIN_KEY = os.getenv("ADMIN_KEY", "admin-demo-key")

# Cached health check so UI never blocks or lags
@st.cache_data(ttl=20)
def get_api_health(base_url: str):
    try:
        r = requests.get(f"{base_url}/health", timeout=1.5)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

# Customer Profiles Directory for Instant Reference
CUSTOMERS_INFO = {
    "C1001": {
        "name": "Aarav Sharma",
        "tier": "STANDARD",
        "orders": "O-100001 (Wireless Headphones, Net ₹2999)",
        "expected": "Happy path: 3 days since delivery, refund ₹2639.10 (10% fee + ₹60 ship deducted)"
    },
    "C1002": {
        "name": "Priya Patel",
        "tier": "STANDARD",
        "orders": "O-100002 (Smart Fitness Watch, Net ₹3499)",
        "expected": "Boundary case: Delivered exactly 7 days ago (7/7 days) -> ELIGIBLE"
    },
    "C1003": {
        "name": "Rohan Mehta",
        "tier": "STANDARD",
        "orders": "O-100003 (Bluetooth Speaker, Net ₹1899)",
        "expected": "Out of window: Delivered 8 days ago (8/7 days) -> OUT_OF_WINDOW"
    },
    "C1004": {
        "name": "Neha Gupta",
        "tier": "STANDARD",
        "orders": "O-100004 (Gaming Laptop, Net ₹89990)",
        "expected": "Approval limit: Refund ₹80,931.00 > ₹50,000 limit -> requires human approval"
    },
    "C1005": {
        "name": "Ananya Verma",
        "tier": "STANDARD",
        "orders": "O-100005 (Organic Basmati Rice, Net ₹450)",
        "expected": "Non-returnable category: Grocery items cannot be returned"
    },
    "C1010": {
        "name": "Vikram Joshi",
        "tier": "GOLD",
        "orders": "O-100015 (Denim Jacket, Net ₹2939)",
        "expected": "Gold tier benefit: 0% restocking fee + 0 reverse shipping -> Full ₹2939.00 refund"
    },
    "C1009": {
        "name": "Aditya Singh",
        "tier": "STANDARD",
        "orders": "O-100009 & O-100010 (Both contain Wireless Headphones)",
        "expected": "Ambiguity edge case: Asking 'Can I return my headphones?' prompts order disambiguation"
    },
    "": {
        "name": "Anonymous / Guest",
        "tier": "N/A",
        "orders": "None",
        "expected": "General policy questions only (Electronics return window, shipping terms, Antarctica?)"
    }
}

# Header & Branding
st.markdown("""
<div class="main-header">
    <div style="display: flex; align-items: center; justify-content: space-between;">
        <div>
            <h2 style="margin: 0; font-weight: 700; color: #F8FAFC; font-size: 1.6rem;">🛍️ ShopEasy AI Retail Support Agent</h2>
            <p style="margin: 6px 0 0 0; color: #94A3B8; font-size: 0.95rem;">
                Multi-Agent Architecture · Annex A Source Precedence · Deterministic Math Tools · Typo-Tolerant
            </p>
        </div>
        <div style="text-align: right; background: rgba(255,255,255,0.06); padding: 8px 16px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1);">
            <div style="font-size: 0.75rem; color: #CBD5E1; text-transform: uppercase; letter-spacing: 0.5px;">Architecture</div>
            <div style="font-size: 0.9rem; font-weight: 600; color: #38BDF8;">LangGraph Multi-Agent</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Sidebar: Customer Selector & Context
with st.sidebar:
    st.subheader("👤 Customer Identification")
    st.caption("Identity comes **only** from the `X-Customer-Id` header (Requirement R7).")

    customer_options = [
        "C1001 — Aarav Sharma (Standard, Happy Path O-100001)",
        "C1002 — Priya Patel (Standard, Last Day of Window O-100002)",
        "C1003 — Rohan Mehta (Standard, Out of Window O-100003)",
        "C1004 — Neha Gupta (Standard, Approval Limit O-100004)",
        "C1005 — Ananya Verma (Standard, Grocery O-100005)",
        "C1010 — Vikram Joshi (GOLD Tier, Fee Waiver O-100015)",
        "C1009 — Aditya Singh (Ambiguous Orders O-100009/10)",
        "Guest / None — (Anonymous Policy Queries)",
        "Custom ID..."
    ]

    selected_option = st.selectbox("Select Customer Profile:", customer_options, index=0)

    if selected_option.startswith("C1001"):
        active_cid = "C1001"
    elif selected_option.startswith("C1002"):
        active_cid = "C1002"
    elif selected_option.startswith("C1003"):
        active_cid = "C1003"
    elif selected_option.startswith("C1004"):
        active_cid = "C1004"
    elif selected_option.startswith("C1005"):
        active_cid = "C1005"
    elif selected_option.startswith("C1010"):
        active_cid = "C1010"
    elif selected_option.startswith("C1009"):
        active_cid = "C1009"
    elif selected_option.startswith("Guest"):
        active_cid = ""
    else:
        active_cid = st.text_input("Enter Custom X-Customer-Id", value="C1001")

    # Display Active Customer Card
    c_info = CUSTOMERS_INFO.get(active_cid, {"name": "Custom User", "tier": "UNKNOWN", "orders": "Custom", "expected": "Custom scenario"})
    st.markdown(f"""
    <div class="customer-badge">
        <div style="font-weight: 600; font-size: 1.05rem; display: flex; align-items: center; justify-content: space-between;">
            <span>{c_info['name']}</span>
            <span style="font-size: 0.8rem; background: rgba(59, 130, 246, 0.2); color: #60A5FA; padding: 2px 8px; border-radius: 6px; font-weight: 600;">{active_cid or 'Guest'}</span>
        </div>
        <div style="font-size: 0.85rem; opacity: 0.9; margin-top: 6px;"><b>Tier:</b> {c_info['tier']}</div>
        <div style="font-size: 0.85rem; opacity: 0.9; margin-top: 2px;"><b>Orders:</b> {c_info['orders']}</div>
        <div style="font-size: 0.8rem; opacity: 0.75; margin-top: 6px; line-height: 1.35;"><i>{c_info['expected']}</i></div>
    </div>
    """, unsafe_allow_html=True)

    as_of = st.date_input("Simulation As-Of Date", value=None)
    as_of_str = as_of.isoformat() if as_of else "2026-10-06"

    st.divider()

    # Cached Server Status Check (Ultra-Fast)
    h = get_api_health(API_BASE)
    if h and h.get("status") == "ok":
        st.success("🟢 API Server: Online (:8000)")
    else:
        st.warning("🟡 API Server: Checking...")

    st.divider()
    st.subheader("⚡ 1-Click Scenario Prompts")
    quick_queries = [
        ("❓ When will I get my refund?", "When will I get my refund?"),
        ("💰 Refund Calculation (O-100001)", "How much refund will I get for order O-100001?"),
        ("🔄 Ambiguity Disambiguation", "Can I return my headphones?"),
        ("📦 Return Window (Electronics)", "What is the return window for electronics?"),
        ("🔤 Typo Handling Demo", "What is the reutrn window for electornics?"),
        ("⚙️ Multi-Step Reasoning (41 days)", "My headphones stopped working after 41 days. Can I return them, and if not, what can I do?"),
        ("🛡️ Privacy Violation Refusal", "Where is my order O-100002?"),
        ("❄️ Unanswerable / Abstention", "Do you deliver to Antarctica?"),
        ("⭐ Gold Member What-If", "What if I were a Gold member for order O-100001?"),
    ]
    for label, query_text in quick_queries:
        if st.button(label, use_container_width=True):
            st.session_state["preset_input"] = query_text

# Main Tabs (Clean 3-Tab Architecture)
tab_chat, tab_audit, tab_ingest = st.tabs([
    "💬 Customer Support Chat",
    "🔍 Audit Trace Inspector",
    "📄 Panelist Document Ingest"
])

with tab_chat:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "recent_traces" not in st.session_state:
        st.session_state.recent_traces = []

    # Chat Controls Header
    col_hdr_left, col_hdr_right = st.columns([5, 1])
    with col_hdr_right:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    # Display Chat History
    for idx, m in enumerate(st.session_state.messages):
        with st.chat_message(m["role"]):
            st.markdown(m["content"], unsafe_allow_html=True)
            
            # Interactive Quick Buttons for disambiguation
            if m["role"] == "assistant" and "extra" in m:
                d = m["extra"]
                atype = d.get("answer_type", "N/A")
                ans_text = m["content"]
                
                # Check for order recommendations to create interactive clickable buttons
                if atype == "clarification_needed":
                    found_orders = re.findall(r"\bO-\d{6}\b", ans_text)
                    if found_orders:
                        st.markdown("**⚡ Select an order to check refund & return eligibility:**")
                        cols_btns = st.columns(min(len(found_orders), 3))
                        for b_idx, oid in enumerate(found_orders[:3]):
                            if cols_btns[b_idx].button(f"👉 Order {oid}", key=f"btn_hist_{idx}_{oid}", use_container_width=True):
                                st.session_state["preset_input"] = f"How much refund will I get for order {oid}?"
                                st.rerun()

                cols = st.columns(3)
                color_map = {
                    "calculated": "🟢",
                    "retrieved_fact": "🔵",
                    "not_found": "⚪",
                    "refused": "🔴",
                    "clarification_needed": "🟡",
                    "conflict_flagged": "🟠"
                }
                cols[0].metric("Answer Type", f"{color_map.get(atype, '🟣')} {atype}")
                cols[1].metric("Trace ID", d.get("trace_id", "N/A"))
                cols[2].metric("Tools Invoked", len(d.get("tools_invoked", [])))

                if d.get("citations"):
                    st.caption("📚 **Citations:** " + " · ".join(
                        f"**{c['doc_id']}** §{c.get('section','')} (v{c.get('version','')}, eff {c.get('effective_from','')})"
                        for c in d["citations"]
                    ))
                if d.get("tools_invoked"):
                    with st.expander("🛠️ Deterministic Tool Executions"):
                        st.json(d["tools_invoked"])
                if d.get("applied_rules"):
                    with st.expander("⚖️ Applied Rule Registry Clauses"):
                        st.json(d["applied_rules"])
                if d.get("assumptions"):
                    st.caption("ℹ️ *Assumptions: " + "; ".join(d["assumptions"]) + "*")

    user_query = st.chat_input("Ask about returns, refunds, warranty, or order status (typo-tolerant)...")
    if "preset_input" in st.session_state and st.session_state["preset_input"]:
        user_query = st.session_state.pop("preset_input")

    if user_query:
        # Context-aware follow-up: If user typed just an order id after a clarification question
        clean_q = user_query.strip()
        oid_match = re.search(r"\bO-\d{6}\b", clean_q)
        if oid_match and len(clean_q.split()) <= 3 and st.session_state.messages:
            last_msg = st.session_state.messages[-1]
            if last_msg.get("role") == "assistant" and last_msg.get("extra", {}).get("answer_type") == "clarification_needed":
                user_query = f"How much refund will I get for order {oid_match.group(0)}?"

        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            with st.spinner("Processing through Multi-Agent System..."):
                try:
                    headers = {"X-Customer-Id": active_cid} if active_cid else {}
                    payload = {"question": user_query, "as_of_date": as_of_str}
                    res = requests.post(f"{API_BASE}/ask", json=payload, headers=headers, timeout=60)
                    data = res.json()

                    ans = data.get("answer", "")
                    st.markdown(ans)

                    # Store trace in session
                    trace_val = data.get("trace_id")
                    if trace_val and trace_val not in st.session_state.recent_traces:
                        st.session_state.recent_traces.append(trace_val)

                    atype = data.get("answer_type", "N/A")
                    
                    # Interactive buttons immediately shown for newly returned clarification
                    if atype == "clarification_needed":
                        found_orders = re.findall(r"\bO-\d{6}\b", ans)
                        if found_orders:
                            st.markdown("**⚡ Select an order to check refund & return eligibility:**")
                            cols_btns = st.columns(min(len(found_orders), 3))
                            for b_idx, oid in enumerate(found_orders[:3]):
                                if cols_btns[b_idx].button(f"👉 Order {oid}", key=f"btn_live_{oid}", use_container_width=True):
                                    st.session_state["preset_input"] = f"How much refund will I get for order {oid}?"
                                    st.rerun()

                    cols = st.columns(3)
                    color_map = {
                        "calculated": "🟢",
                        "retrieved_fact": "🔵",
                        "not_found": "⚪",
                        "refused": "🔴",
                        "clarification_needed": "🟡",
                        "conflict_flagged": "🟠"
                    }
                    cols[0].metric("Answer Type", f"{color_map.get(atype, '🟣')} {atype}")
                    cols[1].metric("Trace ID", data.get("trace_id", "N/A"))
                    cols[2].metric("Tools Invoked", len(data.get("tools_invoked", [])))

                    if data.get("citations"):
                        st.caption("📚 **Citations:** " + " · ".join(
                            f"**{c['doc_id']}** §{c.get('section','')} (v{c.get('version','')}, eff {c.get('effective_from','')})"
                            for c in data["citations"]
                        ))
                    if data.get("tools_invoked"):
                        with st.expander("🛠️ Deterministic Tool Executions"):
                            st.json(data["tools_invoked"])
                    if data.get("applied_rules"):
                        with st.expander("⚖️ Applied Rule Registry Clauses"):
                            st.json(data["applied_rules"])
                    if data.get("assumptions"):
                        st.caption("ℹ️ *Assumptions: " + "; ".join(data["assumptions"]) + "*")

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": ans,
                        "extra": data
                    })
                except Exception as e:
                    st.error(f"Error communicating with API backend: {e}")

with tab_audit:
    st.subheader("🔍 Audit Record Inspector (Requirement R10)")
    st.markdown("""
    Every query processed by the Multi-Agent system generates a cryptographically tracked **Trace ID**.
    The audit record captures the full decision trail: sanitized inputs, verified customer identity, 
    precedence decisions, deterministic tool invocations, and rule citations — **without logging sensitive chain-of-thought**.
    """)

    # Quick inspection from current session
    col_sel, col_btn = st.columns([3, 1])
    recent_list = list(reversed(st.session_state.get("recent_traces", [])))
    
    target_trace = ""
    with col_sel:
        if recent_list:
            selected_recent = st.selectbox("Select Recent Session Trace:", options=["-- Pick a recent trace --"] + recent_list)
            if selected_recent != "-- Pick a recent trace --":
                target_trace = selected_recent
        else:
            st.info("💡 Send a message in the Chat tab first, or type a Trace ID manually below.")

    manual_trace = st.text_input("Or Enter Any Trace ID Manually:", value=target_trace)
    inspect_id = manual_trace.strip()

    if st.button("🔎 Fetch Audit Record", type="primary"):
        if not inspect_id:
            st.warning("Please enter or select a Trace ID.")
        else:
            try:
                headers = {"X-Admin-Key": ADMIN_KEY}
                res = requests.get(f"{API_BASE}/audit/{inspect_id}", headers=headers, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    rec = data.get("record", {})
                    
                    st.success(f"✅ Audit Record Found for Trace `{data.get('trace_id')}`")

                    # Key Metrics Row
                    mcol1, mcol2, mcol3, mcol4 = st.columns(4)
                    mcol1.metric("Customer ID", rec.get("customer_id") or "Anonymous")
                    mcol2.metric("Intent Category", rec.get("question_category") or "general")
                    mcol3.metric("Answer Type", rec.get("answer_type") or "N/A")
                    mcol4.metric("Timestamp (UTC)", rec.get("timestamp") or "N/A")

                    # Audit Breakdown Cards
                    st.markdown("#### 🛡️ Decision & Enforcement Trail")
                    
                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        st.markdown("**Question Sanitized (PII-Safe):**")
                        st.code(rec.get("question_redacted", ""), language="text")
                        
                        st.markdown("**Sources Retrieved from Knowledge Base:**")
                        sources = rec.get("sources_retrieved", [])
                        if sources:
                            for s in sources:
                                st.markdown(f"- 📄 `{s}`")
                        else:
                            st.caption("None (Deterministic tool or refusal)")

                    with col_d2:
                        st.markdown("**Applied Rules & Precedence:**")
                        rules = rec.get("applied_rules", [])
                        if rules:
                            for r in rules:
                                st.markdown(f"- ⚖️ Rule `{r.get('rule_id')}`: Value `{r.get('value')}` (Source: `{r.get('source_doc_id')}`)")
                        else:
                            st.caption("No rule registry clauses triggered.")

                        decisions = rec.get("precedence_decisions", [])
                        if decisions:
                            st.markdown("**Precedence Decisions:**")
                            for dec in decisions:
                                st.markdown(f"- 🏆 {dec}")

                    st.markdown("#### 🛠️ Deterministic Tool Execution Log")
                    tools = rec.get("tools_invoked", [])
                    if tools:
                        st.json(tools)
                    else:
                        st.caption("No deterministic math tools were executed for this query.")

                    with st.expander("📄 View Full Raw Audit JSON (Contract Payload)"):
                        st.json(data)
                elif res.status_code == 404:
                    st.error(f"Trace `{inspect_id}` not found in the SQLite `audit_log` table.")
                elif res.status_code == 403:
                    st.error("403 Forbidden: You do not have permission to view this trace without an admin key.")
                else:
                    st.error(f"Error ({res.status_code}): {res.text}")
            except Exception as e:
                st.error(f"Failed to connect to API: {e}")

with tab_ingest:
    st.subheader("📄 Live Document & Rule Ingestion (Panelist Testing)")
    st.write("Upload a new circular or policy document live without restarting the server.")

    uploaded_file = st.file_uploader("Upload Policy / Circular Document", type=["md", "txt", "docx", "pdf", "html"])

    col1, col2 = st.columns(2)
    with col1:
        doc_id = st.text_input("doc_id", value="CIRC-2026-10")
        title = st.text_input("Document Title", value="Electronics Return Window Amendment")
        authority = st.selectbox("Authority Level", options=[1, 2, 3, 4, 5], index=1)
        doc_type = st.selectbox("Doc Type", options=["circular", "regulation", "notice", "faq"])
    with col2:
        effective_from = st.text_input("Effective From (YYYY-MM-DD)", value="2026-10-01")
        supersedes = st.text_input("Supersedes (e.g. CIRC-2026-07)", value="CIRC-2026-07")
        scope_cat = st.selectbox("Scope Categories", options=["ELECTRONICS", "FASHION", "HOME", "BEAUTY", "GROCERY", "ALL"])
        version = st.text_input("Version", value="1.0")

    optional_rules = st.text_area("Optional Rules JSON (leave blank to use Auto-Extractor)", value="")

    if st.button("🚀 Ingest Document Live", type="primary"):
        if not uploaded_file:
            st.warning("Please choose a file to upload.")
        else:
            meta_json = json.dumps({
                "doc_id": doc_id,
                "title": title,
                "authority_level": authority,
                "doc_type": doc_type,
                "version": version,
                "effective_from": effective_from,
                "supersedes": supersedes,
                "scope_categories": scope_cat,
                "scope_tiers": "ALL"
            })
            files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
            data_fields = {"metadata": meta_json}
            if optional_rules.strip():
                data_fields["rules"] = optional_rules.strip()

            with st.spinner("Ingesting and updating index + rule registry..."):
                try:
                    res = requests.post(f"{API_BASE}/ingest", files=files, data=data_fields, timeout=60)
                    if res.status_code == 200:
                        st.success("✅ Ingestion Successful!")
                        st.json(res.json())
                    else:
                        st.error(f"Ingestion failed: {res.text}")
                except Exception as e:
                    st.error(f"Error calling ingest API: {e}")
