import datetime
import logging
from typing import Dict, List, Optional, Any
from app.workspace_service import WorkspaceService

logger = logging.getLogger("session_manager")

class ReviewSession:
    def __init__(self, doc_id: str, workspace_service: WorkspaceService):
        self.doc_id = doc_id
        self.workspace_service = workspace_service
        self.title: str = "Loading..."
        self.backup_info: Optional[Dict[str, Any]] = None
        self.paragraphs: List[Dict[str, Any]] = []
        self.current_paragraph_idx: int = 0
        self.is_reading: bool = False
        self.is_paused: bool = False
        self.edits_history: List[Dict[str, Any]] = []
        self.created_at: str = datetime.datetime.now().isoformat()

    async def initialize(self) -> Dict[str, Any]:
        doc_data = await self.workspace_service.get_document(self.doc_id)
        self.title = doc_data.get("title", "Untitled Document")
        self.paragraphs = doc_data.get("paragraphs", [])
        
        # Enforce Safe Versioning: Clone Pre-Review Backup in Drive
        self.backup_info = await self.workspace_service.create_pre_review_backup(
            file_id=self.doc_id,
            original_title=self.title
        )
        
        self.current_paragraph_idx = 0
        self.is_reading = False
        self.is_paused = False
        return self.get_state()

    def get_current_paragraph(self) -> Optional[Dict[str, Any]]:
        if 0 <= self.current_paragraph_idx < len(self.paragraphs):
            return self.paragraphs[self.current_paragraph_idx]
        return None

    def advance_paragraph(self) -> Optional[Dict[str, Any]]:
        if self.current_paragraph_idx < len(self.paragraphs) - 1:
            self.current_paragraph_idx += 1
            return self.get_current_paragraph()
        return None

    def seek_paragraph(self, index: int) -> Optional[Dict[str, Any]]:
        if 0 <= index < len(self.paragraphs):
            self.current_paragraph_idx = index
            return self.get_current_paragraph()
        return None

    async def revise_current_paragraph(self, replacement_text: str) -> Dict[str, Any]:
        current_para = self.get_current_paragraph()
        if not current_para:
            raise ValueError("No active paragraph selected for revision.")

        para_id = current_para["paragraph_id"]
        original_text = current_para["text"]

        edit_result = await self.workspace_service.apply_in_line_edit(
            doc_id=self.doc_id,
            paragraph_id=para_id,
            original_text=original_text,
            replacement_text=replacement_text,
            start_index=current_para.get("start_index"),
            end_index=current_para.get("end_index")
        )

        record = {
            "paragraph_id": para_id,
            "original_text": original_text,
            "revised_text": replacement_text,
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.edits_history.append(record)
        current_para["text"] = replacement_text

        # Keep indices up to date
        refreshed = await self.workspace_service.get_document(self.doc_id)
        self.paragraphs = refreshed.get("paragraphs", self.paragraphs)

        return record

    def get_state(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "backup_info": self.backup_info,
            "total_paragraphs": len(self.paragraphs),
            "current_paragraph_index": self.current_paragraph_idx,
            "current_paragraph": self.get_current_paragraph(),
            "is_reading": self.is_reading,
            "is_paused": self.is_paused,
            "edits_count": len(self.edits_history),
            "recent_edits": self.edits_history[-5:],
            "paragraphs": self.paragraphs
        }

class SessionRegistry:
    def __init__(self):
        self._sessions: Dict[str, ReviewSession] = {}

    def get_or_create(self, doc_id: str, workspace_service: WorkspaceService) -> ReviewSession:
        if doc_id not in self._sessions:
            self._sessions[doc_id] = ReviewSession(doc_id, workspace_service)
        return self._sessions[doc_id]

    def get(self, doc_id: str) -> Optional[ReviewSession]:
        return self._sessions.get(doc_id)

    def remove(self, doc_id: str):
        if doc_id in self._sessions:
            del self._sessions[doc_id]

session_registry = SessionRegistry()
