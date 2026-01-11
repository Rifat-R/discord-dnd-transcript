import os
import whisper
from services import GameService, SessionData

whisper_model = whisper.load_model("base")


RECORDINGS_DIR = "recordings"


def _safe_name(name: str) -> str:
    # keep filenames safe and stable
    return (
        name.replace(" ", "_").replace("/", "_").replace("\\", "_").replace("..", "_")
    )


async def transcribe_session(
    bot,
    session_key: str,
    audio_paths: dict[str, str],  # user_id -> wav_path
) -> None:
    session_folder = os.path.join(RECORDINGS_DIR, session_key)
    os.makedirs(session_folder, exist_ok=True)

    transcriptions: dict[str, str] = {}
    session_data: SessionData = {}

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
            transcription_text = str(result.get("text", ""))
            transcriptions[user_id] = transcription_text

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

    # --- Combined transcript: overwrite every time ---
    recorded_users = [
        f"{participant_names[uid]} (<@{uid}>)" for uid in audio_paths.keys()
    ]
    combined_path = os.path.join(session_folder, "combined_transcript.txt")

    with open(combined_path, "w", encoding="utf-8") as f:
        f.write("Combined Session Transcript\n")
        f.write(f"{session_key}\n")
        f.write(f"Participants: {', '.join(recorded_users)}\n")
        f.write("=" * 50 + "\n\n")

        for user_id, text in transcriptions.items():
            name = participant_names.get(user_id, f"User {user_id}")
            f.write(f"{name}:\n{text}\n\n")

    service = GameService()
    service.set_session_data(session_key, session_data)
