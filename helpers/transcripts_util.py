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

whisper_model = whisper.load_model("base")


RECORDINGS_DIR = "recordings"
SUMMARY_FILE_NAME = "combined_summary.md"
METADATA_FILE_NAME = "session_metadata.json"
OPENAI_MODEL = "gpt-4.1-mini"


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
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
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
    bot,
    session_key: str,
    audio_paths: dict[str, str],  # user_id -> wav_path
    *,
    guild_id: int | None = None,
    channel_id: int | None = None,
) -> None:
    session_folder = os.path.join(RECORDINGS_DIR, session_key)
    os.makedirs(session_folder, exist_ok=True)

    transcriptions: dict[str, str] = {}
    session_data: SessionData = {}
    combined_segments: list[tuple[float, str, str]] = []

    # If you want the combined transcript to show names too:
    participant_names: dict[str, str] = {}

    for user_id, wav_path in audio_paths.items():
        # --- Resolve a nice display name ---
        display_name = f"User {user_id}"
        try:
            # pycord expects an int user id
            uid_int = int(user_id)
            user = await bot.fetch_user(uid_int)
            display_name = user.name  # or user.display_name if you have a Member
        except Exception:
            pass

        participant_names[user_id] = display_name

        # --- Keep a stable filename base for overwriting ---
        base = f"{_safe_name(display_name)}_{user_id}"
        wav_filename = os.path.basename(wav_path)

        # Store mapping for later retrieval (you can store wav_filename OR base + extension)
        session_data[user_id] = wav_filename

        print(f"Transcribing audio for {display_name} ({user_id}) from {wav_path}...")

        # --- Transcribe ---
        try:
            result = whisper_model.transcribe(
                wav_path,
                language="en",
                task="transcribe",
                temperature=0.0,
                condition_on_previous_text=False,
            )
            result_dict = result if isinstance(result, dict) else {}
            transcription_text = str(result_dict.get("text", ""))
            transcriptions[user_id] = transcription_text

            for segment in result_dict.get("segments", []) or []:
                if not isinstance(segment, dict):
                    continue
                start = float(segment.get("start", 0.0))
                text = str(segment.get("text", "")).strip()
                if text:
                    combined_segments.append((start, user_id, text))

            # Overwrite transcript for this user every time
            transcription_path = os.path.join(
                session_folder, f"{base}_transcription.txt"
            )
            with open(transcription_path, "w", encoding="utf-8") as f:
                f.write(f"Session: {session_key}\n")
                f.write(f"User: {display_name} (ID: {user_id})\n")
                f.write("=" * 50 + "\n\n")
                f.write(transcription_text)

        except Exception as e:
            transcriptions[user_id] = f"Transcription failed: {e}"

            # still overwrite error transcript so it reflects latest run
            transcription_path = os.path.join(
                session_folder, f"{base}_transcription.txt"
            )
            with open(transcription_path, "w", encoding="utf-8") as f:
                f.write(f"Session: {session_key}\n")
                f.write(f"User: {display_name} (ID: {user_id})\n")
                f.write("=" * 50 + "\n\n")
                f.write(f"Transcription failed: {e}")

    metadata = _load_session_metadata(session_folder)

    if guild_id is not None:
        service = GameService()
        mapping = service.get_mapping(guild_id, channel_id)
        metadata["game_name"] = mapping.get("game_name")
        metadata["characters"] = mapping.get("characters", {})
    else:
        service = GameService()

    metadata["participants"] = participant_names
    metadata.setdefault("session_date", _format_session_date(session_key))
    _write_session_metadata(session_folder, metadata)

    # --- Combined transcript: overwrite every time ---
    recorded_users = [
        f"{participant_names[uid]} (<@{uid}>)" for uid in audio_paths.keys()
    ]
    combined_path = os.path.join(session_folder, "combined_transcript.txt")
    combined_lines: list[str] = []

    with open(combined_path, "w", encoding="utf-8") as f:
        f.write("Combined Session Transcript\n")
        f.write(f"{session_key}\n")
        f.write(f"Participants: {', '.join(recorded_users)}\n")
        f.write("=" * 50 + "\n\n")

        if combined_segments:
            for start, user_id, text in _dedupe_segments(combined_segments):
                name = participant_names.get(user_id, f"User {user_id}")
                timestamp = _format_timestamp(start)
                line = f"[{timestamp}] {name}: {text}"
                f.write(f"{line}\n")
                combined_lines.append(line)
        else:
            for user_id, text in transcriptions.items():
                name = participant_names.get(user_id, f"User {user_id}")
                line = f"{name}: {text}"
                f.write(f"{line}\n")
                combined_lines.append(line)

    if combined_lines:
        try:
            summary_text = await asyncio.to_thread(
                _summarize_transcript,
                "\n".join(combined_lines),
                metadata,
                session_key,
            )
            summary_path = os.path.join(session_folder, SUMMARY_FILE_NAME)
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(summary_text)
        except Exception as e:
            print(f"Summary generation failed: {e}")

    service.set_session_data(session_key, session_data)
