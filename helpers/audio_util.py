import io
import os
from pydub import AudioSegment
from pydub.silence import split_on_silence


def save_silence_removed_audio(audio_buffer: io.BytesIO, output_path: str) -> None:
    """
    Reads audio from a BytesIO buffer, removes silence, trims to max 700KB,
    saves to disk, and returns None.
    """
    MAX_SIZE_KB = 700  # Target file size limit
    MAX_BYTES = MAX_SIZE_KB * 1024

    # Ensure pointer is at the start
    audio_buffer.seek(0)

    try:
        sound = AudioSegment.from_file(audio_buffer)
    except Exception as e:
        print(f"Warning: Could not process audio. Saving raw. Error: {e}")
        with open(output_path, "wb") as f:
            audio_buffer.seek(0)
            # Rough truncation for raw bytes if pydub fails
            f.write(audio_buffer.read(MAX_BYTES))
        return

    # 1. Silence Removal
    chunks = split_on_silence(
        sound, min_silence_len=500, silence_thresh=sound.dBFS - 14, keep_silence=100
    )

    if not chunks:
        combined = sound
    else:
        combined = sum(chunks)  # Pydub supports sum() for chunks

    # 2. Size Truncation Logic
    # WAV header is ~44 bytes, the rest is raw_data.
    # We check if raw data exceeds our limit.
    current_size = len(combined.raw_data)  # type: ignore

    if current_size > MAX_BYTES:
        # Calculate the ratio of how much we need to keep
        ratio = MAX_BYTES / current_size

        # Calculate new duration in milliseconds
        new_duration_ms = int(len(combined) * ratio)  # type: ignore

        # Slice the audio (take the first X seconds that fit)
        combined = combined[:new_duration_ms]  # type: ignore

        print(
            f"Audio truncated from {current_size / 1024:.1f}KB to {len(combined.raw_data) / 1024:.1f}KB for key speaker reference."
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    combined.export(output_path, format="wav")  # type: ignore
