---
name: dialogue
description: Voice multi-speaker scenes and characters with Fish Audio.
version: 0.1.0
author: Fish Audio
license: MIT
metadata:
  hermes:
    tags: [voice, tts, dialogue, characters]
    category: creative
    related_skills: [fish-audio:voice-direction, fish-audio:voices]
---

# Dialogue Skill

Fish Audio S2 models render a whole conversation in one request, each speaker in their own voice,
with delivery cues per line. This skill covers casting voices, writing lines, and keeping characters
consistent. Single-voice character acting (one narrator doing voices) is also covered.

## When to Use

- Scenes, skits, interviews, podcasts, radio plays, language-practice conversations, customer
  service role-plays, reading a chat log aloud.
- The user asks for "two voices", "a conversation between", "act it out", "different characters".

## Prerequisites

`fish_speak` and `fish_voices` from the `fish-audio` plugin. Dialogue needs an S2 model
(`s2.1-pro`, `s2.1-pro-free`, `s2-pro`, `drama-3-preview`); on `s1` the plugin switches model and warns.

## How to Run

```json
{
  "lines": [
    {"speaker": "Mara", "text": "[excited] You found it? Where?"},
    {"speaker": "Theo", "text": "[whispering] Keep your voice down. Under the floorboards."},
    {"speaker": "Mara", "text": "[gasping] Oh! [laughing nervously] Of course it was."}
  ],
  "cast": {"Mara": "bright-female", "Theo": "gravel-male"}
}
```

`cast` maps character names to voice aliases or ids. A speaker with no `cast` entry is resolved as a
voice alias itself. For zero-shot voices, add `reference_audio` items with `speaker` set to the
character name (and the user's permission for that audio).

## Quick Reference

| Need | Do |
|---|---|
| Voices for characters | `fish_voices action=search` with tags (`male`, `female`, `young`, `old`, `calm`, `narration`) and `language`; save picks with `action=alias` |
| New character voice | `fish_voices action=design instruction="gruff old sea captain, slow, amused"` then clone the chosen candidate |
| Narrator + characters | make "Narrator" a speaker with its own voice |
| Long scene | fine: the plugin splits at sentence boundaries and re-opens the current speaker in each request |
| Raw token form (advanced) | `text: "<|speaker:0|>Hi!<|speaker:1|>Hello."` with `cast` unused; pass voices in speaker order via `lines` instead when possible |

## Procedure

1. List the characters and one line of personality each (age, energy, attitude).
2. Cast distinct voices: contrast pitch/gender/age so listeners can tell speakers apart. Reuse the
   same alias for the same character across calls so the character stays consistent.
3. Write short turns (one to three sentences); real conversation interrupts and reacts.
4. Give each turn its own cue where the feeling changes; reactions ("[laughing] Ha!",
   "[sighing] Fine.") make scenes feel alive.
5. Call `fish_speak` with `lines` and `cast`; check `speakers` in the result maps index to name.
6. If the user wants revisions, change only the affected lines and re-render; keep the cast fixed.

## Pitfalls

- Every speaker needs a voice: an unknown name fails with a list of known aliases. Search or alias
  first.
- `s1` cannot do dialogue; do not force `model: s1` for scenes.
- Do not reuse one voice for two characters unless the user asked for a single-narrator reading.
- Cloning a real person's voice for a character needs their permission; design a voice instead.

## Verification

- Result `speakers` lists every character; `voices` has one id per speaker in the same order.
- `performed_text` contains one `<|speaker:N|>` per turn.
- No `warnings` about model switching unless expected.
