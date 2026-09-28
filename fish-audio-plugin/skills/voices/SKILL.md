---
name: voices
description: Find, save, clone and design Fish Audio voices.
version: 0.1.0
author: Fish Audio
license: MIT
metadata:
  hermes:
    tags: [voice, tts, stt, cloning]
    category: creative
    related_skills: [fish-audio:voice-direction, fish-audio:dialogue]
---

# Voices Skill

Fish Audio has a large public voice library, private cloned voices, and voice design from a text
description. This skill covers choosing voices, saving short aliases, cloning with consent,
designing new voices, and transcription with speaker turns.

## When to Use

- The user wants a different voice, a voice "like X", a narrator, or voices for characters.
- The user provides recordings of their own voice to clone.
- The user wants a brand-new voice from a description.
- Transcribing a meeting or voice note where who spoke and how matters.

## Prerequisites

`fish_voices`, `fish_speak`, and `text_to_speech` from the `fish-audio` plugin.

## How to Run

```json
{"action": "search", "tags": ["female", "narration"], "language": "en", "limit": 5}
{"action": "alias", "voice_id": "802e3bc2b27e49c2995d23ef70e6ac89", "alias": "narrator"}
{"action": "design", "instruction": "Warm, confident studio narrator, mid-40s, gentle smile", "preview_text": "Welcome back to the show.", "n": 3}
{"action": "clone", "title": "Sam (own voice)", "audio_paths": ["/path/sam1.wav"], "transcripts": ["Exact words..."], "consent": true}
```

## Quick Reference

| Action | Purpose | Notes |
|---|---|---|
| search | public library | `query` (title words), `tags`, `language`, `licensed` (rights secured by Fish), `sort` |
| mine | the user's own voices | |
| get | details + sample transcripts | |
| alias | save `alias -> id` | aliases work anywhere a voice is accepted |
| design | 1-4 candidates from a description | WAV files to listen to; not stored until cloned |
| clone | persistent private voice | needs `consent: true`; 1-20 files of one speaker |
| delete | remove the user's voice | needs `confirm: true` after the user agrees |
| credit | API balance | |

Instant (zero-shot) cloning without storing a voice: `fish_speak` `reference_audio`
`[{path, transcript}]`, 10-30 s of clean speech with its exact transcript.

Transcription: set `stt.provider: fish-audio`. Plugin setting `stt_model: transcribe-1-pro` returns
speaker turns as `<|speaker:N|>` and emotion cues such as `[laughter]` inside the transcript.

## Procedure

1. Ask what the voice is for (narration, assistant, character) and any traits (gender, age, accent,
   energy, language).
2. `search` with 2-3 tags plus `language`; present 3-5 options with titles and descriptions; prefer
   `licensed` voices for commercial work.
3. Render a one-line sample with `fish_speak` for the top picks so the user can hear them.
4. Save the chosen one with `alias` (short, lowercase: `narrator`, `support-agent`, `mara`).
5. Nothing fits: `design` with a concrete description (age, timbre, pace, accent, attitude, use),
   let the user pick a candidate, `clone` it with `consent: true`, then `alias` it.
6. Cloning a real person: confirm it is the user's own voice or they have the speaker's permission,
   use clean single-speaker audio (quiet room, no music, steady volume, 30-60 s total), and pass
   transcripts when available.

## Pitfalls

- Never clone voices of public figures or people who did not consent, even if asked; offer
  `design` instead.
- Voice ids are 32 hex characters; titles are not ids. Use `alias` rather than memorizing ids.
- Designed candidates disappear from Fish after the call; only the local WAV files remain until
  cloned.
- `delete` is permanent and affects every workflow that uses the voice.

## Verification

- `alias` returns the updated alias map including the new name.
- A `fish_speak` call with `voice: <alias>` succeeds and its result `voices` shows the id.
- `clone` returns a voice whose `state` is `trained` (or `created`, which becomes usable shortly).
