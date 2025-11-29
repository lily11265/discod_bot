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
    else:
        bot.run(config.DISCORD_TOKEN)
