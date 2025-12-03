import discord
from discord.ext import commands, tasks
import logging
import os
from datetime import datetime
import io
import time

logger = logging.getLogger('cogs.log_manager')

class LogManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log_file_path = "bot_runtime.log"
        self.log_channel_id = 1444213969848897547
        self.log_guild_id = 1442404243578556429
        
        # 파일 핸들러 추가
        self.file_handler = None
        self.setup_file_logging()
        
        # 1시간마다 로그 업로드 (비활성화 요청으로 주석 처리)
        # self.upload_logs_task.start()
    
    def cog_unload(self):
        # self.upload_logs_task.cancel()
        # ✅ 핸들러 제거
        if self.file_handler:
            root_logger = logging.getLogger()
            root_logger.removeHandler(self.file_handler)
            self.file_handler.close()
    
    def setup_file_logging(self):
        """파일 로그 핸들러 설정"""
        root_logger = logging.getLogger()
        
        # ✅ 기존 핸들러 제거 (중복 방지)
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                root_logger.removeHandler(handler)
                handler.close()
        
        # 새 파일 핸들러 추가
        self.file_handler = logging.FileHandler(
            self.log_file_path,
            encoding='utf-8',
            mode='a'
        )
        self.file_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.file_handler.setFormatter(formatter)
        
        root_logger.addHandler(self.file_handler)
        logger.info("파일 로그 핸들러 설정 완료")
    
    # @tasks.loop(hours=1)
    # async def upload_logs_task(self):
    #     """1시간마다 로그 파일 업로드"""
    #     await self.upload_and_clear_logs(auto=True)
    
    # @upload_logs_task.before_loop
    # async def before_upload_logs_task(self):
    #     await self.bot.wait_until_ready()
    
    async def upload_and_clear_logs(self, target_channel=None, auto=False):
        """로그 파일 업로드 및 삭제"""
        try:
            if target_channel:
                channel = target_channel
            else:
                # 기본 채널 (설정된 경우)
                guild = self.bot.get_guild(self.log_guild_id)
                if not guild:
                    logger.error(f"서버 {self.log_guild_id}를 찾을 수 없습니다.")
                    return
                channel = guild.get_channel(self.log_channel_id)
                if not channel:
                    logger.error(f"채널 {self.log_channel_id}를 찾을 수 없습니다.")
                    return
            
            if not os.path.exists(self.log_file_path):
                if not auto:
                    await channel.send("⚠️ 업로드할 로그 파일이 없습니다.")
                return
            
            file_size = os.path.getsize(self.log_file_path)
            if file_size == 0:
                if not auto:
                    await channel.send("⚠️ 로그 파일이 비어있습니다.")
                return
            
            # ✅ 파일 핸들러 일시 제거 (파일 잠금 해제)
            root_logger = logging.getLogger()
            if self.file_handler:
                root_logger.removeHandler(self.file_handler)
                self.file_handler.close()
                self.file_handler = None
            
            # 잠시 대기 (파일 시스템 동기화)
            time.sleep(0.5)
            
            # 파일 읽기
            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                log_content = f.read()
            
            # 파일명 생성
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"bot_log_{timestamp}.txt"
            
            # Discord 파일 객체 생성
            file = discord.File(
                io.BytesIO(log_content.encode('utf-8')),
                filename=filename
            )
            
            # 임베드 생성
            embed = discord.Embed(
                title="🤖 봇 로그 업로드",
                description=f"파일 크기: {file_size:,} bytes",
                color=0x3498db,
                timestamp=datetime.now()
            )
            
            if auto:
                embed.add_field(
                    name="업로드 방식",
                    value="⏰ 자동 (1시간마다)",
                    inline=False
                )
            else:
                embed.add_field(
                    name="업로드 방식",
                    value="📝 수동 (!로그출력 명령어)",
                    inline=False
                )
            
            # 업로드
            await channel.send(embed=embed, file=file)
            
            # 로그 파일 삭제
            try:
                os.remove(self.log_file_path)
            except Exception as e:
                logger.error(f"로그 파일 삭제 실패: {e}")
            
            # 새 로그 파일 시작
            self.setup_file_logging()
            
            logger.info(f"로그 파일 업로드 완료: {filename}")
            
        except Exception as e:
            logger.error(f"로그 업로드 중 오류 발생: {e}")
            # 오류 발생 시에도 핸들러 복구
            if not self.file_handler:
                self.setup_file_logging()
    
    @commands.command(name="로그출력")
    async def manual_log_upload(self, ctx):
        """수동 로그 업로드 명령어"""
        # 채널 제한 제거: 어디서든 요청하면 해당 채널로 전송
        await ctx.send("📤 로그 파일 업로드 중...")
        await self.upload_and_clear_logs(target_channel=ctx.channel, auto=False)

async def setup(bot):
    await bot.add_cog(LogManager(bot))