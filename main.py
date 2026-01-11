import discord
import os
from dotenv import load_dotenv

load_dotenv()
bot = discord.Bot(debug_guilds=[1012160557706661898])

cogs_list = ["recording", "admin", "game"]

for cog in cogs_list:
    print(f"Loading cog: {cog}")
    bot.load_extension(f"cogs.{cog}")


@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!")


bot.run(os.getenv("TOKEN"))
