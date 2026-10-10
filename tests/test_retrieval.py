"""Retrieval tests: semantic search, paraphrase coverage, unknown entity abstention (R1-R3)."""
import sys, os, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_FILE = str(Path(tempfile.gettempdir()) / "test_retrieval_shopeasy.db")
os.environ["DB_PATH"] = DB_FILE
if Path(DB_FILE).exists():
    Path(DB_FILE).unlink()

from app.db import get_conn
from app.retrieval.store import VectorStore
from app.retrieval.retriever import Retriever
from scripts.seed import seed

seed(DB_FILE)
conn = get_conn(DB_FILE)
retriever = Retriever(conn)
AS_OF = "2026-10-06"

def test_paraphrase_gadget_retrieval():
    hits = retriever.search("How long do I have to send back a gadget?", as_of=AS_OF, top_k=4)
    assert len(hits) > 0
    assert any(h["doc_id"] == "CIRC-2026-07" for h in hits)

def test_unknown_entity_abstention():
    # Antarctica, Amazon, CEO phone number must return empty hits
    assert retriever.search("Do you deliver to Antarctica?", as_of=AS_OF) == []
    assert retriever.search("Can I return items bought on Amazon?", as_of=AS_OF) == []
    assert retriever.search("What is the phone number of the CEO?", as_of=AS_OF) == []

def test_chroma_metadata_effective_date_ints():
    store = VectorStore(conn)
    chunk = {"chunk_id": "test_chunk_1", "doc_id": "TEST-DOC", "title": "Test Title",
             "section": "1", "page": 1, "version": "1.0", "authority_level": 2,
             "effective_from": "2026-10-01", "effective_to": "2026-12-31",
             "scope_categories": "ALL", "scope_tiers": "ALL", "text": "Sample text for chunk testing."}
    meta = store._chroma_meta(chunk)
    assert meta["eff_from_i"] == 20261001
    assert meta["eff_to_i"] == 20261231
    assert isinstance(meta["eff_from_i"], int)
    assert isinstance(meta["eff_to_i"], int)

def test_reingest_deletes_old_chunks():
    store = VectorStore(conn)
    c1 = {"chunk_id": "docA_chunk1", "doc_id": "DOC-A", "text": "First version text",
          "effective_from": "2026-01-01", "effective_to": "2026-12-31"}
    store.upsert_chunks([c1])
    assert conn.execute("SELECT COUNT(*) c FROM chunks WHERE doc_id = 'DOC-A'").fetchone()["c"] == 1
    store.delete_doc("DOC-A")
    assert conn.execute("SELECT COUNT(*) c FROM chunks WHERE doc_id = 'DOC-A'").fetchone()["c"] == 0
