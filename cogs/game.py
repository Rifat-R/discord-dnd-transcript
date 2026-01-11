import discord
from discord.ext import commands
from services import GameService


class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    game = discord.SlashCommandGroup("game", "Commands related to game settings")

    @game.command(name="set")
    async def game_set(
        self,
        ctx: discord.ApplicationContext,
        name: str,
        channel: discord.VoiceChannel | None = None,
    ):
        """Set the game name and channel."""

        if not ctx.guild:
            await ctx.respond(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        service = GameService()
        channel_id = channel.id if channel else None

        service.set_game(ctx.guild.id, name, channel_id)

        if channel:
            embed = discord.Embed(
                title="Game Set",
                description=(
                    f"The game title for channel '{channel.name}' has been set to '{name}'."
                ),
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                title="Game Set",
                description=f"The default game title has been set to '{name}'.",
                color=discord.Color.green(),
            )

        await ctx.respond(embed=embed)

    @game.command()
    async def character_set(
        self,
        ctx: discord.ApplicationContext,
        name: str,
        channel: discord.VoiceChannel | None = None,
    ):
        """Set the character for the game."""
        if not ctx.guild:
            await ctx.respond(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        service = GameService()
        service.set_character(
            ctx.guild.id, ctx.user.id, name, channel.id if channel else None
        )

        embed = discord.Embed(
            title="Character Set",
            description=f"Your character for the game has been set to '{name}'.",
            color=discord.Color.blue(),
        )

        await ctx.respond(embed=embed)

    @game.command()
    async def mapping(
        self,
        ctx: discord.ApplicationContext,
        channel: discord.VoiceChannel | None = None,
    ):
        if not ctx.guild:
            await ctx.respond(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        service = GameService()
        mappings = service.get_mapping(ctx.guild.id, channel.id if channel else None)

        game_name = mappings["game_name"] or "Not set"
        characters = mappings["characters"]

        description = f"**Game Name:** {game_name}\n\n**Characters:**\n"
        if characters:
            for user_id, character in characters.items():
                user = await self.bot.fetch_user(int(user_id))
                description += f"- **{user.name}**: {character}\n"
        else:
            description += "No characters set."

        embed = discord.Embed(
            title="Game Mapping", description=description, color=discord.Color.purple()
        )
        await ctx.respond(embed=embed)

    @game.command()
    async def clear(
        self,
        ctx: discord.ApplicationContext,
        channel: discord.VoiceChannel | None = None,
    ):
        """Clear the game and character mapping for a channel or global."""
        if not ctx.guild:
            await ctx.respond(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        service = GameService()
        service.clear_mapping(ctx.guild.id, channel.id if channel else None)

        if channel:
            description = f"The game and character mapping for channel '{channel.name}' has been cleared."
        else:
            description = "The default game and character mapping has been cleared."

        embed = discord.Embed(
            title="Mapping Cleared", description=description, color=discord.Color.red()
        )
        await ctx.respond(embed=embed)


def setup(bot):
    bot.add_cog(Game(bot))
