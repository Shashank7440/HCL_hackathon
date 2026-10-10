"""ShopEasy Retail Support Agent - Modern Streamlit Interface.
Thin client connecting to the FastAPI backend (Section 6 contract).
Supports live chat, quick sample scenarios, audit inspection, and panelist live document ingestion.
"""
import json, os, requests, streamlit as st

st.set_page_config(
    page_title="ShopEasy Retail AI Support Agent",
    page_icon="🛍️",
    layout="wide"
)

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
try:
    if "API_BASE" in st.secrets:
        API_BASE = st.secrets["API_BASE"]
except Exception:
    pass

# Header & Branding
st.markdown("""
<div style="padding: 10px 0px 20px 0px;">
    <h1 style="margin: 0; color: #1E293B;">🛍️ ShopEasy AI Retail Support Agent</h1>
    <p style="margin: 5px 0 0 0; color: #64748B; font-size: 1.05rem;">
        Multi-Agent Retail Support with Annex A Source Precedence, Deterministic Tools, and Auditability.
    </p>
</div>
""", unsafe_allow_html=True)

# Sidebar: Identity & Configuration
with st.sidebar:
    st.header("🔑 Customer Context")
    st.info("Identity comes ONLY from the `X-Customer-Id` header (R7 Privacy).")
    
    preset_customer = st.selectbox(
        "Select Demo Customer:",
        options=["C1001 (Standard - O-100001)", "C1010 (Gold Member - Fee Waiver)", "C1009 (Ambiguous Orders - Headphones)", "Guest (No Header)", "Custom"]
    )
    
    if preset_customer.startswith("C1001"):
        default_cid = "C1001"
    elif preset_customer.startswith("C1010"):
        default_cid = "C1010"
    elif preset_customer.startswith("C1009"):
        default_cid = "C1009"
    elif preset_customer.startswith("Guest"):
        default_cid = ""
    else:
        default_cid = "C1001"

    customer_id = st.text_input("X-Customer-Id Header", value=default_cid)
    as_of = st.date_input("As-Of Date (Simulation)", value=None)
    as_of_str = as_of.isoformat() if as_of else "2026-10-06"
    
    st.divider()
    
    # System Status Indicator
    try:
        h = requests.get(f"{API_BASE}/health", timeout=2).json()
        if h.get("status") == "ok":
            st.success("🟢 API Server: Online")
        else:
            st.warning("🟡 API Server: Degraded")
    except Exception:
        st.error("🔴 API Server: Offline (Start on :8000)")

    st.divider()
    st.subheader("⚡ Quick Test Scenarios")
    quick_queries = [
        ("Return Window (Electronics)", "What is the return window for electronics?"),
        ("Refund Calculation", "How much refund will I get for order O-100001?"),
        ("Multi-Step Reasoning", "My headphones stopped working after 41 days. Can I return them, and if not, what can I do?"),
        ("Privacy Violation Attempt", "Where is my order O-100002?"),
        ("Unanswerable / Abstention", "Do you deliver to Antarctica?"),
        ("What-If Simulation", "What if I were a Gold member for order O-100001?"),
        ("Ambiguity Disambiguation", "Can I return my headphones?"),
    ]
    for label, query_text in quick_queries:
        if st.button(label, use_container_width=True):
            st.session_state["preset_input"] = query_text

# Main tabs: Chat vs Live Document Ingestion vs Audit Inspector
tab_chat, tab_ingest, tab_audit = st.tabs(["💬 Customer Support Chat", "📄 Panelist Document Ingest", "🔍 Audit Trace Inspector"])

with tab_chat:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"], unsafe_allow_html=True)
            if "extra" in m:
                d = m["extra"]
                cols = st.columns(3)
                cols[0].metric("Answer Type", d.get("answer_type", "N/A"))
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

    user_query = st.chat_input("Ask about return windows, refunds, warranty, or order status...")
    if "preset_input" in st.session_state and st.session_state["preset_input"]:
        user_query = st.session_state.pop("preset_input")

    if user_query:
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            with st.spinner("Processing through Multi-Agent System..."):
                try:
                    headers = {"X-Customer-Id": customer_id} if customer_id else {}
                    payload = {"question": user_query, "as_of_date": as_of_str}
                    res = requests.post(f"{API_BASE}/ask", json=payload, headers=headers, timeout=60)
                    data = res.json()
                    
                    ans = data.get("answer", "")
                    st.markdown(ans)
                    
                    cols = st.columns(3)
                    cols[0].metric("Answer Type", data.get("answer_type", "N/A"))
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

with tab_ingest:
    st.subheader("Live Document & Rule Ingestion (Panelist Testing)")
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
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "text/plain")}
            data_fields = {"metadata": meta_json}
            if optional_rules.strip():
                data_fields["rules"] = optional_rules.strip()
            
            with st.spinner("Ingesting document, chunking, and updating rule registry..."):
                try:
                    resp = requests.post(f"{API_BASE}/ingest", files=files, data=data_fields, timeout=60)
                    if resp.status_code == 200:
                        st.success(f"✅ Ingestion Successful! {resp.json()}")
                    else:
                        st.error(f"Ingestion failed ({resp.status_code}): {resp.text}")
                except Exception as e:
                    st.error(f"Ingestion error: {e}")

with tab_audit:
    st.subheader("Audit Log & Trace Record Inspector")
    st.caption("Inspect full tamper-proof audit records stored in SQLite for any trace ID.")
    trace_query = st.text_input("Enter Trace ID to Inspect:")
    if st.button("Inspect Audit Record"):
        if trace_query:
            try:
                headers = {"X-Admin-Key": "admin-demo-key"}
                resp = requests.get(f"{API_BASE}/audit/{trace_query.strip()}", headers=headers, timeout=10)
                if resp.status_code == 200:
                    st.json(resp.json())
                else:
                    st.error(f"Audit lookup returned status {resp.status_code}: {resp.text}")
            except Exception as e:
                st.error(f"Audit lookup failed: {e}")
