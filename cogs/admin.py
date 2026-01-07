import discord
from discord.ext import commands


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _is_admin(self, ctx: discord.ApplicationContext) -> bool:
        """Check if user has admin permissions (server admin or bot owner)"""
        if isinstance(ctx.author, discord.Member):
            return (
                ctx.author.guild_permissions.administrator
                or ctx.author.id == self.bot.owner_id
            )
        else:
            return ctx.author.id == self.bot.owner_id

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
            await self.bot.sync_commands()
            await ctx.respond(
                f"✅ Successfully synced commands globally!",
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
            # Get all commands from bot
            all_commands = self.bot.application_commands

            embed = discord.Embed(
                title="📋 Registered Commands", color=discord.Color.blue()
            )

            if all_commands:
                cmd_list = []
                for cmd in all_commands:
                    if hasattr(cmd, "name") and hasattr(cmd, "description"):
                        cmd_list.append(f"• `/{cmd.name}` - {cmd.description}")

                if cmd_list:
                    embed.description = "\n".join(cmd_list[:20])  # Limit to 20 commands
                    if len(cmd_list) > 20:
                        embed.set_footer(
                            text=f"...and {len(cmd_list) - 20} more commands"
                        )
                else:
                    embed.description = "No valid commands found."
            else:
                embed.description = "No commands found."

            embed.set_footer(
                text=f"Total: {len(all_commands) if all_commands else 0} commands"
            )
            await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            await ctx.respond(f"❌ Failed to list commands: {str(e)}", ephemeral=True)

    @discord.slash_command(
        name="bot_info", description="Show bot information and status"
    )
    async def info(self, ctx: discord.ApplicationContext):
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
