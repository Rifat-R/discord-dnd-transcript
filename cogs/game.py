import discord
from discord.ext import commands


class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    game = discord.SlashCommandGroup("game", "Commands related to game settings")

    @game.command(name="set")
    async def game_set(
        self,
        ctx: discord.ApplicationContext,
        name: discord.Option(str),  # type: ignore
        channel: discord.Option(discord.TextChannel),  # type: ignore
    ): ...

    @game.command()
    async def character_set(self, ctx: discord.ApplicationContext): ...

    @game.command()
    async def mapping(self, ctx: discord.ApplicationContext): ...

    @game.command()
    async def clear(self, ctx: discord.ApplicationContext): ...


def setup(bot):  # this is called by Pycord to setup the cog
    bot.add_cog(Game(bot))  # add the cog to the bot
