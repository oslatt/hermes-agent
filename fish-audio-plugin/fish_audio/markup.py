"""Fish Audio speech markup: one authoring syntax for the agent, compiled per model.

The agent always writes S2 syntax: ``[cue]`` for emotion/tone/effects (free-form on S2),
``<|speaker:N|>`` for dialogue turns, ``<|phoneme_start|>…<|phoneme_end|>`` for pronunciation.
:func:`compile_for_model` turns that into what the chosen model understands, so a cue is never
read aloud. Pure functions; every change is reported as a warning the tool returns to the agent.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import FishModel

# --- Vocabularies (fishaudio/docs snippets/emotion-list-*.mdx) -------------------------------------
S1_EMOTIONS = frozenset((
    "happy sad angry excited calm nervous confident surprised satisfied delighted scared worried upset "
    "frustrated depressed empathetic embarrassed disgusted moved proud relaxed grateful curious sarcastic "
    "disdainful unhappy anxious hysterical indifferent uncertain doubtful confused disappointed regretful "
    "guilty ashamed jealous envious hopeful optimistic pessimistic nostalgic lonely bored contemptuous "
    "sympathetic compassionate determined resigned").split())
S1_TONES = frozenset(("in a hurry tone", "shouting", "screaming", "whispering", "soft tone"))
S1_EFFECTS = frozenset(("laughing", "chuckling", "sobbing", "crying loudly", "sighing", "groaning",
                        "panting", "gasping", "yawning", "snoring"))
S1_SPECIAL = frozenset(("audience laughing", "background laughter", "crowd laughing", "break", "long-break"))
S1_TAGS = S1_EMOTIONS | S1_TONES | S1_EFFECTS | S1_SPECIAL
S2_EXTRA_CUES = frozenset(("emphasis", "clear throat", "whisper", "laugh", "sigh", "gasp", "pause",
                           "inhale", "exhale"))
KNOWN_CUES = S1_TAGS | S2_EXTRA_CUES

# Common S2 spellings -> the S1 tag with the same meaning.
_S1_ALIASES: Dict[str, str] = {
    "whisper": "whispering", "whispers": "whispering", "laugh": "laughing", "laughs": "laughing",
    "chuckle": "chuckling", "chuckles": "chuckling", "sigh": "sighing", "sighs": "sighing",
    "gasp": "gasping", "gasps": "gasping", "sob": "sobbing", "sobs": "sobbing", "groan": "groaning",
    "pant": "panting", "yawn": "yawning", "shout": "shouting", "shouts": "shouting",
    "scream": "screaming", "soft": "soft tone", "softly": "soft tone", "hurried": "in a hurry tone",
    "in a hurry": "in a hurry tone", "pause": "break", "short pause": "break", "long pause": "long-break",
    "long break": "long-break", "cry": "crying loudly", "crying": "crying loudly", "joyful": "delighted",
    "furious": "angry", "terrified": "scared", "ecstatic": "excited", "cheerful": "happy",
    "joyous": "delighted", "fearful": "scared", "afraid": "scared", "annoyed": "frustrated",
}
_INTENSITY_WORDS = re.compile(r"^(?:slightly|very|extremely|a bit|a little|mildly|really|quite|so|deeply)\s+")

CONTROL_TOKEN_RE = re.compile(r"<\|[A-Za-z0-9_.:-]{1,64}\|>")
SPEAKER_TOKEN_RE = re.compile(r"<\|speaker:(\d+)\|>")
BRACKET_CUE_RE = re.compile(r"\[([^\[\]\n]{1,120})\]")
_PAREN_TAG_RE = re.compile(r"\(([^()\n]{1,40})\)")
# Hermes < the control-token fix turned "<|speaker:0|>" into "<; speaker:0; >" and dropped the
# underscores of "phoneme_start" (italic rule); undo that so the plugin works on older builds.
_MANGLED_TOKEN_RE = re.compile(r"<;\s*(speaker:\d+|phoneme_?start|phoneme_?end)\s*;\s*>")
_SENTENCE_RE = re.compile(r"[^.!?。！？]+(?:[.!?。！？]+|$)\s*")
MAX_CUES_PER_SENTENCE = 3


def repair_control_tokens(text: str) -> str:
    return _MANGLED_TOKEN_RE.sub(
        lambda m: "<|" + m.group(1).replace("phonemestart", "phoneme_start").replace("phonemeend", "phoneme_end") + "|>",
        text)


def spoken_words(text: str) -> List[str]:
    """The words a listener hears: cues and control tokens removed."""
    return CONTROL_TOKEN_RE.sub(" ", BRACKET_CUE_RE.sub(" ", text)).split()


def has_cues(text: str) -> bool:
    """True when the text already carries delivery markup (the agent directed it; do not rewrite)."""
    return bool(BRACKET_CUE_RE.search(text) or SPEAKER_TOKEN_RE.search(text) or any(
        m.group(1).strip().lower() in S1_TAGS for m in _PAREN_TAG_RE.finditer(text)))


def _to_s1_tags(cue: str) -> Tuple[List[str], List[str]]:
    """Map one free-form cue ("slightly sad, whispering") to S1 tags; returns ``(tags, unmapped)``."""
    tags, unmapped = [], []
    for part in re.split(r",|\band\b|/", cue.lower()):
        part = _INTENSITY_WORDS.sub("", part.strip())
        if not part:
            continue
        tag = part if part in S1_TAGS else _S1_ALIASES.get(part)
        (tags if tag else unmapped).append(tag or part)
    return tags, unmapped


def _sentences(text: str) -> List[str]:
    return [s for s in _SENTENCE_RE.findall(text) if s.strip()] or [text]


def _hoist_s1_emotions(text: str) -> Tuple[str, int]:
    """S1 reads a mid-sentence emotion tag badly; move each to the start of its sentence."""
    moved, out = 0, []
    for sentence in _sentences(text):
        lead = re.match(r"\s*(?:\([^()]+\)\s*)*", sentence)
        body = sentence[lead.end():]
        found = [m.group(0) for m in _PAREN_TAG_RE.finditer(body) if m.group(1) in S1_EMOTIONS]
        if not found:
            out.append(sentence)
            continue
        moved += len(found)
        body = _PAREN_TAG_RE.sub(lambda m: "" if m.group(1) in S1_EMOTIONS else m.group(0), body)
        out.append(lead.group(0).rstrip() + "".join(found) + " " + re.sub(r"\s{2,}", " ", body).lstrip())
    return "".join(out), moved


def compile_for_model(text: str, model: FishModel) -> Tuple[str, List[str]]:
    """Compile agent markup for *model*; returns ``(text, warnings)``."""
    warnings: List[str] = []
    text = repair_control_tokens(text)
    if model.cue_syntax == "paren":
        dropped: List[str] = []

        def _bracket_to_paren(m: re.Match) -> str:
            tags, unmapped = _to_s1_tags(m.group(1))
            dropped.extend(unmapped)
            return "".join(f"({t})" for t in tags)

        text = BRACKET_CUE_RE.sub(_bracket_to_paren, text)
        if dropped:
            warnings.append(f"{model.id} only understands its fixed tag set; removed cues it would read "
                            f"aloud: {', '.join(sorted(set(dropped)))}. Use an S2 model for free-form cues.")
        text, moved = _hoist_s1_emotions(text)
        if moved:
            warnings.append(f"Moved {moved} emotion tag(s) to the start of their sentence ({model.id} "
                            "requires sentence-initial emotions).")
    else:
        text = _PAREN_TAG_RE.sub(
            lambda m: f"[{m.group(1).strip()}]" if m.group(1).strip().lower() in KNOWN_CUES else m.group(0), text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    warnings.extend(lint(text, model))
    return text, warnings


def lint(text: str, model: FishModel) -> List[str]:
    """Advisory checks from Fish's emotion best practices."""
    warnings: List[str] = []
    cue_re = BRACKET_CUE_RE if model.cue_syntax == "bracket" else _PAREN_TAG_RE
    for sentence in _sentences(CONTROL_TOKEN_RE.sub(" ", text)):
        count = len(cue_re.findall(sentence))
        if count > MAX_CUES_PER_SENTENCE:
            warnings.append(f"{count} cues in one sentence ({sentence.strip()[:60]!r}); Fish recommends at most "
                            f"{MAX_CUES_PER_SENTENCE}.")
    for m in BRACKET_CUE_RE.finditer(text):
        if len(m.group(1)) > 60:
            warnings.append(f"Cue [{m.group(1)[:40]}...] is long; short descriptions steer delivery better.")
    starts, ends = text.count("<|phoneme_start|>"), text.count("<|phoneme_end|>")
    if starts != ends:
        warnings.append(f"Unbalanced phoneme tags ({starts} start, {ends} end); the span may be read literally.")
    return warnings


def apply_direction(text: str, direction: Optional[str], model: FishModel) -> Tuple[str, List[str]]:
    """Turn overall delivery direction ("warm, amused, unhurried") into a leading cue."""
    direction = re.sub(r"[\[\]()]", "", direction or "").strip()
    if not direction:
        return text, []
    if model.cue_syntax == "bracket":
        head = SPEAKER_TOKEN_RE.match(text)
        if head:  # keep the first speaker token in front
            return f"{head.group(0)}[{direction}] {text[head.end():].lstrip()}", []
        return f"[{direction}] {text}", []
    tags, unmapped = _to_s1_tags(direction)
    warnings = [f"{model.id} cannot express direction terms: {', '.join(unmapped)}."] if unmapped else []
    return ("".join(f"({t})" for t in tags) + " " + text if tags else text), warnings


def build_dialogue(lines: Sequence[Dict[str, str]]) -> Tuple[str, List[str]]:
    """``[{speaker, text}]`` -> ``(text with <|speaker:N|> turns, speaker names by index)``; speakers are
    numbered in order of first appearance."""
    names: List[str] = []
    parts: List[str] = []
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ValueError(f"lines[{i}] must be an object with 'speaker' and 'text'.")
        speaker = str(line.get("speaker") or "").strip()
        body = str(line.get("text") or "").strip()
        if not speaker or not body:
            raise ValueError(f"lines[{i}] needs both 'speaker' and 'text'.")
        if speaker not in names:
            names.append(speaker)
        parts.append(f"<|speaker:{names.index(speaker)}|>{body}")
    if not parts:
        raise ValueError("lines is empty.")
    return "".join(parts), names


def speaker_indices(text: str) -> List[int]:
    return sorted({int(i) for i in SPEAKER_TOKEN_RE.findall(text)})


def strip_speaker_tokens(text: str) -> str:
    return SPEAKER_TOKEN_RE.sub(" ", text).strip()


def split_for_requests(text: str, max_chars: int) -> List[str]:
    """Sentence-safe split under ``max_chars`` that never cuts a control token and re-opens the active
    speaker at the top of every chunk, so each request stands alone."""
    if len(text) <= max_chars:
        return [text]
    pieces = re.split(r"(?<=[.!?。！？])\s+|(?=<\|speaker:\d+\|>)", text)
    chunks: List[str] = []
    current, speaker = "", None
    for piece in filter(None, (p.strip() for p in pieces)):
        opening = SPEAKER_TOKEN_RE.match(piece)
        prefix = f"<|speaker:{speaker}|>" if speaker is not None and not current and not opening else ""
        candidate = (current + " " if current else "") + prefix + piece
        if current and len(candidate) > max_chars:
            chunks.append(current)
            prefix = f"<|speaker:{speaker}|>" if speaker is not None and not opening else ""
            candidate = prefix + piece
        current = candidate
        found = SPEAKER_TOKEN_RE.findall(piece)
        if found:
            speaker = found[-1]
    if current:
        chunks.append(current)
    return chunks


def unknown_voice_indices(indices: Iterable[int], voice_count: int) -> List[int]:
    return [i for i in indices if i >= voice_count]
