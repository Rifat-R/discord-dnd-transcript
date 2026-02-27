import discord
import os
from dotenv import load_dotenv
from logging_config import setup_logging

load_dotenv()
setup_logging()

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


if __name__ == "__main__":
    bot.run(os.getenv("TOKEN"))
