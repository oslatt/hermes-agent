---
name: pronunciation
description: Control Fish Audio pronunciation with phonemes and dictionaries.
version: 0.1.0
author: Fish Audio
license: MIT
metadata:
  hermes:
    tags: [voice, tts, pronunciation, phonemes]
    category: creative
    related_skills: [fish-audio:voice-direction]
---

# Pronunciation Skill

Fish Audio reads most text correctly, but names, brands, acronyms, homographs and technical terms
sometimes need exact pronunciation. Fish accepts inline phoneme spans and per-request pronunciation
dictionaries. This skill picks the right mechanism and writes the phonemes.

## When to Use

- A name, brand, acronym or jargon word is likely to be misread (Kubernetes, SQL, nginx, Siobhan).
- Homographs whose meaning decides the sound (read/read, bass/bass, lead/lead, polish/Polish).
- Chinese polyphonic characters (重庆 chong2 vs 重要 zhong4) or Japanese pitch-accent pairs.
- The user says "you pronounced X wrong".

## Prerequisites

`fish_speak` from the `fish-audio` plugin. English phonemes use CMU Arpabet (IPA is not supported).

## How to Run

One occurrence, exact control, inline in `text`:

```text
Deploy it with <|phoneme_start|>K UW2 B ER0 N EH1 T IY0 Z<|phoneme_end|> tonight.
```

Every occurrence in the request, via `pronunciations` on `fish_speak`:

```json
{"text": "Our SQL runs on Kubernetes.", "pronunciations": {"SQL": "EH1 S K Y UW1 EH1 L", "Kubernetes": "K UW2 B ER0 N EH1 T IY0 Z"}}
```

Terms the user always wants: ask them to add `pronunciations` (or managed
`pronunciation_dictionaries: [{id, version}]` from the Fish web app) to the plugin settings.

## Quick Reference

- English: CMU Arpabet, space separated, stress digit 0/1/2 on vowels, one word per tag.
  `<|phoneme_start|>R IY1 D<|phoneme_end|>` (read, present tense)
- Chinese: tone-number pinyin (tones 1-5), one syllable per tag.
  `<|phoneme_start|>chong2<|phoneme_end|><|phoneme_start|>qing4<|phoneme_end|>` (重庆)
- Japanese: OpenJTalk romaji with a pitch digit per mora (0 low, 1 high), short phrase per tag.
  `<|phoneme_start|>ha0shi1ga0<|phoneme_end|>見えます` (橋が見えます)

Common English: engineer `EH1 N JH AH0 N IH1 R`; read (past) `R EH1 D`; bass (fish) `B AE1 S`;
bass (music) `B EY1 S`; Polish `P OW1 L IH0 SH`; polish `P AA1 L IH0 SH`; SQL `EH1 S K Y UW1 EH1 L`;
nginx `EH1 N JH AH0 N EH1 K S`; GIF `JH IH1 F` or `G IH1 F`; data `D EY1 T AH0`.

Arpabet vowels: AA (father) AE (cat) AH (cut) AO (thought) AW (cow) AY (my) EH (bed) ER (bird)
EY (say) IH (sit) IY (see) OW (go) OY (boy) UH (book) UW (food). Consonants: B CH D DH (this) F G
HH JH (judge) K L M N NG P R S SH T TH (thin) V W Y Z ZH (vision).

## Procedure

1. Identify the risky words; do not tag words the model already reads correctly.
2. Write phonemes for the pronunciation the listener should hear, not the spelling. Put stress
   digits on vowels (1 = primary stress).
3. Keep punctuation outside the tag: `<|phoneme_start|>R EH1 D<|phoneme_end|>.`
4. One tag per English word or Chinese syllable; wrap multi-word names word by word.
5. Repeated terms: use `pronunciations` instead of repeating tags; keys are matched as plain,
   case-insensitive substrings (an uppercase key is matched case-sensitively), so prefer
   distinctive keys ("read endpoint" rather than "read").
6. Numbers, dates and URLs are normalized automatically; set `normalize` off in plugin settings
   only when you need the exact surface text read literally.

## Pitfalls

- Never put `<|phoneme_start|>` markers inside `pronunciations` values; the plugin strips them.
- Unbalanced tags produce a warning and may be read literally.
- Short dictionary keys match inside longer words ("SQL" inside "PostgreSQL").
- At most 3 dictionaries per request; inline rules and managed dictionaries cannot be mixed in one
  request (the plugin keeps the inline rules and warns).

## Verification

- `performed_text` keeps the phoneme tags intact.
- Listen, or transcribe the result: the term should come back spelled the intended way.
