---
name: voice-direction
description: Direct expressive Fish Audio speech with delivery cues.
version: 0.1.0
author: Fish Audio
license: MIT
metadata:
  hermes:
    tags: [voice, tts, speech, emotion]
    category: creative
    related_skills: [fish-audio:dialogue, fish-audio:pronunciation, fish-audio:voices]
---

# Voice Direction Skill

Fish Audio models perform text the way a voice actor would when you direct them. This skill is the
cue library and the judgement for using it: which emotion, tone, effect, pace and intensity fit a
line, where cues go, and when to leave text plain. It covers single-voice delivery; dialogue and
pronunciation have their own skills.

## When to Use

- Any `fish_speak` call where feeling, character or pacing matters: stories, jokes, condolences,
  announcements, apologies, greetings, dramatic readings, audio drafts for the user.
- The user asks for a tone ("say it sarcastically", "whisper it", "sound excited").
- Rewriting your own reply before it is spoken, when the user is in a voice conversation.
- Not for neutral read-outs of data (numbers, lists, code): plain text sounds best there.

## Prerequisites

The `fish-audio` plugin with `FISH_API_KEY` set. Tools: `fish_speak`, `text_to_speech`.

## How to Run

Write the script with cues inline and call `fish_speak`:

```json
{"text": "[warm] Welcome back. [curious] Did the demo go well? [laughing] Ha, I knew it would!"}
```

Whole-script mood that no single sentence carries: `"direction": "calm, unhurried, faint smile"`.
With `text_to_speech`, put cues in `text` and the overall mood in `instructions`.

## Quick Reference

Cue syntax is always `[cue]`. The plugin converts it for the legacy `s1` model and removes cues
`s1` cannot say, so they are never read aloud. On S2 models (`s2.1-pro`, `s2.1-pro-free`,
`s2-pro`, `drama-3-preview`) any short natural-language description works.

| Kind | Cues (documented set; S2 also accepts free-form) | Placement |
|---|---|---|
| Basic emotion | happy, sad, angry, excited, calm, nervous, confident, surprised, satisfied, delighted, scared, worried, upset, frustrated, depressed, empathetic, embarrassed, disgusted, moved, proud, relaxed, grateful, curious, sarcastic | start of the sentence |
| Nuanced emotion | disdainful, unhappy, anxious, hysterical, indifferent, uncertain, doubtful, confused, disappointed, regretful, guilty, ashamed, jealous, envious, hopeful, optimistic, pessimistic, nostalgic, lonely, bored, contemptuous, sympathetic, compassionate, determined, resigned | start of the sentence |
| Tone | whispering, soft tone, shouting, screaming, in a hurry tone, emphasis | anywhere; `[emphasis]` right before the stressed word |
| Vocal effect | laughing, chuckling, sighing, gasping, sobbing, crying loudly, groaning, panting, yawning, snoring, clear throat | where the sound happens, followed by matching text |
| Pause / ambience | break, long-break, audience laughing, background laughter, crowd laughing | where it happens |
| S2 free-form | [whispers sweetly], [laughing nervously], [slightly sarcastic, rising tone], [voice cracking] | anywhere |

Intensity: add a modifier (`[slightly sad]`, `[very excited]`) or pick the stronger word.

| Base | Mild | Moderate | Intense |
|---|---|---|---|
| happy | satisfied | happy | delighted |
| sad | disappointed | sad | depressed |
| angry | frustrated | angry | furious |
| scared | nervous | scared | terrified |
| excited | interested | excited | ecstatic |

Other knobs on `fish_speak`: `speed` 0.5-2.0 (0.85 for gravity or teaching, 1.15 for urgency),
`volume` in dB, `temperature` (0.4 steady narration, 0.8-0.9 animated character work), `latency`
(`normal` for files, `balanced` when the user is waiting to hear it).

## Procedure

1. Decide the arc before writing cues: what does the listener feel at the start, the turn, the end?
2. Mark only the moments where the mood changes. One cue per sentence on average; never more than
   three per sentence; never two conflicting emotions together (`[happy][sad]`).
3. Put the emotion first in its sentence: `[nervous] Are you sure about this?` not
   `Are you [nervous] sure?`.
4. Pair effects with sound-text so the model has something to perform: `[laughing] Ha, ha!`,
   `[sighing] Sigh...`, `[clear throat] Ahem.`, `[gasping] Oh!`.
5. Use punctuation for rhythm first (commas, ellipses, full stops); add `[break]` or
   `[long-break]` for beats punctuation cannot carry; filler words ("um", "well...") make
   conversational speech natural.
6. Stack at most two cues for a compound delivery: `[sad][whispering] I miss you.`
7. Pick pace with `speed`, not with cues like `[slow]`.
8. Check the tool result: `performed_text` shows exactly what was sent; `warnings` explain anything
   converted or removed. Fix and re-run if a warning changes the meaning.

Recipes:

| Situation | Script shape |
|---|---|
| Conversational reply | `[warm] Sure thing. [curious] Do you want the short version or the details?` |
| Good news | `[excited] It passed! [relieved] All forty tests are green.` |
| Bad news / apology | `[sympathetic] I'm sorry. [calm] Here's what happened, and what we'll do next.` speed 0.95 |
| Story narration | `[mysterious][whispering] The house stood silent. [break] [scared] "Is anyone there?" she called.` temperature 0.8 |
| Sarcasm / comedy | `[sarcastic] Oh, great. Another meeting. [chuckling] Heh, can't wait.` |
| Motivation | `[determined] We are not done yet. [emphasis] Every single one of you made this possible.` |
| Bedtime / meditation | `[soft tone] Breathe in... [long-break] and let it go.` speed 0.85 |
| Urgent alert | `[in a hurry tone] The build is failing on main. [emphasis] Now.` speed 1.15 |

## Pitfalls

- Cues in normal chat replies show up as literal text on screen; keep them in speech-tool input.
- Over-tagging sounds theatrical and unstable. If every sentence has a cue, remove half.
- A cue far from its sentence drifts: keep emotion cues at sentence start.
- `s1` supports only the fixed list above and no free-form cues; results `warnings` tell you what
  was dropped. Prefer an S2 model for expressive work.
- Long bracket descriptions (over ~8 words) steer worse than short ones.
- Markdown, emoji and URLs are not spoken well; write speech as plain sentences.

## Verification

- The result has `success: true`, a `file_path`, and a `media_tag` to deliver.
- `performed_text` still contains your cues in `[brackets]` (S2) or `(parentheses)` (s1).
- No `warnings` about removed cues, or you accepted them deliberately.
- For an important piece, round-trip the audio through transcription (`stt.provider: fish-audio`,
  model `transcribe-1-pro` keeps emotion cues) and compare the words.
