from discord.ext import commands
import os  # default module
from dotenv import load_dotenv

load_dotenv()
bot = commands.Bot()

cogs_list = ["recording", "admin"]

for cog in cogs_list:
    bot.load_extension(f"cogs.{cog}")


@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!")


bot.run(os.getenv("TOKEN"))
