import discord
from discord.sinks import Sink
from discord.ext import commands
import os
from datetime import datetime
import whisper

# Load a faster model for real-time transcription
whisper_model = whisper.load_model("base")


class Recording(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.connections = {}
        self.recordings_dir = "recordings"
        os.makedirs(self.recordings_dir, exist_ok=True)

    @discord.slash_command()
    async def start_record(self, ctx: discord.ApplicationContext):
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

    async def once_done(self, sink: Sink, channel: discord.TextChannel, *args):
        recorded_users = [f"<@{user_id}>" for user_id in sink.audio_data.keys()]
        await sink.vc.disconnect()

        # Create timestamp for folder name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_folder = os.path.join(self.recordings_dir, f"session_{timestamp}")
        os.makedirs(session_folder, exist_ok=True)

        saved_files = []
        discord_files = []
        transcriptions = {}

        await channel.send("🔄 Processing recordings and transcribing audio...")

        for user_id, audio in sink.audio_data.items():
            # Get user info for filename
            try:
                user = await self.bot.fetch_user(user_id)
                username = user.name.replace(" ", "_").replace("/", "_")
            except:
                username = f"user_{user_id}"

            # Save original WAV file locally
            wav_filename = f"{username}_{user_id}.wav"
            wav_path = os.path.join(session_folder, wav_filename)

            # Reset file pointer and save locally
            audio.file.seek(0)
            with open(wav_path, "wb") as f:
                f.write(audio.file.read())

            saved_files.append(wav_path)

            discord_files.append(discord.File(wav_path, wav_filename))

            # Transcribe audio using Whisper
            transcription_text = ""
            try:
                await channel.send(f"🎯 Transcribing {username}'s audio...")
                result = whisper_model.transcribe(wav_path)
                transcription_text = result["text"]
                transcriptions[user_id] = transcription_text

                # Save transcription to file
                transcription_filename = f"{username}_{user_id}_transcription.txt"
                transcription_path = os.path.join(
                    session_folder, transcription_filename
                )

                with open(transcription_path, "w", encoding="utf-8") as f:
                    f.write(f"Transcription for {username} (ID: {user_id})\n")
                    f.write(f"Session: {timestamp}\n")
                    f.write("=" * 50 + "\n\n")
                    f.write(transcription_text)  # type: ignore

                saved_files.append(transcription_path)

            except Exception as e:
                print(f"Error transcribing {wav_filename}: {e}")
                transcriptions[user_id] = f"Transcription failed: {str(e)}"

        # Create combined transcript file
        combined_transcript_path = os.path.join(
            session_folder, "combined_transcript.txt"
        )
        with open(combined_transcript_path, "w", encoding="utf-8") as f:
            f.write(f"Combined Session Transcript\n")
            f.write(f"Session: {timestamp}\n")
            f.write(f"Participants: {', '.join(recorded_users)}\n")
            f.write("=" * 50 + "\n\n")

            for user_id, transcription in transcriptions.items():
                try:
                    user = await self.bot.fetch_user(user_id)
                    username = user.name
                except:
                    username = f"User {user_id}"

                f.write(f"**{username}**:\n")
                f.write(f"{transcription}\n\n")

        saved_files.append(combined_transcript_path)

        # Prepare transcription summary for Discord
        transcript_summary = []
        for user_id, text in transcriptions.items():
            try:
                user = await self.bot.fetch_user(user_id)
                username = user.name
            except:
                username = f"User {user_id}"

            # Truncate long transcriptions for Discord display
            display_text = text[:200] + "..." if len(text) > 200 else text
            transcript_summary.append(f"**{username}**: {display_text}")

        # Send message with files and transcriptions
        await channel.send(
            f"🎙️ Recording completed! Saved locally for: {', '.join(recorded_users)}\n"
            f"📁 Session folder: `{session_folder}`\n"
            f"📊 Files saved: {len(saved_files)}\n"
            f"📝 Transcriptions: {len([t for t in transcriptions.values() if not t.startswith('Transcription')])}/{len(transcriptions)}\n\n"
            f"**Transcript Preview:**\n" + "\n".join(transcript_summary[:3]),
            files=discord_files[:10],  # Limit to 10 files for Discord
        )

        # Send the combined transcript as a separate file if it exists
        if os.path.exists(combined_transcript_path):
            await channel.send(
                f"📄 **Full combined transcript** for session {timestamp}:",
                file=discord.File(
                    combined_transcript_path, f"session_{timestamp}_transcript.txt"
                ),
            )

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
            if len(sessions) > 10:
                embed.set_footer(text=f"...and {len(sessions) - 10} more sessions")
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
            if len(transcripts) > 10:
                embed.set_footer(
                    text=f"...and {len(transcripts) - 10} more transcript sessions"
                )
            await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command()
    async def get_transcript(self, ctx: discord.ApplicationContext, session: str):
        """Get transcript from a specific session"""
        if not os.path.exists(self.recordings_dir):
            await ctx.respond("No recordings found.", ephemeral=True)
            return

        # Find the session folder
        session_folder = None
        for folder in os.listdir(self.recordings_dir):
            if session in folder:  # Allow partial match for convenience
                session_folder = os.path.join(self.recordings_dir, folder)
                break

        if not session_folder or not os.path.exists(session_folder):
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
