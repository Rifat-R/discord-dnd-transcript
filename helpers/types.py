from typing import TypedDict


class KnownSpeakerData(TypedDict):
    known_speaker_names: list[str]
    known_speaker_references: list[str]


class SessionMetadata(TypedDict):
    game_name: str | None
    characters: list[str]
    session_folder: str
