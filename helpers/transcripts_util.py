import asyncio
import collections
import json
import os
import wave
from datetime import datetime

import numpy as np
import webrtcvad
import whisper
from openai import OpenAI
from services import GameService, SessionData
import logging

logger = logging.getLogger(__name__)
whisper_model = whisper.load_model("base")


RECORDINGS_DIR = "recordings"
SUMMARY_FILE_NAME = "combined_summary.md"
METADATA_FILE_NAME = "session_metadata.json"
OPENAI_MODEL = "gpt-4.1-mini"

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    logger.error("OPENAI_API_KEY environment variable not set")


def _safe_name(name: str) -> str:
    # keep filenames safe and stable
    return (
        name.replace(" ", "_").replace("/", "_").replace("\\", "_").replace("..", "_")
    )


def _format_timestamp(seconds: float) -> str:
    total_seconds = max(int(seconds), 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _parse_session_datetime(session_key: str) -> datetime | None:
    if not session_key.startswith("session_"):
        return None
    timestamp = session_key.replace("session_", "", 1)
    try:
        return datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _format_session_date(session_key: str, fallback: str = "Unknown date") -> str:
    parsed = _parse_session_datetime(session_key)
    if not parsed:
        return fallback
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _load_session_metadata(session_folder: str) -> dict:
    metadata_path = os.path.join(session_folder, METADATA_FILE_NAME)
    if not os.path.exists(metadata_path):
        return {}
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _write_session_metadata(session_folder: str, metadata: dict) -> None:
    metadata_path = os.path.join(session_folder, METADATA_FILE_NAME)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


def _chunk_text(text: str, max_chars: int = 12000) -> list[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def _call_openai(messages: list[dict[str, str]], max_tokens: int = 900) -> str:
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,  # type: ignore
        temperature=0.2,
        max_tokens=max_tokens,
    )

    choices = response.choices or []
    if not choices:
        raise RuntimeError("OpenAI response missing choices")
    content = choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI response missing content")
    return str(content).strip()


def _summary_template() -> str:
    return (
        "# Session Summary\n\n"
        "**Game/Date:** <fill>\n"
        "**Names:** <fill>\n"
        "**Party:**\n"
        "- <fill>\n"
        "**NPCs/Groups:**\n"
        "- <fill>\n\n"
        "## Places\n"
        "- <fill>\n\n"
        "## Key Points\n"
        "- <fill>\n\n"
        "## Action\n"
        "**Cause Of Combat**\n"
        "- <fill>\n"
        "**Combat**\n"
        "- <fill>\n"
        "**Events In Combat**\n"
        "- <fill>\n\n"
        "## Extracted Information\n"
        "**Combined Key Facts**\n"
        "- <fill>\n"
        "**What’s Known vs. Unknown**\n"
        "- <fill>\n"
        "**Plans**\n"
        "- <fill>\n"
        "**Risks & Mitigations**\n"
        "- <fill>\n"
        "**Decision Points Ahead**\n"
        "- <fill>\n"
        "**Why it matters**\n"
        "- <fill>\n\n"
        "## Loot & Supplies\n"
        "**Supplies:** <fill>\n"
        "**Potions:** <fill>\n"
        "**Valuables:** <fill>\n"
        "**Weapons (Magic):** <fill>\n"
        "**Weapons/Armor (Non-magical):** <fill>\n"
        "**Magic item pending ID:** <fill>\n\n"
        "## The Situation (one-page read)\n"
        "<fill>\n\n"
        "## This Season Recap for next game\n"
        "<fill>\n\n"
        "## What this covers (full-season recap)\n"
        "<fill>\n"
    )


def _build_metadata_context(metadata: dict, session_key: str) -> str:
    game_name = metadata.get("game_name")
    session_date = metadata.get("session_date") or _format_session_date(session_key)
    participants = metadata.get("participants", {})
    characters = metadata.get("characters", {})

    names_line = ", ".join(participants.values()) if participants else "Unknown"
    party_lines = []
    for user_id, name in participants.items():
        character = characters.get(str(user_id))
        if character:
            party_lines.append(f"- {character} ({name})")
    party_line = "\n".join(party_lines) if party_lines else "- Unknown"

    game_line = session_date
    if game_name:
        game_line = f"{game_name} — {session_date}"

    return (
        f"Game/Date: {game_line}\n"
        f"Participants: {names_line}\n"
        f"Party (if known):\n{party_line}\n"
    )


def _summarize_transcript(
    transcript_text: str, metadata: dict, session_key: str
) -> str:
    if not transcript_text.strip():
        raise RuntimeError("Transcript is empty")

    if api_key is None:
        raise RuntimeError("OpenAI API key is not set")

    chunks = _chunk_text(transcript_text)
    chunk_summaries: list[str] = []

    for index, chunk in enumerate(chunks, start=1):
        messages = [
            {
                "role": "system",
                "content": (
                    "You summarize D&D session transcript chunks. "
                    "Extract accurate facts, names, places, events, combat, loot, "
                    "plans, risks, and decisions. Be concise. "
                    "Return a compact bullet list. Avoid speculation."
                ),
            },
            {
                "role": "user",
                "content": f"Chunk {index}/{len(chunks)}:\n{chunk}",
            },
        ]
        chunk_summaries.append(_call_openai(messages, max_tokens=700))

    combined_notes = "\n\n".join(chunk_summaries)
    metadata_context = _build_metadata_context(metadata, session_key)

    final_messages = [
        {
            "role": "system",
            "content": (
                "You are a careful session summarizer. "
                "Use only the notes provided, keep it accurate and concise. "
                "Fill the markdown template exactly, replacing <fill>. "
                "Use '-' bullets where appropriate. If info is missing, write 'None mentioned' or 'Unknown'."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Context:\n{metadata_context}\n"
                "Chunk summaries:\n"
                f"{combined_notes}\n\n"
                "Template:\n"
                f"{_summary_template()}"
            ),
        },
    ]

    return _call_openai(final_messages, max_tokens=1800)


def _to_mono_16bit(pcm_data: bytes, channels: int, sample_width: int) -> bytes:
    if sample_width == 1:
        audio = np.frombuffer(pcm_data, dtype=np.uint8).astype(np.int16)
        audio = (audio - 128) << 8
    elif sample_width == 2:
        audio = np.frombuffer(pcm_data, dtype=np.int16)
    elif sample_width == 4:
        audio = np.frombuffer(pcm_data, dtype=np.int32)
        audio = (audio / 65536).astype(np.int16)
    else:
        raise ValueError("Unsupported sample width")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)

    return audio.tobytes()


def _trim_audio_with_vad(wav_path: str, output_path: str) -> str:
    with wave.open(wav_path, "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        pcm_data = wav_file.readframes(wav_file.getnframes())

    mono_pcm = _to_mono_16bit(pcm_data, channels, sample_width)

    vad = webrtcvad.Vad(2)
    frame_duration_ms = 30
    frame_size = int(sample_rate * frame_duration_ms / 1000)
    frame_bytes = frame_size * 2
    if frame_size == 0:
        return wav_path

    frames = [
        mono_pcm[i : i + frame_bytes]
        for i in range(0, len(mono_pcm) - frame_bytes + 1, frame_bytes)
    ]

    padding_ms = 300
    num_padding_frames = max(int(padding_ms / frame_duration_ms), 1)
    ring_buffer = collections.deque(maxlen=num_padding_frames)
    voiced_frames: list[bytes] = []
    triggered = False

    for frame in frames:
        is_speech = vad.is_speech(frame, sample_rate)
        if not triggered:
            ring_buffer.append((frame, is_speech))
            num_voiced = sum(1 for _, speech in ring_buffer if speech)
            if num_voiced > 0.9 * num_padding_frames:
                triggered = True
                voiced_frames.extend(f for f, _ in ring_buffer)
                ring_buffer.clear()
        else:
            voiced_frames.append(frame)
            ring_buffer.append((frame, is_speech))
            num_unvoiced = sum(1 for _, speech in ring_buffer if not speech)
            if num_unvoiced > 0.9 * num_padding_frames:
                triggered = False
                voiced_frames.extend(f for f, _ in ring_buffer)
                ring_buffer.clear()

    if not voiced_frames:
        return wav_path

    trimmed_pcm = b"".join(voiced_frames)
    with wave.open(output_path, "wb") as trimmed_file:
        trimmed_file.setnchannels(1)
        trimmed_file.setsampwidth(2)
        trimmed_file.setframerate(sample_rate)
        trimmed_file.writeframes(trimmed_pcm)

    return output_path


def _dedupe_segments(
    segments: list[tuple[float, str, str]], window_seconds: float = 2.0
) -> list[tuple[float, str, str]]:
    last_seen: dict[str, tuple[str, float]] = {}
    deduped: list[tuple[float, str, str]] = []

    for start, user_id, text in sorted(segments, key=lambda item: item[0]):
        last_text, last_time = last_seen.get(user_id, ("", -1.0))
        if text == last_text and start - last_time <= window_seconds:
            continue
        deduped.append((start, user_id, text))
        last_seen[user_id] = (text, start)

    return deduped


async def transcribe_session(
    session_key: str,
    audio_path: str,
) -> None:
    session_folder = os.path.join(RECORDINGS_DIR, session_key)
    os.makedirs(session_folder, exist_ok=True)
    client = OpenAI(api_key=api_key)

    with open(audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-transcribe-diarize",
            file=audio_file,
            response_format="diarized_json",
            chunking_strategy="auto",
        )

    for segment in transcript.segments:
        print(segment.speaker, segment.text, segment.start, segment.end)
