import discord
from discord.ext import commands
import config
import os
import logging
import asyncio

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # 콘솔 출력
        # 파일 핸들러는 LogManager에서 추가
    ]
)
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
        
        # ✅ 구글 시트 워크시트 초기화
        try:
            from utils.sheets import SheetsManager
            sheets = SheetsManager()
            sheets.initialize_worksheets()
            logger.info("✅ Google Sheets worksheets initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize worksheets: {e}")
        
        logger.info("Loading cogs...")
        
        cogs = [
            'cogs.log_manager',  # 로그 관리 먼저 로드
            'cogs.stats',
            'cogs.survival',
            'cogs.investigation',
            'cogs.admin',
            'cogs.clues'
        ]
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"✅ Loaded: {cog}")
            except Exception as e:
                logger.error(f"❌ Failed to load {cog}: {e}")
        
        # 슬래시 커맨드 동기화
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} slash command(s)")
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}")
    
    async def on_ready(self):
        """봇이 준비되었을 때"""
        logger.info(f'🤖 Logged in as {self.user} (ID: {self.user.id})')
        logger.info(f'📊 Connected to {len(self.guilds)} guild(s)')
        logger.info('------')
        
        # 봇 상태 메시지 설정
        await self.change_presence(
            activity=discord.Game(name="고립무원 | /상태")
        )
    
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