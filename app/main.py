import os
import sys

# Ensure direct file lookup for modules regardless of filesystem caching
class DirectFinder:
    def find_spec(self, fullname, path, target=None):
        import importlib.util
        if path is None:
            path = sys.path
        parts = fullname.split('.')
        for p in path:
            candidate = os.path.join(p, *parts)
            if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, '__init__.py')):
                return importlib.util.spec_from_file_location(fullname, os.path.join(candidate, '__init__.py'), submodule_search_locations=[candidate])
            file_cand = candidate + '.py'
            if os.path.exists(file_cand):
                return importlib.util.spec_from_file_location(fullname, file_cand)
        return None

sys.meta_path.insert(0, DirectFinder())
sys.path.insert(0, '/working_dir/c_8afa272a78346a93/legal_voice_review')

import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.config import settings
from app.workspace_service import WorkspaceService
from app.session_manager import session_registry
from app.gemini_live_bridge import GeminiLiveBridge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("legal_voice_review")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Full-duplex verbal review & revision PWA for Google Docs legal drafts on iPhone."
)

# Workspace service singleton (configured with user's OAuth token if present)
workspace_service = WorkspaceService(access_token=settings.GOOGLE_OAUTH_TOKEN or None)

# Request Models
class StartSessionRequest(BaseModel):
    doc_id: str

class ManualEditRequest(BaseModel):
    revised_text: str

class SeekParagraphRequest(BaseModel):
    index: int

# --- REST Endpoints ---

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "mode": "live" if settings.GEMINI_API_KEY else "simulation_ready"
    }

@app.get("/api/documents")
async def list_documents():
    """Lists available legal drafts from Google Drive."""
    try:
        docs = await workspace_service.list_drive_documents()
        return {"documents": docs}
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sessions/start")
async def start_review_session(req: StartSessionRequest):
    """
    Initializes a verbal review session:
    1. Fetches document paragraphs from Google Docs.
    2. Enforces Safe Versioning: Clones an immutable pre-review backup in Google Drive.
    """
    try:
        session = session_registry.get_or_create(req.doc_id, workspace_service)
        state = await session.initialize()
        return {
            "message": "Review session started. Pre-review backup created.",
            "state": state
        }
    except Exception as e:
        logger.error(f"Error starting session for doc {req.doc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions/{doc_id}")
async def get_session_state(doc_id: str):
    session = session_registry.get(doc_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Please start session first.")
    return session.get_state()

@app.post("/api/sessions/{doc_id}/seek")
async def seek_paragraph(doc_id: str, req: SeekParagraphRequest):
    session = session_registry.get(doc_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    para = session.seek_paragraph(req.index)
    return {"current_paragraph": para, "current_index": session.current_paragraph_idx}

@app.post("/api/sessions/{doc_id}/edit")
async def apply_manual_edit(doc_id: str, req: ManualEditRequest):
    session = session_registry.get(doc_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    record = await session.revise_current_paragraph(req.revised_text)
    return {"message": "Paragraph revised cleanly in Google Docs.", "edit": record, "state": session.get_state()}

# --- WebSocket Live Audio & Voice Review Endpoint ---

@app.websocket("/ws/review/{doc_id}")
async def review_websocket_endpoint(websocket: WebSocket, doc_id: str):
    await websocket.accept()
    logger.info(f"iPhone client connected to WebSocket review session for doc {doc_id}")

    session = session_registry.get_or_create(doc_id, workspace_service)
    if not session.paragraphs:
        await session.initialize()

    bridge = GeminiLiveBridge(session, websocket)

    try:
        # Run live or simulated conversational review loop
        await bridge.run_fallback_simulation()
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from doc {doc_id} review session.")
    except Exception as e:
        logger.error(f"WebSocket error in review session: {e}")
        await websocket.close()

# --- Serve iPhone Progressive Web App (PWA) ---

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")

if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(frontend_path, "index.html"))

    @app.get("/manifest.json")
    async def serve_manifest():
        return FileResponse(os.path.join(frontend_path, "manifest.json"))

    @app.get("/sw.js")
    async def serve_sw():
        return FileResponse(os.path.join(frontend_path, "sw.js"), media_type="application/javascript")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
