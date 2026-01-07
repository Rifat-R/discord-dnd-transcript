import discord
from discord.sinks import Sink
from discord.ext import commands
import os
from datetime import datetime


class Recording(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.connections = {}
        self.recordings_dir = "recordings"
        os.makedirs(self.recordings_dir, exist_ok=True)

    @discord.slash_command()
    async def record(self, ctx: discord.ApplicationContext):
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

        # Send message with files
        await channel.send(
            f"🎙️ Recording completed! Saved locally for: {', '.join(recorded_users)}\n"
            f"📁 Session folder: `{session_folder}`\n"
            f"📊 Files saved: {len(saved_files)}",
            files=discord_files,
        )

    @discord.slash_command()
    async def stop_recording(self, ctx):
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


def setup(bot):  # this is called by Pycord to setup the cog
    bot.add_cog(Recording(bot))  # add the cog to the bot
