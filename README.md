# Legal Voice Review & Revision (iPhone PWA)

A full-duplex verbal review tool designed for Florida litigation attorney Christopher Hanson to review drafts of legal documents (briefs, petitions, motions, agreements) aloud on an iPhone, interrupt with verbal revisions, apply clean in-line edits to Google Docs, and preserve clean pre-review versions without track changes clutter.

---

## Key Features

1. **iPhone-Optimized Progressive Web App (PWA):**
   - Runs directly in Safari or added to the Home Screen (`standalone` display mode).
   - Unlocks the iOS Web Audio API on initial user touch.
   - Built with hardware echo cancellation, noise suppression, and Voice Activity Detection (VAD) to allow smooth voice interruptions without feedback loops.

2. **Safe Versioning (Clean Two-Version Architecture):**
   - Avoids messy Google Docs "track changes / suggestions" markup.
   - **Automated Snapshot on Session Start:** Clones an immutable backup in Google Drive before any edits take place:  
     `[Title] — Pre-Review Backup (YYYY-MM-DD HH:MM)`
   - **Direct In-Line Revisions:** Replaces the text cleanly inside the working Google Doc so the draft remains executive-ready.
   - Preserves both the original baseline and the revised draft.

3. **Verbal Interruption & Barge-In:**
   - The assistant reads the draft aloud paragraph-by-paragraph with legal cadence.
   - When you speak (*"Wait, clarify that..."* or *"Change the date in paragraph 3 to..."*), client-side audio playback halts immediately.
   - The model parses the instruction, applies the edit via the Google Docs API, and reads back the revised paragraph for confirmation.
   - Say *"Next"* or *"Continue"* to resume reading from the next section.

4. **Live Visual Diff Card:**
   - The mobile UI displays the active paragraph, progress indicator, and a real-time **Before & After Diff Card** showing the replaced text and the new text in-line.

---

## Directory Structure

```
legal_voice_review/
├── app/
│   ├── __init__.py           # Package setup & dynamic finder
│   ├── config.py             # Environment configuration
│   ├── workspace_service.py  # Google Drive backup cloning & Google Docs batchUpdate
│   ├── session_manager.py    # Active review session state, index tracking, diff history
│   ├── gemini_live_bridge.py # Gemini Multimodal Live WebSocket relay & barge-in logic
│   └── main.py               # FastAPI application, REST endpoints, and static PWA host
├── frontend/
│   ├── index.html            # iPhone mobile UI & legal reading stage
│   ├── manifest.json         # Web App Manifest for iOS "Add to Home Screen"
│   ├── sw.js                 # Service Worker for offline shell caching
│   ├── icon.svg              # App icon
│   ├── css/
│   │   └── app.css           # Apple Human Interface Guidelines responsive dark theme
│   └── js/
│       ├── audio_engine.js   # iOS Safari AudioContext unlock, mic recording & instant mute
│       └── app.js            # PWA controller, WebSocket event handler & diff viewer
├── tests/
│   └── test_review_flow.py   # Full test suite covering Drive, Docs, sessions & API
├── run.py                    # Entry point runner
└── README.md                 # Complete documentation
```

---

## Quick Start & Running Locally

### 1. Launch the Server
```bash
python3 run.py
```
The server will start at `http://0.0.0.0:8000`.

### 2. Access on iPhone
1. Ensure your iPhone is on the same local Wi-Fi network (or accessible via your tailscale/tunnel).
2. Open Safari on your iPhone and navigate to `http://<your-local-ip>:8000`.
3. Tap the **Share** button in Safari and select **"Add to Home Screen"**.
4. Tap the **Legal Voice** icon on your home screen to launch in full-screen PWA mode.

---

## Configuration (`.env`)

Create a `.env` file in the root directory:

```ini
# Google Workspace OAuth
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_OAUTH_TOKEN=your_oauth_token

# Gemini Multimodal Live API
GEMINI_API_KEY=your_gemini_api_key
GEMINI_LIVE_MODEL=models/gemini-2.0-flash-exp
GEMINI_VOICE_NAME=Aoede  # Options: Aoede, Puck, Charon, Kore, Fenrir
```

*Note: If no Google OAuth token or Gemini API key is provided, the application automatically runs in simulated demonstration mode with full offline testing and local speech synthesis enabled.*

---

## Verbal Interaction Cheatsheet

| Attorney Says | Assistant Action |
| :--- | :--- |
| **"Start reading" / Tap Mic** | Begins reading the active paragraph aloud. |
| **"Pause" / "Hold on" / Tap Stop** | Cuts off audio immediately and waits for instruction. |
| **"Change paragraph [X] to..."** | Rewrites the clause, applies edit to Google Doc, and reads back the revision. |
| **"Repeat" / "Read again"** | Re-reads the current paragraph aloud. |
| **"Next" / "Continue"** | Advances reading pointer to the subsequent paragraph. |
| **"Previous"** | Steps back to the preceding paragraph. |
