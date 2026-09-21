// Main Mobile PWA Controller for Legal Voice Review
document.addEventListener('DOMContentLoaded', async () => {
  // PWA Service Worker Registration
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(err => console.log('SW registration skipped:', err));
  }

  const audioEngine = new AudioEngine();
  let currentDocId = 'doc_mandamus_001';
  let ws = null;
  let sessionState = null;
  let isVoiceSessionActive = false;

  // DOM Elements
  const docTitleEl = document.getElementById('docTitle');
  const docMetaEl = document.getElementById('docMeta');
  const backupBadgeEl = document.getElementById('backupBadge');
  const progressFillEl = document.getElementById('progressFill');
  const paraLabelEl = document.getElementById('paraLabel');
  const paraTextEl = document.getElementById('paraText');
  const speakingWaveEl = document.getElementById('speakingWave');
  const diffCardEl = document.getElementById('diffCard');
  const diffOldEl = document.getElementById('diffOld');
  const diffNewEl = document.getElementById('diffNew');
  const statusBoxEl = document.getElementById('statusBox');

  // Control Dock Buttons
  const btnMic = document.getElementById('btnMic');
  const btnPlayPause = document.getElementById('btnPlayPause');
  const btnPrev = document.getElementById('btnPrev');
  const btnNext = document.getElementById('btnNext');
  const btnInterrupt = document.getElementById('btnInterrupt');
  const btnSelectDoc = document.getElementById('btnSelectDoc');

  // Modal Elements
  const docModal = document.getElementById('docModal');
  const docList = document.getElementById('docList');
  const btnCloseModal = document.getElementById('btnCloseModal');

  // 1. Fetch Documents from Google Drive
  async function loadDocuments() {
    try {
      const res = await fetch('/api/documents');
      const data = await res.json();
      docList.innerHTML = '';
      data.documents.forEach(doc => {
        const item = document.createElement('div');
        item.className = 'doc-item';
        item.innerHTML = `
          <div>
            <div class="doc-item-title">${doc.name}</div>
            <div class="doc-item-sub">Modified: ${new Date(doc.modifiedTime).toLocaleDateString()}</div>
          </div>
          <span style="font-size: 1.2rem; color: #38bdf8;">➔</span>
        `;
        item.onclick = () => {
          docModal.classList.remove('open');
          startSession(doc.id, doc.name);
        };
        docList.appendChild(item);
      });
    } catch (err) {
      console.error('Error loading docs:', err);
    }
  }

  // 2. Start Review Session (Triggers Pre-Review Backup Cloning in Drive)
  async function startSession(docId, docName) {
    currentDocId = docId;
    statusBoxEl.innerHTML = `<span class="highlight">Initializing:</span> Creating pre-review backup in Google Drive...`;

    try {
      const res = await fetch('/api/sessions/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_id: docId })
      });
      const data = await res.json();
      sessionState = data.state;

      // Update UI with document and backup info
      docTitleEl.textContent = sessionState.title;
      docMetaEl.textContent = `${sessionState.total_paragraphs} Paragraphs • Backup: ${sessionState.backup_info?.backup_title || 'Clean Copy'}`;
      backupBadgeEl.style.display = 'flex';
      backupBadgeEl.textContent = `✓ Pre-Review Backup Saved`;

      updateParagraphDisplay();
      connectWebSocket(docId);
    } catch (err) {
      console.error('Session start error:', err);
      statusBoxEl.textContent = 'Error starting session. Check network.';
    }
  }

  function updateParagraphDisplay() {
    if (!sessionState || !sessionState.paragraphs.length) return;
    const curr = sessionState.current_paragraph;
    const total = sessionState.total_paragraphs;
    const idx = sessionState.current_paragraph_index;

    paraLabelEl.textContent = `Paragraph ${idx + 1} of ${total} (${curr.style || 'NORMAL_TEXT'})`;
    paraTextEl.textContent = curr.text;

    const pct = ((idx + 1) / total) * 100;
    progressFillEl.style.width = `${pct}%`;
  }

  // 3. WebSocket Real-Time Voice Connection
  function connectWebSocket(docId) {
    if (ws) {
      ws.close();
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/review/${docId}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('[WS] Connected to Legal Voice Review session');
      statusBoxEl.innerHTML = `Connected. Tap the <span class="highlight">Microphone</span> to start verbal review with barge-in.`;
    };

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      console.log('[WS Message]:', msg);

      if (msg.type === 'assistant_message') {
        statusBoxEl.textContent = msg.text;
        speakingWaveEl.classList.add('active');

        // Play assistant speech aloud
        audioEngine.speakText(msg.speak_text || msg.text, () => {
          speakingWaveEl.classList.remove('active');
        });

        if (msg.current_paragraph) {
          sessionState.current_paragraph = msg.current_paragraph;
          sessionState.current_paragraph_index = msg.current_index;
          updateParagraphDisplay();
        }
      } else if (msg.type === 'paragraph_updated') {
        // Safe in-line edit confirmed
        const edit = msg.edit;
        diffOldEl.textContent = edit.original_text;
        diffNewEl.textContent = edit.revised_text;
        diffCardEl.classList.add('show');

        sessionState = msg.session_state;
        updateParagraphDisplay();
      } else if (msg.type === 'interrupted') {
        speakingWaveEl.classList.remove('active');
        audioEngine.stopPlayback();
        statusBoxEl.innerHTML = `<span class="highlight">Interrupted:</span> Listening for your changes...`;
      } else if (msg.type === 'transcribing') {
        statusBoxEl.innerHTML = `<span class="highlight">Listening back:</span> transcribing what you said...`;
      }
    };

    ws.onerror = (err) => console.error('[WS Error]:', err);
    ws.onclose = () => console.log('[WS Closed]');
  }

  // 4. Voice Controls & Barge-In
  btnMic.onclick = async () => {
    await audioEngine.unlock();

    if (!isVoiceSessionActive) {
      // Start recording and voice loop
      try {
        await audioEngine.startRecording(
          (pcmBuffer) => {
            // Chunks are buffered internally by AudioEngine (see
            // finalizeUtterance()); nothing to do with each individual chunk here.
          },
          () => {
            // Local Barge-in triggered!
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'barge_in' }));
            }
          }
        );
        isVoiceSessionActive = true;
        btnMic.classList.add('listening');
        statusBoxEl.innerHTML = `<span class="highlight">Voice active:</span> Speak your instruction, then tap the red button to send it. Say "next" or "repeat" the same way.`;
      } catch (e) {
        alert('Microphone access denied or unavailable: ' + e.message);
      }
    } else {
      audioEngine.stopRecording();
      audioEngine.stopPlayback();
      isVoiceSessionActive = false;
      btnMic.classList.remove('listening');
      speakingWaveEl.classList.remove('active');
      statusBoxEl.textContent = 'Voice paused. Tap mic to resume.';
    }
  };

  // The red button does double duty:
  // - While the assistant is talking, it interrupts playback (unchanged).
  // - While idle and voice mode is active, it sends whatever you just said
  //   as a spoken instruction for Gemini to transcribe and act on.
  btnInterrupt.onclick = () => {
    if (audioEngine.isPlaying) {
      audioEngine.stopPlayback();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'barge_in' }));
      }
      statusBoxEl.innerHTML = `<span class="highlight">Interrupted:</span> Listening for your changes...`;
      return;
    }

    if (!isVoiceSessionActive) {
      statusBoxEl.textContent = 'Tap the microphone first, then speak, then tap here to send.';
      return;
    }

    const audioBase64 = audioEngine.finalizeUtterance();
    if (!audioBase64) {
      statusBoxEl.textContent = "Didn't catch anything. Speak, then tap the red button again.";
      return;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'audio_instruction', audio_base64: audioBase64 }));
      statusBoxEl.innerHTML = `<span class="highlight">Sent:</span> transcribing and applying your instruction...`;
    } else {
      statusBoxEl.textContent = 'Not connected. Try again in a moment.';
    }
  };

  btnNext.onclick = () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'instruction', text: 'next' }));
    }
  };

  btnPrev.onclick = async () => {
    if (!sessionState) return;
    const prevIdx = Math.max(0, sessionState.current_paragraph_index - 1);
    await fetch(`/api/sessions/${currentDocId}/seek`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index: prevIdx })
    });
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'instruction', text: 'repeat' }));
    }
  };

  // Modal Events
  btnSelectDoc.onclick = () => {
    loadDocuments();
    docModal.classList.add('open');
  };

  btnCloseModal.onclick = () => {
    docModal.classList.remove('open');
  };

  // Initial load
  await loadDocuments();
  await startSession('doc_mandamus_001', 'Petition for Writ of Mandamus');
});
