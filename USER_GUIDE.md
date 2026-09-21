# Legal Voice Review — User Guide (as the app actually works, 2026-09-20)

This describes what the app does right now, not what the original README promised. Two things in the README are not true yet — flagged below — because they matter for how you use it safely.

## Getting in

1. On your iPhone, open Safari and go to `https://legal-voice-review.onrender.com`.
2. Tap the Share icon, then "Add to Home Screen." Tap the new "Legal Voice" icon to open it full-screen.
3. The app loads and shows "Select a Document."

## Picking a document

1. Tap "Switch Draft" at the top.
2. A list of your real Google Docs appears, newest first.
3. Tap one. This does two things immediately:
   - Creates a timestamped backup copy of that exact document in your Google Drive, named `[Title] — Pre-Review Backup (date time)`. This is real and permanent — your original is never touched directly; edits land on the working copy while the backup preserves the "before" state.
   - Loads the document, split into paragraphs, and starts reading the first one aloud automatically.

## Reading and navigating

- The current paragraph's text is shown on screen and read aloud.
- **Next / Previous arrows** (bottom dock) move to the next or previous paragraph and read it.
- **The voice you hear is your iPhone's own built-in voice** (Safari's text-to-speech, whichever system voice it finds — Samantha, Daniel, or similar), not Gemini's voice. The app is not actually connected to Gemini at all right now, despite what it's named.
- **Tapping the red Interrupt button, or starting to talk while it's reading,** stops the reading instantly. Talking near the phone is detected as volume/energy, not as words — it just knows you started making noise and stops.

## Making an edit — READ THIS BEFORE USING

There is a text box near the bottom with a placeholder that says "Or type a verbal instruction." This is currently the **only** way to make an edit — **saying a change out loud does not work today.** The microphone only detects that you're talking (to pause playback); it never converts your speech to text or acts on it.

**There is also an active bug in the typed-edit path you should know about before relying on it:** typing something and hitting Send does not cleanly rewrite the paragraph. Instead, it takes your typed words and tacks them onto the end of the original paragraph text in brackets, then saves that combined mess into your actual Google Doc — for example, typing "change the date to August 10" would leave the paragraph reading like:

> [original paragraph text] [Revised per instruction: change the date to August 10]

That is not what a clean edit should look like, and it will land directly in your live document if you use it. **Until this is fixed, don't use the typed-edit box for a document you care about** — the pre-review backup means nothing is unrecoverable, but you'd have to manually clean up the bracketed text afterward.

## What "Safe Versioning" actually means right now

- The Drive backup copy: real, works, happens automatically every time you open a document for review.
- The in-line edit mechanism (when it isn't hitting the bug above): a genuine, surgical edit — it finds the exact paragraph in the live Google Doc and replaces just that range, using Google's own document API. No tracked-changes clutter. This part of the engineering is solid.

## Bottom line for today's use

The app is reliable for **listening to a draft read back to you, paragraph by paragraph, hands-free**, using your phone's built-in voice. It is **not yet reliable for making edits** — neither by voice (not built) nor by typing (bug above). Treat it as a read-aloud tool for now, and make your actual edits the way you did before, until the fixes below land.

---

## What needs to be built to match the original vision

In order of what would help most:

1. **Fix the typed-edit bug.** Small, fast fix — the fallback logic should replace the paragraph cleanly (like the REST endpoint already does correctly) instead of appending a bracketed note. This makes typed edits trustworthy.
2. **Real speech-to-text for spoken instructions.** This is the core of what you actually asked for — talking instead of typing. The fastest path is the iPhone browser's own built-in speech recognition (works reasonably well in Safari), feeding transcribed text into the same edit pipeline that already exists. This does not require Gemini at all to work.
3. **An actual rewrite step.** Right now, whatever text you provide (typed or eventually spoken) becomes the paragraph verbatim. To get real "clarify the date" or "tighten this sentence" style instructions, that instruction needs to go through an AI call that drafts the revised paragraph — a genuine text-generation step, not string handling.
4. **The real Gemini voice, if you still want it specifically.** This is the biggest lift: a live, two-way audio connection to Gemini's Multimodal Live API (partially scaffolded in the code already, but never wired up) so Gemini both listens and speaks directly, rather than the phone's generic voice. Worth doing last, after the app is trustworthy on the basics.

Items 1–3 would get you a genuinely usable hands-free review-and-edit tool without Gemini's voice specifically. Item 4 is what would make it match the name.
