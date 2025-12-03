print("Imports start...")
import discord
print("Imported discord")
from discord.ext import commands
print("Imported commands")
import config
print("Imported config")
import os
import logging
import asyncio
from utils.database import DatabaseManager
print("Imported DatabaseManager")
from utils.logger import setup_logger
print("Imported setup_logger")

# 로깅 설정
logger = logging.getLogger('discord_bot')
setup_logger()
logger.setLevel(logging.DEBUG) # 디버그 레벨로 설정

# 인텐트 설정
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class RPGBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=config.COMMAND_PREFIX,
            intents=intents,
            help_command=None
        )
        self.db_manager = DatabaseManager()
        self.investigation_data = {}

    async def setup_hook(self):
        print("Starting setup_hook...")
        # 1. DB 초기화
        print("Initializing database...")
        await self.db_manager.initialize()
        print("Database initialized.")
        
        # 2. Cog 로드
        print("Loading cogs...")
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    print(f"Loading extension: {filename}")
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    logger.info(f'Loaded extension: {filename}')
                    print(f"Loaded extension: {filename}")
                except Exception as e:
                    logger.error(f'Failed to load extension {filename}: {e}')
                    print(f'Failed to load extension {filename}: {e}')
        
        # 3. 커맨드 싱크
        print("Syncing commands...")
        try:
            synced = await self.tree.sync()
            logger.info(f'Synced {len(synced)} commands')
            print(f'Synced {len(synced)} commands')
        except Exception as e:
            logger.error(f'Failed to sync commands: {e}')
            print(f'Failed to sync commands: {e}')
        print("setup_hook completed.")

    async def close(self):
        print("Closing bot...")
        await self.db_manager.close()
        await super().close()

def main():
    print("Starting main...")
    if not config.DISCORD_TOKEN:
        logger.error("❌ DISCORD_TOKEN이 설정되지 않았습니다. .env 파일을 확인해주세요.")
        print("❌ DISCORD_TOKEN이 설정되지 않았습니다. .env 파일을 확인해주세요.")
        return
    
    print("Creating bot instance...")
    bot = RPGBot()
    
    try:
        print("Running bot...")
        bot.run(config.DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.error("❌ 잘못된 토큰입니다. DISCORD_TOKEN을 확인해주세요.")
        print("❌ 잘못된 토큰입니다. DISCORD_TOKEN을 확인해주세요.")
    except Exception as e:
        logger.error(f"❌ 봇 실행 중 오류 발생: {e}")
        print(f"❌ 봇 실행 중 오류 발생: {e}")

if __name__ == "__main__":
    main()