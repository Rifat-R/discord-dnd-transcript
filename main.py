import discord
import os
from dotenv import load_dotenv

load_dotenv()

GUILD_ID = os.getenv("GUILD_ID")

if GUILD_ID is None:
    raise ValueError("GUILD_ID environment variable is not set.")

bot = discord.Bot(debug_guilds=[int(GUILD_ID)])

cogs_list = ["recording", "admin", "game"]

for cog in cogs_list:
    print(f"Loading cog: {cog}")
    bot.load_extension(f"cogs.{cog}")


@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!")


bot.run(os.getenv("TOKEN"))
