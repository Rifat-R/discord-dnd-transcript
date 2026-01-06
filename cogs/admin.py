import discord
from discord.ext import commands
import asyncio


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _is_admin(self, ctx: discord.ApplicationContext) -> bool:
        """Check if user has admin permissions (server admin or bot owner)"""
        return (
            ctx.author.guild_permissions.administrator
            or ctx.author.id == self.bot.owner_id
        )

    @discord.slash_command(
        name="sync_commands",
        description="Sync all slash commands globally (admin only)",
    )
    async def sync_commands(self, ctx: discord.ApplicationContext):
        """Sync all commands globally"""
        if not self._is_admin(ctx):
            await ctx.respond(
                "❌ You need admin permissions to use this command.", ephemeral=True
            )
            return

        await ctx.defer(ephemeral=True)

        try:
            synced = await self.bot.sync_commands()
            await ctx.respond(
                f"✅ Successfully synced {len(synced)} commands globally!",
                ephemeral=True,
            )
        except Exception as e:
            await ctx.respond(f"❌ Failed to sync commands: {str(e)}", ephemeral=True)

    @discord.slash_command(
        name="sync_guild", description="Sync commands for this server only (admin only)"
    )
    async def sync_guild(self, ctx: discord.ApplicationContext):
        """Sync commands for the current guild only"""
        if not self._is_admin(ctx):
            await ctx.respond(
                "❌ You need admin permissions to use this command.", ephemeral=True
            )
            return

        await ctx.defer(ephemeral=True)

        try:
            synced = await self.bot.sync_commands(guild=ctx.guild)
            await ctx.respond(
                f"✅ Successfully synced {len(synced)} commands for this server!",
                ephemeral=True,
            )
        except Exception as e:
            await ctx.respond(
                f"❌ Failed to sync guild commands: {str(e)}", ephemeral=True
            )

    @discord.slash_command(
        name="list_commands", description="List all registered commands (admin only)"
    )
    async def list_commands(self, ctx: discord.ApplicationContext):
        """List all registered commands"""
        if not self._is_admin(ctx):
            await ctx.respond(
                "❌ You need admin permissions to use this command.", ephemeral=True
            )
            return

        await ctx.defer(ephemeral=True)

        try:
            # Get global commands
            global_commands = await self.bot.get_application_commands()

            # Get guild commands
            guild_commands = await self.bot.get_application_commands(guild=ctx.guild)

            embed = discord.Embed(
                title="📋 Registered Commands", color=discord.Color.blue()
            )

            if global_commands:
                global_cmd_list = "\n".join(
                    f"• `/{cmd.name}` - {cmd.description}" for cmd in global_commands
                )
                embed.add_field(
                    name="🌍 Global Commands", value=global_cmd_list, inline=False
                )

            if guild_commands:
                guild_cmd_list = "\n".join(
                    f"• `/{cmd.name}` - {cmd.description}" for cmd in guild_commands
                )
                embed.add_field(
                    name="🏠 Server Commands", value=guild_cmd_list, inline=False
                )

            if not global_commands and not guild_commands:
                embed.description = "No commands found."

            embed.set_footer(
                text=f"Total: {len(global_commands or []) + len(guild_commands or [])} commands"
            )
            await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            await ctx.respond(f"❌ Failed to list commands: {str(e)}", ephemeral=True)

    @discord.slash_command(
        name="clear_commands",
        description="Clear all commands (admin only - use with caution!)",
    )
    async def clear_commands(
        self,
        ctx: discord.ApplicationContext,
        scope: str = discord.Option(
            str, "Choose scope to clear", choices=["global", "guild"], default="guild"
        ),
    ):
        """Clear all commands - use with caution!"""
        if not self._is_admin(ctx):
            await ctx.respond(
                "❌ You need admin permissions to use this command.", ephemeral=True
            )
            return

        await ctx.defer(ephemeral=True)

        try:
            if scope == "global":
                await self.bot.clear_application_commands()
                await ctx.respond(
                    "⚠️ Cleared all global commands. You'll need to restart the bot or run sync_commands to restore them.",
                    ephemeral=True,
                )
            else:
                await self.bot.clear_application_commands(guild=ctx.guild)
                await ctx.respond(
                    "⚠️ Cleared all server commands. Run sync_guild to restore them.",
                    ephemeral=True,
                )

        except Exception as e:
            await ctx.respond(f"❌ Failed to clear commands: {str(e)}", ephemeral=True)

    @discord.slash_command(
        name="bot_info", description="Show bot information and status"
    )
    async def bot_info(self, ctx: discord.ApplicationContext):
        """Show bot information"""
        embed = discord.Embed(title="🤖 Bot Information", color=discord.Color.green())

        embed.add_field(
            name="📡 Latency", value=f"{round(self.bot.latency * 1000)}ms", inline=True
        )
        embed.add_field(name="🏠 Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(
            name="👥 Users",
            value=str(sum(len(guild.members) for guild in self.bot.guilds)),
            inline=True,
        )
        embed.add_field(
            name="🔧 Cogs Loaded", value=str(len(self.bot.cogs)), inline=True
        )
        embed.add_field(
            name="📋 Commands",
            value=str(len(self.bot.application_commands)),
            inline=True,
        )

        embed.set_footer(text=f"Bot ID: {self.bot.user.id}")
        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Admin(bot))
