import discord
from discord.sinks import Sink
from discord.ext import commands
import os
import re
from datetime import datetime
from services import GameService
from helpers import transcribe_session, save_silence_removed_audio
from helpers.types import KnownSpeakerData
import base64
from pydub import AudioSegment


# Load a faster model for real-time transcription
class Recording(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.connections = {}
        self.recordings_dir = "recordings"
        os.makedirs(self.recordings_dir, exist_ok=True)

    def _slugify_name(self, name: str) -> str:
        lowered = name.lower().strip()
        cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
        cleaned = cleaned.strip("-")
        return cleaned or "session"

    def _make_session_key(self, name: str) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        base = f"{date_str} - {self._slugify_name(name)}"
        candidate = base
        suffix = 2

        while os.path.exists(os.path.join(self.recordings_dir, candidate)):
            candidate = f"{base} {suffix}"
            suffix += 1

        return candidate

    @discord.slash_command()
    async def start_recording(self, ctx: discord.ApplicationContext):
        """Start recording audio in your current voice channel"""
        if not isinstance(ctx.author, discord.Member):
            await ctx.respond("This command can only be used in a server.")
            return

        voice = ctx.author.voice

        if not voice:
            await ctx.respond("You aren't in a voice channel!")

        vc = await voice.channel.connect()
        self.connections.update({ctx.guild.id: vc})

        vc.start_recording(
            discord.sinks.WaveSink(),
            self.once_done,
            ctx.channel,
            sync_start=True,
        )
        await ctx.respond("Started recording!")

    def _to_data_url(self, path: str) -> str:
        with open(path, "rb") as fh:
            return "data:audio/wav;base64," + base64.b64encode(fh.read()).decode(
                "utf-8"
            )

    def _get_known_speaker_data_from_sink(
        self,
        session_folder_path: str,
        sink: discord.sinks.Sink,
        guild_id: int,
        channel_id: int | None,
    ) -> KnownSpeakerData:
        known_speaker_names = []
        known_speaker_references = []
        service = GameService()

        for user_id, audio in sink.audio_data.items():
            # audio.file is file-like (BytesIO/SpooledTemporaryFile)
            wav_filename = f"{user_id}.wav"
            wav_path = os.path.join(session_folder_path, wav_filename)

            audio.file.seek(0)
            with open(wav_path, "wb") as f:
                save_silence_removed_audio(audio.file, wav_path)

            # this is quite pretty

            character_name = (
                service.get_character(guild_id, user_id, channel_id) or user_id
            )
            print(f"Mapping user {user_id} to character '{character_name}'")

            known_speaker_names.append(character_name)
            data_url = self._to_data_url(wav_path)
            known_speaker_references.append(data_url)

        return KnownSpeakerData(
            known_speaker_names=known_speaker_names,
            known_speaker_references=known_speaker_references,
        )

    def _save_combined_wav_from_sink(
        self, session_folder: str, sink: discord.sinks.Sink
    ) -> str:
        os.makedirs(session_folder, exist_ok=True)

        segments = []
        for user_id, audio in sink.audio_data.items():
            audio.file.seek(0)

            try:
                seg = AudioSegment.from_file(audio.file)
                print(f"SEGMENT LENGTH for user {user_id}: {len(seg)} ms")
                if len(seg) > 0:
                    segments.append(seg)
            except Exception as e:
                print(f"Skipping user {user_id}: {e}")

        if not segments:
            raise ValueError("No valid audio segments found to combine.")

        # Calculate the longest audio clip to ensure no one gets cut off
        max_length_ms = max(len(seg) for seg in segments)

        padded_segments = []
        for seg in segments:
            if len(seg) < max_length_ms:
                silence = AudioSegment.silent(duration=max_length_ms - len(seg))
                seg += silence
            padded_segments.append(seg)

        combined = padded_segments[0]
        for seg in padded_segments[1:]:
            combined = combined.overlay(seg)

        combined_path = os.path.join(session_folder, "combined_audio.wav")
        combined.export(combined_path, format="wav")

        return combined_path

    async def once_done(self, sink: Sink, channel: discord.TextChannel, *args):
        service = GameService()
        voice_channel = sink.vc.channel if sink.vc else None
        voice_channel_id = voice_channel.id if voice_channel else None  # type: ignore
        channel_game_name = service.get_game(channel.guild.id, voice_channel_id)
        global_game_name = service.get_game(channel.guild.id, None)
        session_name = (
            channel_game_name
            or global_game_name
            or (voice_channel.name if voice_channel else channel.name)  # type: ignore
        )

        session_key = self._make_session_key(session_name)
        session_folder_path = os.path.join(self.recordings_dir, session_key)
        await channel.send("🔄 Processing recordings and transcribing audio...")

        audio_path = self._save_combined_wav_from_sink(session_folder_path, sink)
        known_speaker_data = self._get_known_speaker_data_from_sink(
            session_folder_path, sink, channel.guild.id, voice_channel_id
        )
        await transcribe_session(session_folder_path, audio_path, known_speaker_data)

        await sink.vc.disconnect()

        embed = discord.Embed(
            title="✅ Recording and Transcription Complete",
            description=f"Session ID: `{session_key}`\n"
            f"Use `/get_transcript session:{session_key}` to retrieve transcripts.\n"
            f"Use `/get_summary session:{session_key}` to retrieve the summary.",
            color=discord.Color.green(),
        )
        await channel.send(embed=embed)

    @discord.slash_command()
    async def stop_recording(self, ctx):
        """
        Stop recording audio in the current voice channel to save files and see transcriptions.
        This also triggers once_done function.
        """
        if ctx.guild.id in self.connections:
            vc = self.connections[ctx.guild.id]
            vc.stop_recording()

            del self.connections[ctx.guild.id]
            await ctx.delete()
        else:
            await ctx.respond("I am currently not recording here.")

    @discord.slash_command()
    async def list_recordings(self, ctx: discord.ApplicationContext):
        """List all recording sessions"""
        if not os.path.exists(self.recordings_dir):
            await ctx.respond("No recordings found.", ephemeral=True)
            return

        sessions = []
        for folder in os.listdir(self.recordings_dir):
            folder_path = os.path.join(self.recordings_dir, folder)
            if os.path.isdir(folder_path):
                files = [f for f in os.listdir(folder_path) if f.endswith((".wav"))]
                sessions.append(f"📁 `{folder}` - {len(files)} files")

        if not sessions:
            await ctx.respond("No recording sessions found.", ephemeral=True)
        else:
            embed = discord.Embed(
                title="📋 Recording Sessions",
                description="\n".join(sessions[:10]),  # Limit to 10 sessions
                color=discord.Color.blue(),
            )
            footer = "Use the exact session name for /get_transcript or /re_transcribe."
            if len(sessions) > 10:
                footer = f"...and {len(sessions) - 10} more sessions. {footer}"
            embed.set_footer(text=footer)
            await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command()
    async def cleanup_old_recordings(self, ctx: discord.ApplicationContext):
        """Clean up old recordings (admin only)"""
        days = 30  # Default to 30 days
        if (
            not isinstance(ctx.author, discord.Member)
            or not ctx.author.guild_permissions.administrator
        ):
            await ctx.respond(
                "❌ You need admin permissions to use this command.", ephemeral=True
            )
            return

        await ctx.defer(ephemeral=True)

        if not os.path.exists(self.recordings_dir):
            await ctx.respond("No recordings directory found.", ephemeral=True)
            return

        import time

        current_time = time.time()
        cutoff_time = current_time - (days * 24 * 60 * 60)

        deleted_folders = 0
        deleted_files = 0

        for folder in os.listdir(self.recordings_dir):
            folder_path = os.path.join(self.recordings_dir, folder)
            if os.path.isdir(folder_path):
                folder_time = os.path.getctime(folder_path)
                if folder_time < cutoff_time:
                    # Delete folder and all files
                    for file in os.listdir(folder_path):
                        file_path = os.path.join(folder_path, file)
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            deleted_files += 1
                    os.rmdir(folder_path)
                    deleted_folders += 1

        await ctx.respond(
            f"🧹 Cleanup complete!\n"
            f"📁 Deleted {deleted_folders} old session folders\n"
            f"📄 Deleted {deleted_files} files\n"
            f"📅 Removed recordings older than {days} days",
            ephemeral=True,
        )

    @discord.slash_command()
    async def list_transcripts(self, ctx: discord.ApplicationContext):
        """List all transcript files"""
        if not os.path.exists(self.recordings_dir):
            await ctx.respond("No recordings found.", ephemeral=True)
            return

        transcripts = []
        for folder in os.listdir(self.recordings_dir):
            folder_path = os.path.join(self.recordings_dir, folder)
            if os.path.isdir(folder_path):
                txt_files = [f for f in os.listdir(folder_path) if f.endswith(".txt")]
                if txt_files:
                    transcripts.append(
                        f"📄 `{folder}` - {len(txt_files)} transcript files"
                    )

        if not transcripts:
            await ctx.respond("No transcript files found.", ephemeral=True)
        else:
            embed = discord.Embed(
                title="📝 Transcript Files",
                description="\n".join(transcripts[:10]),  # Limit to 10 sessions
                color=discord.Color.green(),
            )
            footer = "Use the exact session name for /get_transcript or /re_transcribe."
            if len(transcripts) > 10:
                footer = (
                    f"...and {len(transcripts) - 10} more transcript sessions. {footer}"
                )
            embed.set_footer(text=footer)
            await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(description="Re-transcribe audio for a specific session")
    async def re_transcribe(self, ctx: discord.ApplicationContext, session_id: str):
        service = GameService()
        data = service.get_session_data(session_id)  # user_id -> wav_filename

        if not data:
            await ctx.respond(
                f"No session data found for '{session_id}'.", ephemeral=True
            )
            return

        session_folder = os.path.join(self.recordings_dir, session_id)

        audio_path = os.path.join(session_folder, "combined_audio.wav")

        await ctx.respond(
            f"🔄 Re-transcribing audio for session '{session_id}'...", ephemeral=True
        )
        await transcribe_session(session_folder, audio_path)
        await ctx.respond(
            f"✅ Re-transcription complete for session '{session_id}'.", ephemeral=True
        )

    @discord.slash_command()
    async def get_transcript(self, ctx: discord.ApplicationContext, session: str):
        """Get transcript from a specific session"""
        if not os.path.exists(self.recordings_dir):
            await ctx.respond("No recordings found.", ephemeral=True)
            return

        session_folder = os.path.join(self.recordings_dir, session)

        if not os.path.exists(session_folder):
            await ctx.respond(f"Session '{session}' not found.", ephemeral=True)
            return

        # Look for combined transcript first
        combined_transcript = os.path.join(session_folder, "combined_transcript.txt")
        if os.path.exists(combined_transcript):
            await ctx.respond(
                f"📄 **Combined transcript** for session {os.path.basename(session_folder)}:",
                file=discord.File(
                    combined_transcript,
                    f"combined_transcript_{os.path.basename(session_folder)}.txt",
                ),
                ephemeral=True,
            )
        else:
            # List individual transcripts
            txt_files = [f for f in os.listdir(session_folder) if f.endswith(".txt")]
            if txt_files:
                await ctx.respond(
                    f"📝 Found {len(txt_files)} transcript files in session {os.path.basename(session_folder)}:\n"
                    + "\n".join(f"• {f}" for f in txt_files),
                    ephemeral=True,
                )
            else:
                await ctx.respond(
                    f"No transcript files found in session {session}.", ephemeral=True
                )

    @discord.slash_command()
    async def get_summary(self, ctx: discord.ApplicationContext, session: str):
        """Get transcript from a specific session"""
        if not os.path.exists(self.recordings_dir):
            await ctx.respond("No recordings found.", ephemeral=True)
            return

        session_folder = os.path.join(self.recordings_dir, session)

        if not os.path.exists(session_folder):
            await ctx.respond(f"Session '{session}' not found.", ephemeral=True)
            return

        combined_transcript = os.path.join(session_folder, "combined_summary.md")
        if os.path.exists(combined_transcript):
            await ctx.respond(
                f"📄 **Summary file** for session {os.path.basename(session_folder)}:",
                file=discord.File(
                    combined_transcript,
                    f"summary_{os.path.basename(session_folder)}.md",
                ),
                ephemeral=True,
            )
        else:
            await ctx.respond(
                f"No summary file found in session `{session}`.", ephemeral=True
            )

    @discord.slash_command()
    async def transcription_status(self, ctx: discord.ApplicationContext):
        """Check transcription system status"""
        embed = discord.Embed(
            title="🔍 Transcription System Status", color=discord.Color.blue()
        )

        embed.add_field(
            name="🎯 Whisper AI",
            value="✅ Available - Using 'base' model",
            inline=False,
        )

        # Recordings directory status
        if os.path.exists(self.recordings_dir):
            session_count = len(
                [
                    f
                    for f in os.listdir(self.recordings_dir)
                    if os.path.isdir(os.path.join(self.recordings_dir, f))
                ]
            )
            embed.add_field(
                name="📁 Recordings Directory",
                value=f"✅ Available - {session_count} sessions",
                inline=True,
            )
        else:
            embed.add_field(
                name="📁 Recordings Directory", value="❌ Not found", inline=True
            )

        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):  # this is called by Pycord to setup the cog
    bot.add_cog(Recording(bot))  # add the cog to the bot
