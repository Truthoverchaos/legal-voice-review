import asyncio
import sys
import os
import importlib.util

class DirectFinder:
    def find_spec(self, fullname, path, target=None):
        search_paths = sys.path if path is None else path
        mod_name = fullname.split('.')[-1]
        for p in search_paths:
            pkg_init = os.path.join(p, mod_name, '__init__.py')
            if os.path.exists(pkg_init):
                return importlib.util.spec_from_file_location(fullname, pkg_init, submodule_search_locations=[os.path.join(p, mod_name)])
            file_cand = os.path.join(p, mod_name + '.py')
            if os.path.exists(file_cand):
                return importlib.util.spec_from_file_location(fullname, file_cand)
        return None

sys.meta_path.insert(0, DirectFinder())
sys.path.insert(0, '/working_dir/c_8afa272a78346a93/legal_voice_review')

from app.workspace_service import WorkspaceService
from app.session_manager import ReviewSession, SessionRegistry
from app.main import app
from starlette.testclient import TestClient

async def test_workspace_service_and_versioning():
    print("--- 1. Testing WorkspaceService & Safe Versioning ---")
    ws = WorkspaceService()
    
    # 1. List documents
    docs = await ws.list_drive_documents()
    assert len(docs) >= 1, "Should list draft documents"
    print(f"✓ Found {len(docs)} documents in Drive. Sample: {docs[0]['name']}")

    # 2. Safe Versioning: Pre-review Backup Copy
    backup = await ws.create_pre_review_backup(docs[0]["id"], docs[0]["name"])
    assert backup["success"] is True
    assert "Pre-Review Backup" in backup["backup_title"]
    print(f"✓ Created pre-review backup copy: '{backup['backup_title']}'")

    # 3. Document Parsing
    doc = await ws.get_document(docs[0]["id"])
    assert "paragraphs" in doc
    assert len(doc["paragraphs"]) > 0
    print(f"✓ Parsed document '{doc['title']}' into {len(doc['paragraphs'])} paragraphs.")

    # 4. In-line text editing without track changes
    original_p = doc["paragraphs"][4]["text"]
    new_text = original_p + " [Revised: Specific agency record identification provided.]"
    edit_res = await ws.apply_in_line_edit(
        doc_id=docs[0]["id"],
        paragraph_id=4,
        original_text=original_p,
        replacement_text=new_text
    )
    assert edit_res["success"] is True
    print(f"✓ Clean in-line edit applied directly to doc.")

async def test_session_lifecycle():
    print("\n--- 2. Testing Review Session Lifecycle ---")
    ws = WorkspaceService()
    session = ReviewSession("doc_mandamus_001", ws)
    
    state = await session.initialize()
    assert state["current_paragraph_index"] == 0
    assert state["backup_info"] is not None
    print(f"✓ Session initialized. Current paragraph: '{session.get_current_paragraph()['text'][:40]}...'")

    # Advance
    session.advance_paragraph()
    assert session.current_paragraph_idx == 1
    print(f"✓ Advanced to paragraph 2")

    # Revise paragraph
    current_text = session.get_current_paragraph()["text"]
    revised = "CIVIL DIVISION - CASE NO.: 2026-CA-004521 (SECTION 119 MANDAMUS ENFORCEMENT)"
    edit_record = await session.revise_current_paragraph(revised)
    assert edit_record["revised_text"] == revised
    assert len(session.edits_history) == 1
    print(f"✓ Revised paragraph successfully. Edit record stored in history.")

def test_fastapi_rest_endpoints():
    print("\n--- 3. Testing FastAPI REST Endpoints ---")
    client = TestClient(app)
    
    # Health check
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    print("✓ GET /api/health passed")

    # Documents listing
    r = client.get("/api/documents")
    assert r.status_code == 200
    docs = r.json()["documents"]
    assert len(docs) > 0
    print(f"✓ GET /api/documents returned {len(docs)} files")

    # Start session
    r = client.post("/api/sessions/start", json={"doc_id": "doc_mandamus_001"})
    assert r.status_code == 200
    state = r.json()["state"]
    assert state["backup_info"] is not None
    print(f"✓ POST /api/sessions/start succeeded with automatic backup")

    # Seek
    r = client.post("/api/sessions/doc_mandamus_001/seek", json={"index": 2})
    assert r.status_code == 200
    assert r.json()["current_index"] == 2
    print(f"✓ POST /api/sessions/doc_mandamus_001/seek jumped to index 2")

    # In-line Edit endpoint
    r = client.post("/api/sessions/doc_mandamus_001/edit", json={"revised_text": "CHRISTOPHER HANSON, Petitioner, v. AGENCY HEAD, Respondent."})
    assert r.status_code == 200
    assert r.json()["edit"]["revised_text"].startswith("CHRISTOPHER HANSON")
    print(f"✓ POST /api/sessions/doc_mandamus_001/edit applied in-line edit")

    # Static index.html serve
    r = client.get("/")
    assert r.status_code == 200
    assert "Legal Voice" in r.text
    print(f"✓ GET / serves iPhone PWA index.html cleanly")

async def main():
    await test_workspace_service_and_versioning()
    await test_session_lifecycle()
    test_fastapi_rest_endpoints()
    print("\n=======================================================")
    print("ALL TESTS PASSED! APPLICATION VERIFIED 100% OPERATIONAL")
    print("=======================================================")

if __name__ == "__main__":
    asyncio.run(main())
