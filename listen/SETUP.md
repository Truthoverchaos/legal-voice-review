# Voice Review: listen to drafts on the go, revise by voice

Version 2 of Legal Voice Review (October 2026). The first version read drafts with Safari's voice, which stopped when the screen locked, and it let Gemini rewrite the live Google Doc. This version works by ear with the phone in your pocket, and nothing in a draft changes until you approve it.

## How it works

1. **Listen.** At the desk, one command turns a draft (.md, .docx, or .txt) into a private podcast. Each part of the brief is an episode. Before every paragraph, a second voice says its number ("Fourteen."). You play it in Apple Podcasts or Overcast, so the lock screen, CarPlay, AirPods, steering-wheel buttons, speed control, and resume all just work.
2. **Note.** While listening, say **"Hey Siri, draft note"** (or press the Action Button), then speak: *"fourteen, cut the second sentence."* Siri answers "Saved, paragraph fourteen," and playback resumes.
3. **Revise.** Back at the desk, tell Claude **/voice-notes**. Claude turns your notes into a list of proposed edits next to each paragraph. Nothing changes until you say yes. Quotes, citations, dates, and dollar figures are protected: a guard check fails if any of them changed.

Every rendered paragraph is also transcribed back and compared with your text. If the voice dropped or garbled words, the render report names the paragraph so you know to listen closely there.

## One-time setup (about 20 minutes)

### 1. Let the phone reach the PC (Tailscale Funnel)
The audio and notes live on your PC. Tailscale gives it a private web address that works from anywhere. You need to do this part yourself because it involves signing in.

1. Install Tailscale on the PC: https://tailscale.com/download (or run `winget install Tailscale.Tailscale`), then sign in.
2. In a terminal, run: `tailscale funnel --bg 8790`
   The first time, it prints a link to turn on HTTPS and Funnel for your account. Open it, approve, and run the command again.
   It prints your address, something like `https://yourpc.tail1234.ts.net`.
3. Tell Voice Review that address:
   `py -3.13 -I C:\Users\truth\legal_voice_review\listen\voice.py set public_url https://yourpc.tail1234.ts.net`

The links include a long secret code, so nobody can find or guess them. Treat the feed link like a password.

### 2. The server
It starts by itself, hidden, every time you log in to Windows (`autostart_voice_review.vbs`, copied into the Startup folder as "Voice Review.vbs"). Its log is `C:\Users\truth\VoiceReview\server.log`. To run it in a visible window instead, double-click `start_voice_review.bat`.

**The PC has to be on and awake** for the phone to download new episodes and to receive Siri notes. Episodes you've already downloaded play anywhere, even with no signal.

### 3. Subscribe on the iPhone
1. Run `voice.py urls` and get the **Podcast feed** link to your phone (AirDrop it, or email it to yourself).
2. **Apple Podcasts:** Library, then the "..." menu, then **Follow a Show by URL**, and paste the link.
   **Overcast:** the + button, then **Add URL**.
3. In the show's settings, turn on automatic downloads.

### 4. Make the "Draft note" Shortcut
In the Shortcuts app, tap **+** and add these actions in order:

1. **Dictate Text**: set *Stop Listening* to **After Pause**.
2. **Append to Note**: append *Dictated Text* to a note called "Draft notes". This is a backup copy in case the PC is off.
3. **Get Contents of URL**
   - URL: the **Shortcut POST** link from `voice.py urls`
   - Method: **POST**
   - Request Body: **JSON**, with one field: key `text`, value *Dictated Text*
4. **Speak Text**: speak *Contents of URL* (this is the "Saved, paragraph fourteen" reply).
5. **Play/Pause**: set to **Play**, which resumes the podcast.

Name the shortcut **Draft note**. "Hey Siri, draft note" then works, including through CarPlay. Optional shortcuts:
- **Action Button** (iPhone 15 Pro and later): Settings, Action Button, Shortcut, Draft note.
- **Back Tap**: Settings, Accessibility, Touch, Back Tap, Double Tap, Draft note.

**Start every note with the paragraph number you just heard.** Notes without a number still save; Claude matches them to a paragraph by content when processing.

## Everyday use

| Where | What you do |
|---|---|
| Desk, before leaving | Ask Claude: `/voice-notes render <draft>`. Or run `voice.py render "<path to draft>"`. |
| Gym / car | Open Podcasts, choose Voice Review, press play. To leave a note: "Hey Siri, draft note", then "*number*, *what to change*". |
| Desk, eyes-free | Open the **Desk page** link (`voice.py urls`). Keys: **Space** play/pause, **←/→** paragraph, **↑/↓** part, **N** start/stop a voice note (it attaches to the paragraph playing, with no number needed), **T** type a note, **R** replay, **[ ]** speed, **W** "where am I". |
| Gym, phone in hand | The Desk page also works in Safari on the phone, with a big Voice note button. Keep the page open on screen. |
| Back at the desk | Ask Claude: `/voice-notes`. Approve or reject each proposal; Claude applies only the yeses to a new version and runs the guard. |

## Limits and fixes

- **Google allows about 100 voice clips per model per day** on this account. A long brief may need more than one day, or will switch to a backup voice model partway through, which sounds slightly different. Finished paragraphs are cached, so re-rendering an edited draft only redoes the paragraphs that changed.
- **A Siri note said it failed:** the PC was off or asleep. The note is still in Apple Notes under "Draft notes"; tell Claude "import my draft notes" and paste them.
- **New episode not showing:** pull down to refresh the show in the Podcasts app. Check the server window is open.
- **The render report flags a paragraph:** listen to it. Sometimes the voice skipped a word; re-rendering usually fixes it.

## Commands

```
py -3.13 -I voice.py render "<draft>"        # make the podcast (add --no-verify to skip the audio check)
py -3.13 -I voice.py serve                   # run the server
py -3.13 -I voice.py urls                    # print the feed, desk page, and Shortcut links
py -3.13 -I voice.py list                    # rendered drafts (* = the one Siri notes go to)
py -3.13 -I voice.py activate <slug>         # send Siri notes to a different draft
py -3.13 -I voice.py add "14, cut the last sentence"   # add a note by hand (e.g. from the Apple Notes backup)
py -3.13 -I voice.py notes [<slug>]          # build the notes packet for Claude
py -3.13 -I voice.py guard <old> <new>       # check that quotes and citations survived
py -3.13 -I voice.py set voice Kore          # change the narrator voice (Gemini voice names)
```

Data (audio, notes, settings, and the secret link token) lives in `C:\Users\truth\VoiceReview\`, never in this repository.
