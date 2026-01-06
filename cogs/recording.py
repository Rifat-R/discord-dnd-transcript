import discord
from discord.sinks import Sink
from discord.ext import commands


class Recording(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.connections = {}

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
        files = [
            discord.File(audio.file, f"{user_id}")
            for user_id, audio in sink.audio_data.items()
        ]
        await channel.send(
            f"finished recording audio for: {', '.join(recorded_users)}.",
            files=files,
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


def setup(bot):  # this is called by Pycord to setup the cog
    bot.add_cog(Recording(bot))  # add the cog to the bot
