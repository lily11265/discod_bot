import discord
from discord.ext import commands
import config
import os
import logging
import asyncio

# ✅ 수정됨: 로깅 설정 중복 제거
# logging.basicConfig(...) 제거하고 utils.logger.setup_logger()만 사용
from utils.logger import setup_logger
logger = logging.getLogger('discord_bot')
setup_logger()

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
            help_command=None  # 기본 help 명령어 비활성화
        )
        self.investigation_data = {}  # 조사 데이터 저장소
        
        # ✅ 데이터베이스 초기화 (봇 시작 시 즉시)
        from utils.database import DatabaseManager
        self.db_manager = DatabaseManager()
        logger.info("✅ Database initialized")
    
    async def setup_hook(self):
        """봇 시작 시 Cog 로드 및 초기화"""
        logger.info("Starting bot initialization...")
        
        # Cog 로드
        initial_extensions = [
            'cogs.admin',
            'cogs.investigation',
            'cogs.stats',
            'cogs.survival',
            'cogs.clues',
            'cogs.inventory',
            'cogs.log_manager' # 로그 매니저도 여기에 포함되어 있어야 함
        ]
        
        for extension in initial_extensions:
            try:
                await self.load_extension(extension)
                logger.info(f"Loaded extension: {extension}")
            except Exception as e:
                logger.error(f"Failed to load extension {extension}: {e}")
        
        # 슬래시 커맨드 동기화
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} commands")
        except Exception as e:
            logger.error(f"Error syncing commands: {e}")
    
    async def on_command_error(self, ctx, error):
        """명령어 오류 처리"""
        if isinstance(error, commands.CommandNotFound):
            return  # 존재하지 않는 명령어 무시
        
        logger.error(f"Command error: {error}")
        await ctx.send(f"❌ 오류가 발생했습니다: {str(error)}")

# 봇 실행
def main():
    """봇 메인 함수"""
    if not config.DISCORD_TOKEN:
        logger.error("❌ DISCORD_TOKEN이 설정되지 않았습니다. .env 파일을 확인해주세요.")
        return
    
    bot = RPGBot()
    
    try:
        bot.run(config.DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.error("❌ 잘못된 토큰입니다. DISCORD_TOKEN을 확인해주세요.")
    except Exception as e:
        logger.error(f"❌ 봇 실행 중 오류 발생: {e}")

if __name__ == "__main__":
    main()