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

## Making an edit

There is a text box near the bottom with a placeholder that says "Or type a verbal instruction." This is currently the **only** way to make an edit — **saying a change out loud does not work today.** The microphone only detects that you're talking (to pause playback); it never converts your speech to text or acts on it.

**Fixed 2026-09-20:** typing text and hitting Send now cleanly replaces the current paragraph with exactly what you typed. It used to corrupt the paragraph by appending a bracketed note onto the original text — that bug is gone. But note what "clean replacement" means today: whatever you type becomes the paragraph, verbatim. If you type "change the date to August 10," the paragraph becomes the literal words "change the date to August 10" — it does not yet understand instructions and rewrite the paragraph intelligently. You need to type (or eventually speak) the full replacement paragraph text itself, not a description of the change. See item 3 below for the fix that adds real instruction-following.

## What "Safe Versioning" actually means right now

- The Drive backup copy: real, works, happens automatically every time you open a document for review.
- The in-line edit mechanism (when it isn't hitting the bug above): a genuine, surgical edit — it finds the exact paragraph in the live Google Doc and replaces just that range, using Google's own document API. No tracked-changes clutter. This part of the engineering is solid.

## Bottom line for today's use

The app is reliable for **listening to a draft read back to you, paragraph by paragraph, hands-free**, using your phone's built-in voice. Typed edits now save cleanly, but only if you type the full replacement paragraph rather than a description of the change — there's no instruction-following yet. Speaking a change out loud does nothing yet. Treat it as a read-aloud tool with a basic manual-typing fallback for now.

---

## What needs to be built to match the original vision

In order of what would help most:

1. ~~Fix the typed-edit bug.~~ **Done 2026-09-20** — typed edits now replace the paragraph cleanly.
2. **Real speech-to-text for spoken instructions.** This is the core of what you actually asked for — talking instead of typing. The fastest path is the iPhone browser's own built-in speech recognition (works reasonably well in Safari), feeding transcribed text into the same edit pipeline that already exists. This does not require Gemini at all to work.
3. **An actual rewrite step.** Right now, whatever text you provide (typed or eventually spoken) becomes the paragraph verbatim. To get real "clarify the date" or "tighten this sentence" style instructions, that instruction needs to go through an AI call that drafts the revised paragraph — a genuine text-generation step, not string handling.
4. **The real Gemini voice, if you still want it specifically.** This is the biggest lift: a live, two-way audio connection to Gemini's Multimodal Live API (partially scaffolded in the code already, but never wired up) so Gemini both listens and speaks directly, rather than the phone's generic voice. Worth doing last, after the app is trustworthy on the basics.

Items 1–3 would get you a genuinely usable hands-free review-and-edit tool without Gemini's voice specifically. Item 4 is what would make it match the name.
