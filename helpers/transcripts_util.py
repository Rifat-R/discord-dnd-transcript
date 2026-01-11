import collections
import os
import wave

import numpy as np
import webrtcvad
import whisper
from services import GameService, SessionData

whisper_model = whisper.load_model("base")


RECORDINGS_DIR = "recordings"


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
            trimmed_path = wav_path
            try:
                trimmed_path = _trim_audio_with_vad(
                    wav_path, os.path.join(session_folder, f"{base}_trimmed.wav")
                )
            except Exception:
                trimmed_path = wav_path

            result = whisper_model.transcribe(
                trimmed_path,
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

        if combined_segments:
            for start, user_id, text in _dedupe_segments(combined_segments):
                name = participant_names.get(user_id, f"User {user_id}")
                timestamp = _format_timestamp(start)
                f.write(f"[{timestamp}] {name}: {text}\n")
        else:
            for user_id, text in transcriptions.items():
                name = participant_names.get(user_id, f"User {user_id}")
                f.write(f"{name}: {text}\n")

    service = GameService()
    service.set_session_data(session_key, session_data)
