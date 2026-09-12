import datetime
import logging
import time
from typing import Dict, List, Optional, Any
import httpx

logger = logging.getLogger("workspace_service")

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

class DocumentParagraph:
    def __init__(self, paragraph_id: int, text: str, start_index: int, end_index: int, style: str = "NORMAL_TEXT"):
        self.paragraph_id = paragraph_id
        self.text = text
        self.start_index = start_index
        self.end_index = end_index
        self.style = style

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paragraph_id": self.paragraph_id,
            "text": self.text,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "style": self.style
        }

class WorkspaceService:
    """
    Handles Google Drive file operations and Google Docs structural parsing & batch editing.
    Enforces safe versioning:
      - Creates an immutable pre-review backup copy in Drive before editing begins.
      - Applies clean in-line edits directly to the working document (no track changes).
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        # access_token: a static bearer token (legacy path). Expires ~1 hour after
        # issuance and is never renewed -- only used when no refresh_token is configured.
        self.access_token = access_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._cached_access_token: Optional[str] = access_token
        self._token_expires_at: float = 0.0  # epoch seconds; 0 = never refreshed
        self.docs_base_url = "https://docs.googleapis.com/v1/documents"
        self.drive_base_url = "https://www.googleapis.com/drive/v3/files"

    @property
    def has_credentials(self) -> bool:
        """True if any auth path is configured (static token or refresh flow)."""
        return bool(self.access_token or self.refresh_token)

    async def _get_access_token(self) -> Optional[str]:
        """
        Returns a valid access token. If client_id/client_secret/refresh_token are
        all configured, proactively refreshes via Google's OAuth2 token endpoint
        (cached, refreshed 5 minutes before expiry) so the integration keeps working
        indefinitely. Falls back to a static access_token (e.g. one pasted directly
        into GOOGLE_OAUTH_TOKEN with no refresh token) if no refresh token is
        configured -- that path stops working ~1 hour after the token was issued.
        """
        if self.refresh_token and self.client_id and self.client_secret:
            if self._cached_access_token and time.time() < self._token_expires_at - 300:
                return self._cached_access_token
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": self.refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                self._cached_access_token = data["access_token"]
                self._token_expires_at = time.time() + data.get("expires_in", 3600)
                logger.info(
                    "Refreshed Google OAuth access token; expires in %s s",
                    data.get("expires_in"),
                )
                return self._cached_access_token
        return self.access_token

    async def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = await self._get_access_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def list_drive_documents(self) -> List[Dict[str, Any]]:
        """
        Lists editable Google Docs from Google Drive.
        """
        if not self.has_credentials:
            # Simulated legal draft files for demonstration/offline review
            return [
                {
                    "id": "doc_mandamus_001",
                    "name": "Petition for Writ of Mandamus - Public Records Compliance.docx",
                    "modifiedTime": "2026-09-10T14:30:00Z",
                    "webViewLink": "https://docs.google.com/document/d/doc_mandamus_001/edit"
                },
                {
                    "id": "doc_motion_limine_002",
                    "name": "Motion in Limine - Exclude Speculative Expert Testimony.docx",
                    "modifiedTime": "2026-09-08T11:15:00Z",
                    "webViewLink": "https://docs.google.com/document/d/doc_motion_limine_002/edit"
                },
                {
                    "id": "doc_settlement_agr_003",
                    "name": "Confidential Settlement Agreement & Mutual General Release.docx",
                    "modifiedTime": "2026-09-05T16:45:00Z",
                    "webViewLink": "https://docs.google.com/document/d/doc_settlement_agr_003/edit"
                }
            ]

        query = "mimeType = 'application/vnd.google-apps.document' and trashed = false"
        url = f"{self.drive_base_url}?q={query}&fields=files(id,name,modifiedTime,webViewLink)&orderBy=modifiedTime desc&pageSize=20"
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=await self._headers())
            resp.raise_for_status()
            data = resp.json()
            return data.get("files", [])

    async def create_pre_review_backup(self, file_id: str, original_title: str) -> Dict[str, Any]:
        """
        Clones the document in Google Drive before review begins.
        Format: "[Title] — Pre-Review Backup (YYYY-MM-DD HH:MM)"
        """
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        backup_title = f"{original_title} — Pre-Review Backup ({now_str})"
        
        logger.info(f"Cloning pre-review backup for '{original_title}' (ID: {file_id}) -> '{backup_title}'")
        
        if not self.has_credentials:
            return {
                "success": True,
                "backup_file_id": f"backup_{file_id}_{int(datetime.datetime.now().timestamp())}",
                "backup_title": backup_title,
                "original_file_id": file_id,
                "created_at": datetime.datetime.now().isoformat(),
                "mode": "simulated"
            }

        copy_url = f"{self.drive_base_url}/{file_id}/copy"
        payload = {
            "name": backup_title,
            "description": "Automated pre-review snapshot created by Legal Voice Review prior to verbal revision session."
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(copy_url, headers=await self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

            return {
                "success": True,
                "backup_file_id": data.get("id"),
                "backup_title": data.get("name"),
                "original_file_id": file_id,
                "created_at": datetime.datetime.now().isoformat(),
                "mode": "live"
            }

    async def get_document(self, doc_id: str) -> Dict[str, Any]:
        """
        Retrieves the Google Doc and parses it into a sequence of addressable paragraphs.
        """
        if not self.has_credentials:
            sample_paragraphs = [
                DocumentParagraph(0, "IN THE CIRCUIT COURT OF THE THIRTEENTH JUDICIAL CIRCUIT IN AND FOR HILLSBOROUGH COUNTY, FLORIDA", 1, 98, "HEADING_1"),
                DocumentParagraph(1, "CIVIL DIVISION - CASE NO.: 2026-CA-004521", 99, 140, "HEADING_2"),
                DocumentParagraph(2, "CHRISTOPHER HANSON, Petitioner, v. STATE AGENCY RECORDS CUSTODIAN, Respondent.", 141, 225, "NORMAL_TEXT"),
                DocumentParagraph(3, "VERIFIED PETITION FOR WRIT OF MANDAMUS TO ENFORCE PUBLIC RECORDS COMPLIANCE", 226, 301, "HEADING_1"),
                DocumentParagraph(4, "1. Petitioner, Christopher Hanson, petitions this Court for a Writ of Mandamus compelling Respondent to produce public records withheld in violation of Article I, Section 24(a) of the Florida Constitution and Chapter 119, Florida Statutes.", 302, 545, "NORMAL_TEXT"),
                DocumentParagraph(5, "2. On August 10, 2026, Petitioner submitted a written public records request to Respondent requesting all electronic correspondence and text messages between the Records Custodian and agency leadership regarding docket management.", 546, 786, "NORMAL_TEXT"),
                DocumentParagraph(6, "3. As of the date of this filing, more than thirty days have elapsed, and Respondent has failed to provide records, state an exemption, or provide the statutory citation supporting redaction.", 787, 982, "NORMAL_TEXT"),
                DocumentParagraph(7, "WHEREFORE, Petitioner respectfully requests that this Court issue an Alternative Writ of Mandamus directing Respondent to produce the requested records or show cause why it should not do so.", 983, 1177, "NORMAL_TEXT")
            ]
            return {
                "doc_id": doc_id,
                "title": "Petition for Writ of Mandamus - Public Records Compliance",
                "revision_id": "rev_local_01",
                "paragraphs": [p.to_dict() for p in sample_paragraphs]
            }

        url = f"{self.docs_base_url}/{doc_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=await self._headers())
            resp.raise_for_status()
            doc_data = resp.json()

        title = doc_data.get("title", "Untitled Document")
        body = doc_data.get("body", {})
        raw_elements = body.get("content", [])
        
        parsed_paragraphs = self._parse_structural_elements(raw_elements)
        return {
            "doc_id": doc_id,
            "title": title,
            "revision_id": doc_data.get("revisionId"),
            "paragraphs": [p.to_dict() for p in parsed_paragraphs]
        }

    def _parse_structural_elements(self, elements: List[Dict[str, Any]]) -> List[DocumentParagraph]:
        paragraphs: List[DocumentParagraph] = []
        p_idx = 0

        for elem in elements:
            if "paragraph" in elem:
                para = elem["paragraph"]
                elements_list = para.get("elements", [])
                text_runs = []
                for p_elem in elements_list:
                    if "textRun" in p_elem:
                        text_runs.append(p_elem["textRun"].get("content", ""))

                full_text = "".join(text_runs).strip()
                if not full_text:
                    continue

                start_idx = elem.get("startIndex", 0)
                end_idx = elem.get("endIndex", 0)
                named_style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")

                paragraphs.append(DocumentParagraph(
                    paragraph_id=p_idx,
                    text=full_text,
                    start_index=start_idx,
                    end_index=end_idx,
                    style=named_style
                ))
                p_idx += 1

        return paragraphs

    async def apply_in_line_edit(
        self,
        doc_id: str,
        paragraph_id: int,
        original_text: str,
        replacement_text: str,
        start_index: Optional[int] = None,
        end_index: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes an in-line text edit on the Google Doc.
        If start_index and end_index are specified, deletes that range and inserts replacement_text.
        Otherwise, uses ReplaceAllTextRequest matching original_text.
        """
        logger.info(f"Applying in-line edit on Doc {doc_id}, para {paragraph_id}: '{original_text[:35]}...' -> '{replacement_text[:35]}...'")

        if not self.has_credentials:
            return {
                "success": True,
                "doc_id": doc_id,
                "paragraph_id": paragraph_id,
                "original_text": original_text,
                "replacement_text": replacement_text,
                "status": "applied_cleanly",
                "timestamp": datetime.datetime.now().isoformat(),
                "mode": "simulated"
            }

        url = f"{self.docs_base_url}/{doc_id}:batchUpdate"
        requests_payload: List[Dict[str, Any]] = []

        if start_index is not None and end_index is not None:
            requests_payload.append({
                "deleteContentRange": {
                    "range": {
                        "startIndex": start_index,
                        "endIndex": end_index - 1
                    }
                }
            })
            requests_payload.append({
                "insertText": {
                    "location": {
                        "index": start_index
                    },
                    "text": replacement_text
                }
            })
        else:
            requests_payload.append({
                "replaceAllText": {
                    "containsText": {
                        "text": original_text,
                        "matchCase": True
                    },
                    "replaceText": replacement_text
                }
            })

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=await self._headers(), json={"requests": requests_payload})
            resp.raise_for_status()
            result = resp.json()

            return {
                "success": True,
                "doc_id": doc_id,
                "paragraph_id": paragraph_id,
                "original_text": original_text,
                "replacement_text": replacement_text,
                "batch_update_reply": result,
                "timestamp": datetime.datetime.now().isoformat(),
                "mode": "live"
            }
