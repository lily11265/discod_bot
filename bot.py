import discord
from discord.ext import commands
import config
import os
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_bot')

# 인텐트 설정 (필요한 권한 활성화)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# 봇 인스턴스 생성
class RPGBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=config.COMMAND_PREFIX,
            intents=intents,
            help_command=None,
            description="TRPG Investigation Bot"
        )

    async def setup_hook(self):
        """
        봇 시작 시 실행되는 훅.
        Cogs(확장 기능)를 로드합니다.
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logger.info('------')

bot = RPGBot()

if __name__ == '__main__':
    if not config.DISCORD_TOKEN:
        logger.error("Error: DISCORD_TOKEN not found in environment variables.")
    else:
        bot.run(config.DISCORD_TOKEN)
