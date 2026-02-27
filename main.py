import discord
import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger("mybot")
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", "%H:%M:%S"
    )
)

logger.addHandler(handler)
logger.propagate = False  # Important


if not discord.opus.is_loaded():
    logger.warning(
        "Opus library not loaded, web users will not have their voice recorded."
    )

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


if __name__ == "__main__":
    bot.run(os.getenv("TOKEN"))
