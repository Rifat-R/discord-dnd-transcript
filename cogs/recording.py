import discord
from discord.sinks import Sink
from discord.ext import commands
import os
import re
from datetime import datetime
import whisper
from services import GameService
from helpers import transcribe_session


# Load a faster model for real-time transcription
whisper_model = whisper.load_model("base")


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
            discord.sinks.WaveSink(),  # The sink type to use.
            self.once_done,  # What to do once done.
            ctx.channel,  # The channel to disconnect from.
        )
        await ctx.respond("Started recording!")

    def _save_wavs_from_sink(self, session_folder: str, sink) -> dict[str, str]:
        os.makedirs(session_folder, exist_ok=True)

        paths: dict[str, str] = {}

        for user_id, audio in sink.audio_data.items():
            # audio.file is file-like (BytesIO/SpooledTemporaryFile)
            wav_filename = f"{user_id}.wav"
            wav_path = os.path.join(session_folder, wav_filename)

            audio.file.seek(0)
            with open(wav_path, "wb") as f:
                f.write(audio.file.read())

            paths[str(user_id)] = wav_path

        return paths

    async def once_done(self, sink: Sink, channel: discord.TextChannel, *args):
        service = GameService()
        channel_game_name = service.get_game(channel.guild.id, channel.id)
        global_game_name = service.get_game(channel.guild.id, None)
        session_name = channel_game_name or global_game_name or channel.name

        session_key = self._make_session_key(session_name)
        session_folder = os.path.join(self.recordings_dir, session_key)
        session_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        await channel.send("🔄 Processing recordings and transcribing audio...")

        audio_paths = self._save_wavs_from_sink(session_folder, sink)
        await transcribe_session(
            self.bot,
            session_key,
            audio_paths,
            guild_id=channel.guild.id if channel.guild else None,
            channel_id=channel.id,
            session_date=session_date,
        )

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
        """Stop recording audio in the current voice channel to save files and see transcriptions"""
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

        audio_paths = {
            user_id: os.path.join(session_folder, wav_filename)
            for user_id, wav_filename in data.items()
        }

        await ctx.respond(
            f"🔄 Re-transcribing audio for session '{session_id}'...", ephemeral=True
        )
        await transcribe_session(self.bot, session_id, audio_paths)
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
