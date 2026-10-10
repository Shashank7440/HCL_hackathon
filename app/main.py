"""FastAPI app. Exact contract paths; no prefix. /ask never returns an error envelope."""
from __future__ import annotations
import csv, io, json, tempfile
from datetime import date
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse

from . import constants
from .config import settings
from .db import get_conn, init_schema
from .schemas import (AskRequest, AskResponse, IngestResponse, SourceDoc, AuditResponse,
                      ErrorEnvelope, Citation, ToolInvoked, AppliedRule, ConflictDetected, UpcomingChange)
from .agent.graph import build_graph
from .ingestion.pipeline import ingest_document, parse_rules_field, META_FIELDS
from .audit import build_record, store_record
from .security import known_customer

app = FastAPI(title="AI-Powered Retail Customer Support Agent", version="0.1.0")
graph = build_graph()
init_schema()

def _error(status: int, code: str, message: str, detail=None):
    return JSONResponse(status_code=status,
                        content=ErrorEnvelope(error={"code": code, "message": message, "detail": detail}).model_dump())

@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))

@app.get("/")
def root():
    return {
        "service": "ShopEasy Retail Support Agent API",
        "status": "online",
        "docs": "/docs",
        "ui": "http://localhost:8501",
        "endpoints": {
            "ask": "POST /ask",
            "health": "GET /health",
            "ingest": "POST /ingest",
            "sources": "GET /sources",
            "audit": "GET /audit/{trace_id}"
        }
    }

_last_llm_check = 0.0
_last_llm_ok = False

def check_llm_live() -> bool:
    global _last_llm_check, _last_llm_ok
    import time
    now = time.time()
    if now - _last_llm_check < 60:
        return _last_llm_ok
    _last_llm_check = now
    if settings.MOCK_LLM:
        _last_llm_ok = True
        return True
    import urllib.request
    try:
        urllib.request.urlopen(f"{settings.OLLAMA_HOST}/api/tags", timeout=0.3)
        _last_llm_ok = True
    except Exception:
        _last_llm_ok = False
    return _last_llm_ok

@app.get("/health")
def health():
    conn = get_conn()
    try:
        db_ok = conn.execute("SELECT 1").fetchone() is not None
    except Exception:
        db_ok = False
    llm_ok = check_llm_live()

    from .retrieval.store import VectorStore
    store = VectorStore(conn)
    store_ok = (store.client is not None and not store.last_error)
    retrieval_mode = "semantic" if store_ok else "keyword-fallback"

    try:
        details = {"llm_provider": settings.LLM_PROVIDER, "model": settings.OLLAMA_MODEL,
                   "mock_llm": settings.MOCK_LLM,
                   "retrieval_mode": retrieval_mode,
                   "documents": conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"],
                   "chunks": conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"],
                   "rules": conn.execute("SELECT COUNT(*) c FROM rule_registry").fetchone()["c"],
                   "customers": conn.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"]}
    finally:
        conn.close()
    overall_ok = db_ok and store_ok
    return {"status": "ok" if overall_ok else "degraded", "api": True, "sqlite": db_ok,
            "vector_store": store_ok, "llm": llm_ok, "details": details}

@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest,
        x_customer_id: str | None = Header(default=None)):
    import time
    t0 = time.perf_counter()
    state = {"question": body.question, "customer_id": x_customer_id,
             "as_of_date": body.as_of_date.isoformat() if body.as_of_date else date.today().isoformat(),
             "t0": t0}
    result = graph.execute(state)
    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    conn = get_conn()
    try:
        store_record(conn, result)
    finally:
        conn.close()
    return AskResponse(
        trace_id=result["trace_id"], answer=result.get("answer", constants.NOT_FOUND_MSG),
        answer_type=result.get("answer_type", "not_found"),
        citations=[Citation(**c) for c in result.get("citations", [])],
        tools_invoked=[ToolInvoked(**t) for t in result.get("tools_invoked", [])],
        applied_rules=[AppliedRule(rule_id=r["rule_id"], value=str(r.get("value","")),
                                   source_doc_id=r.get("source_doc_id","")) for r in result.get("applied_rules", [])],
        conflicts_detected=[ConflictDetected(**c) for c in result.get("conflicts_detected", [])],
        assumptions=result.get("assumptions", []),
        explanation=result.get("explanation", ""),
        as_of_date=result["as_of_date"],
        upcoming_changes=[UpcomingChange(**u) for u in result.get("upcoming_changes", []) if u.get("rule_id")])

async def _field_or_file(form_str: str | None, file: UploadFile | None):
    if form_str is not None: return form_str
    if file is not None: return (await file.read()).decode("utf-8", errors="ignore")
    return None

@app.post("/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile = File(...),
                 metadata: str | None = Form(default=None),
                 metadata_file: UploadFile | None = File(default=None),
                 rules: str | None = Form(default=None),
                 rules_file: UploadFile | None = File(default=None)):
    meta_raw = await _field_or_file(metadata, metadata_file)
    rules_raw = await _field_or_file(rules, rules_file)
    try:
        metadata_obj = json.loads(meta_raw) if meta_raw else None
    except json.JSONDecodeError:
        raise HTTPException(422, "VALIDATION_ERROR: metadata is not valid JSON")
    if not metadata_obj: raise HTTPException(422, "VALIDATION_ERROR: metadata required")
    try:
        from .schemas import IngestMetadata
        valid_meta = IngestMetadata(**metadata_obj)
        metadata_dict = valid_meta.model_dump()
        metadata_dict["effective_from"] = valid_meta.effective_from.isoformat()
        if valid_meta.effective_to:
            metadata_dict["effective_to"] = valid_meta.effective_to.isoformat()
    except Exception as e:
        raise HTTPException(422, f"VALIDATION_ERROR: {e}")
    try:
        rules_obj = parse_rules_field(rules_raw)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"VALIDATION_ERROR: {e}")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf",".docx",".txt",".md",".html",".htm"):
        raise HTTPException(400, "UNSUPPORTED_FILE_TYPE")
    tmp = Path(tempfile.gettempdir()) / (file.filename or "upload")
    tmp.write_bytes(await file.read())
    conn = get_conn()
    try:
        from .retrieval.store import VectorStore
        out = ingest_document(conn, VectorStore(conn), str(tmp), file.filename, metadata_dict, rules_obj)
        if out["chunks_indexed"] == 0: raise HTTPException(422, "EMPTY_DOCUMENT")
        return IngestResponse(**out)
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        conn.close(); tmp.unlink(missing_ok=True)

@app.get("/sources")
def sources():
    conn = get_conn()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM documents ORDER BY doc_id")]
        return [SourceDoc(**r).model_dump() for r in rows]
    finally:
        conn.close()

@app.get("/audit/{trace_id}", response_model=AuditResponse)
def audit(trace_id: str, x_customer_id: str | None = Header(default=None),
          x_admin_key: str | None = Header(default=None)):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM audit_log WHERE trace_id = ?", (trace_id,)).fetchone()
        if not row: raise HTTPException(404, "NOT_FOUND: no such trace")
        rec = json.loads(row["record_json"])
        owner = row["customer_id"]
        if owner and x_customer_id != owner and x_admin_key != settings.ADMIN_KEY:
            raise HTTPException(403, "FORBIDDEN: not your trace (admin key required)")
        return AuditResponse(trace_id=row["trace_id"], timestamp=rec.get("timestamp",""),
                             customer_id=owner, record=rec)
    finally:
        conn.close()

@app.post("/admin/load-data")
async def load_data(request: Request):
    """Judge test-data loader: JSON body {table: rows[]} or multipart CSV files."""
    rows_by_table, order = {}, []
    ctype = request.headers.get("content-type", "")
    if "multipart" in ctype:
        form = await request.form()
        for name, part in form.items():
            if hasattr(part, "read"):
                text = (await part.read()).decode("utf-8", errors="ignore")
                table = (name or part.filename or "").replace(".csv","")
                rows_by_table[table] = list(csv.DictReader(io.StringIO(text)))
    else:
        body = await request.json()
        rows_by_table = body
    from scripts.load_data import upsert_rows      # reuse the loader (upsert, reserved ids accepted)
    conn = get_conn()
    try:
        counts = {}
        for table in ("products","customers","orders","order_items","returns"):
            rows = rows_by_table.get(table) or []
            if rows: counts[table] = upsert_rows(conn, table, rows)
        conn.commit()
        return {"status": "loaded", "counts": counts}
    finally:
        conn.close()
