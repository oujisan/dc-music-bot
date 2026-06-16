import discord
from discord.ext import commands
import config

class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=config.COMMAND_PREFIX, intents=intents, help_command=None)

    async def setup_hook(self):
        await self.load_extension("cogs.music")
        print("Modules loaded successfully.")

    async def on_ready(self):
        print(f"Operational system online. Logged in as {self.user}")

if __name__ == "__main__":
    bot = Bot()
    bot.run(config.BOT_TOKEN)