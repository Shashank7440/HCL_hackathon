"""ShopEasy Retail Support Agent - Modern Streamlit Interface.
Ultra-fast, typo-tolerant, thin client connecting to the FastAPI backend (Section 6 contract).
Supports live chat, quick scenarios, audit inspection, and panelist live document ingestion.
"""
import json, os, requests, streamlit as st

st.set_page_config(
    page_title="ShopEasy Retail AI Support Agent",
    page_icon="🛍️",
    layout="wide"
)

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
try:
    if hasattr(st, "secrets"):
        API_BASE = st.secrets.get("API_BASE", API_BASE)
except BaseException:
    API_BASE = os.getenv("API_BASE", "http://localhost:8000")

# Cached health check so UI never blocks or lags
@st.cache_data(ttl=30)
def get_api_health(base_url: str):
    try:
        r = requests.get(f"{base_url}/health", timeout=1)
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
<div style="background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%); padding: 18px 24px; border-radius: 12px; margin-bottom: 20px; color: white;">
    <h2 style="margin: 0; font-weight: 700; color: #F8FAFC;">🛍️ ShopEasy AI Retail Support Agent</h2>
    <p style="margin: 6px 0 0 0; color: #94A3B8; font-size: 0.95rem;">
        Multi-Agent Architecture · Annex A Source Precedence · Deterministic Code Tools · Typo-Tolerant
    </p>
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
    <div style="background: #F1F5F9; padding: 12px; border-radius: 8px; border-left: 4px solid #3B82F6; margin-top: 8px;">
        <div style="font-weight: 600; color: #1E293B;">{c_info['name']} ({active_cid or 'Guest'})</div>
        <div style="font-size: 0.85rem; color: #475569;"><b>Tier:</b> {c_info['tier']}</div>
        <div style="font-size: 0.85rem; color: #475569;"><b>Orders:</b> {c_info['orders']}</div>
        <div style="font-size: 0.8rem; color: #64748B; margin-top: 4px;"><i>{c_info['expected']}</i></div>
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
        ("Return Window (Electronics)", "What is the return window for electronics?"),
        ("Typo Handling Demo", "What is the reutrn window for electornics?"),
        ("Refund Calculation (O-100001)", "How much refund will I get for order O-100001?"),
        ("Multi-Step Reasoning", "My headphones stopped working after 41 days. Can I return them, and if not, what can I do?"),
        ("Privacy Violation Refusal", "Where is my order O-100002?"),
        ("Unanswerable / Abstention", "Do you deliver to Antarctica?"),
        ("Gold Member What-If", "What if I were a Gold member for order O-100001?"),
        ("Ambiguity Disambiguation", "Can I return my headphones?"),
    ]
    for label, query_text in quick_queries:
        if st.button(label, use_container_width=True):
            st.session_state["preset_input"] = query_text

# Main Tabs
tab_chat, tab_ingest, tab_audit, tab_db = st.tabs([
    "💬 Customer Support Chat",
    "📄 Panelist Document Ingest",
    "🔍 Audit Trace Inspector",
    "🗄️ Database Explorer"
])

with tab_chat:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display Chat History
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"], unsafe_allow_html=True)
            if "extra" in m:
                d = m["extra"]
                cols = st.columns(3)
                atype = d.get("answer_type", "N/A")
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

                    cols = st.columns(3)
                    atype = data.get("answer_type", "N/A")
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
    st.subheader("🔍 Audit Log & Trace Record Inspector")
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

with tab_db:
    st.subheader("🗄️ SQLite Database Explorer (`data/app.db`)")
    st.caption("Browse, inspect, and query the underlying relational tables directly without needing external tools.")

    import sqlite3, pandas as pd
    from app.config import settings

    try:
        conn = sqlite3.connect(settings.DB_PATH)
        
        # Summary Metrics
        m1, m2, m3, m4 = st.columns(4)
        c_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        o_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        p_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        r_count = conn.execute("SELECT COUNT(*) FROM rule_registry").fetchone()[0]
        m1.metric("Customers", c_count)
        m2.metric("Orders", o_count)
        m3.metric("Products", p_count)
        m4.metric("Active Rules", r_count)

        st.divider()

        tables = ["customers", "orders", "order_items", "products", "returns", "rule_registry", "audit_log", "documents", "chunks"]
        selected_tbl = st.selectbox("Select Table to View:", options=tables, index=0)

        # Search filter
        search_kw = st.text_input(f"Filter records in '{selected_tbl}' (search keyword):", value="")
        
        limit_n = st.slider("Max rows to display:", min_value=10, max_value=200, value=50, step=10)
        
        query = f"SELECT * FROM {selected_tbl}"
        if search_kw.strip():
            # Filter across columns
            df_full = pd.read_sql_query(query, conn)
            mask = df_full.astype(str).apply(lambda col: col.str.contains(search_kw.strip(), case=False, na=False)).any(axis=1)
            df = df_full[mask].head(limit_n)
            st.info(f"Showing {len(df)} matching rows (out of {len(df_full)} total)")
        else:
            df = pd.read_sql_query(f"{query} LIMIT {limit_n}", conn)
            st.caption(f"Showing top {len(df)} rows")

        st.dataframe(df, use_container_width=True)

        # Download CSV button
        csv_data = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label=f"📥 Download {selected_tbl}.csv",
            data=csv_data,
            file_name=f"{selected_tbl}.csv",
            mime="text/csv",
        )

        st.divider()
        st.subheader("⚡ Execute Custom Read-Only SQL Query")
        custom_sql = st.text_area(
            "SQL Query (SELECT only):",
            value=f"SELECT * FROM orders WHERE customer_id = '{active_cid if active_cid else 'C1001'}' LIMIT 10"
        )
        if st.button("Run SQL Query"):
            sql_clean = custom_sql.strip()
            if not sql_clean.lower().startswith("select"):
                st.error("Only SELECT queries are allowed in this explorer for safety.")
            else:
                try:
                    res_df = pd.read_sql_query(sql_clean, conn)
                    st.success(f"Returned {len(res_df)} rows")
                    st.dataframe(res_df, use_container_width=True)
                except Exception as sql_err:
                    st.error(f"SQL Error: {sql_err}")

        conn.close()
    except Exception as db_err:
        st.error(f"Database connection error: {db_err}")

