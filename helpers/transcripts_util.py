import os

from openai import OpenAI
from helpers.types import SessionMetadata
from services import GameService
import logging

from helpers.types import KnownSpeakerData

logger = logging.getLogger(__name__)


RECORDINGS_DIR = "recordings"
SUMMARY_FILE_NAME = "combined_summary.md"
METADATA_FILE_NAME = "session_metadata.json"
OPENAI_MODEL = "gpt-4.1-mini"

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    logger.error("OPENAI_API_KEY environment variable not set")


def _load_session_metadata(session_folder: str) -> SessionMetadata | None:
    print(f"Loading session metadata for folder '{session_folder}'")
    service = GameService()
    data = service.get_session_data(session_folder)
    if not data:
        print(f"No metadata found for session folder '{session_folder}'")
        return None
    session_data = SessionMetadata(
        game_name=data.get("game_name"),
        characters=data.get("characters", []),
        session_folder=session_folder,
    )

    print(f"Loaded session metadata for folder '{session_folder}': {session_data}")
    return session_data


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


def _build_metadata_context(metadata: SessionMetadata) -> str:
    game_name = metadata.get("game_name")
    session_folder = metadata.get("session_folder")
    characters = metadata.get("characters", [])

    names_line = ", ".join(characters) if characters else "Unknown"
    game_line = session_folder

    return f"Game name: {game_name}\nGame/Date: {game_line}\nParticipants/Characters ({len(characters)}): {names_line}\n"


def _summarize_transcript(
    transcript_text: str, metadata: SessionMetadata | None
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
    if metadata:
        metadata_context = _build_metadata_context(metadata)
    else:
        metadata_context = "No metadata available."

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


async def transcribe_session(
    session_key: str,
    audio_path: str,
    known_speaker_data: KnownSpeakerData | None,
) -> None:
    session_folder_path = os.path.join(RECORDINGS_DIR, session_key)
    client = OpenAI(api_key=api_key)

    with open(audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-transcribe-diarize",
            file=audio_file,
            response_format="diarized_json",
            chunking_strategy="auto",
            extra_body=known_speaker_data or {},
        )
    diarized_transcript_path = os.path.join(
        session_folder_path, "combined_transcript.txt"
    )

    with open(diarized_transcript_path, "w", encoding="utf-8") as f:
        for segment in transcript.segments:
            f.write(
                f"[{segment.start:.2f} - {segment.end:.2f}] - {segment.speaker}: {segment.text}\n"
            )

    metadata = _load_session_metadata(session_key)
    summary = _summarize_transcript(
        transcript_text=open(diarized_transcript_path, "r", encoding="utf-8").read(),
        metadata=metadata,
    )

    summary_path = os.path.join(session_folder_path, SUMMARY_FILE_NAME)
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)
