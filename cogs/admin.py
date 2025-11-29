import discord
from discord.ext import commands, tasks
from discord import app_commands
from utils.sheets import SheetsManager
from utils.diagnostics import SelfDiagnostics
import config
import logging
import json
import datetime

logger = logging.getLogger('cogs.admin')

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sheets = SheetsManager()
        self.bot.investigation_data = self.sheets.get_investigation_data() # 초기 로드 (캐시 사용)
        self.sync_task.start() # 백그라운드 태스크 시작

    def cog_unload(self):
        self.sync_task.cancel()

    @tasks.loop(time=datetime.time(hour=3, minute=0))
    async def sync_task(self):
        """매일 03:00에 데이터를 동기화하고 백업합니다."""
        logger.info("Starting scheduled data sync (03:00 AM)...")
        await self.perform_sync()
        
        # 추가 백업 (DB -> Sheet)
        # 관리자가 수동으로 시트를 수정했을 수 있으므로, 
        # perform_sync()에서 시트->DB 동기화를 먼저 수행하고(옵션),
        # 여기서는 DB의 최신 상태를 시트에 백업합니다.
        # 하지만 perform_sync()는 현재 시트->메모리(캐시) 방향임.
        # 유저 요청: "매일 03:00 동기화 태스크: a. 시트 E열 읽기 → DB 업데이트, b. DB 읽기 → 시트 E열 쓰기"
        
        # perform_sync() 내에서 처리하도록 위임하거나 여기서 호출
        # perform_sync()는 "전체 동기화" 개념이므로 거기서 호출하는 것이 깔끔함.
        pass

    @sync_task.before_loop
    async def before_sync_task(self):
        await self.bot.wait_until_ready()

    async def perform_sync(self):
        """실제 동기화 로직 수행"""
        try:
            # 0. DB Manager 가져오기
            db_manager = self.bot.get_cog("Survival").db
            
            # 1. 메타데이터 (ID <-> 이름)
            self.sheets.get_metadata_map()
            
            # 2. 스탯 데이터
            self.sheets.fetch_all_stats()
            
            # 3. 조사 데이터
            data = self.sheets.fetch_investigation_data()
            if data:
                self.bot.investigation_data = data
                
            # 4. 아이템 & 광기 데이터 캐싱 (Phase 2)
            self.sheets.get_item_data("") # 전체 로드 트리거
            self.sheets.get_madness_data("") # 전체 로드 트리거
            
            # 5. 허기 동기화 (Phase 2)
            # a. 시트 -> DB (관리자 수동 수정 반영)
            self.sheets.sync_hunger_from_sheet(db_manager)
            
            # b. DB -> 시트 (백업)
            self.sheets.sync_hunger_to_sheet(db_manager)
            
            # 6. 캐시 저장
            self.sheets.save_cache()
            
            logger.info(f"Data sync completed at {datetime.datetime.now()}")
            return True
        except Exception as e:
            logger.error(f"Data sync failed: {e}")
            return False

    @app_commands.command(name="동기화", description="[관리자] 구글 시트 데이터를 동기화합니다.")
    async def sheet_sync(self, interaction: discord.Interaction):
        """
        구글 시트의 조사 데이터를 읽어와서 봇의 메모리에 로드합니다.
        """
        if interaction.user.id not in config.ADMIN_IDS:
            await interaction.response.send_message("❌ 관리자만 사용할 수 있는 명령어입니다.", ephemeral=True)
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        success = await self.perform_sync()
        
        if success:
            data_count = len(self.bot.investigation_data) if self.bot.investigation_data else 0
            await interaction.followup.send(f"✅ 데이터 동기화 및 캐시 저장 완료! (지역: {data_count}개)", ephemeral=True)
        else:
            await interaction.followup.send("❌ 동기화 중 오류 발생. 로그를 확인해주세요.", ephemeral=True)

    @app_commands.command(name="시스템점검", description="[관리자] 봇의 상태와 데이터 무결성을 점검합니다.")
    async def system_check(self, interaction: discord.Interaction):
        """
        시스템 상태 점검 명령어
        """
        if interaction.user.id not in config.ADMIN_IDS:
            await interaction.response.send_message("❌ 관리자만 사용할 수 있는 명령어입니다.", ephemeral=True)
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        # 1. 봇 지연시간 (Latency)
        bot_latency = round(self.bot.latency * 1000)
        
        # 2. 데이터 캐시 상태
        cache_status = "✅ 정상" if self.sheets.cached_data else "⚠️ 비어있음"
        
        # 3. 데이터 카운트
        stats_count = len(self.sheets.cached_data.get('stats', []))
        investigation_count = len(self.sheets.cached_data.get('investigation', {}))
        metadata_count = len(self.sheets.cached_data.get('metadata', {}))
        
        # 4. 구글 시트 연결 테스트 (핑)
        sheet_latency = "측정 중..."
        try:
            start_time = datetime.datetime.now()
            # 가벼운 메타데이터 시트 읽기 시도
            self.sheets.get_metadata_map()
            end_time = datetime.datetime.now()
            sheet_latency = f"{round((end_time - start_time).total_seconds() * 1000)}ms"
            sheet_status = "✅ 연결됨"
        except Exception as e:
            sheet_status = f"❌ 오류: {str(e)}"
            sheet_latency = "N/A"

        # 5. 종합 진단 (Diagnostics)
        diagnostics = SelfDiagnostics(self.sheets)
        report = diagnostics.run_all_tests()
        
        embed = discord.Embed(title="🛠️ 시스템 정밀 점검 보고서", color=0x3498db, timestamp=datetime.datetime.now())
        
        embed.add_field(name="🤖 봇 상태", value=f"Latency: {bot_latency}ms", inline=True)
        embed.add_field(name="📊 구글 시트", value=f"{sheet_status}\nPing: {sheet_latency}", inline=True)
        embed.add_field(name="💾 캐시", value=cache_status, inline=True)
        
        embed.add_field(name="� 데이터 현황", value=f"스탯: {stats_count}명 | 지역: {investigation_count}개", inline=False)
        
        # 진단 결과 표시
        logic_res = report['logic_stress']
        data_res = report['data_integrity']
        edge_res = report['edge_cases']
        
        embed.add_field(name="🎲 로직 스트레스 (1000회)", value=f"[{logic_res['status']}] {logic_res['details']}", inline=False)
        embed.add_field(name="🌳 데이터 무결성", value=f"[{data_res['status']}] {data_res['details']}", inline=False)
        embed.add_field(name="⚠️ 엣지 케이스", value=f"[{edge_res['status']}] {edge_res['details']}", inline=False)
        
        # 오류가 있다면 출력
        all_errors = logic_res.get('errors', []) + data_res.get('errors', []) + edge_res.get('errors', [])
        if all_errors:
            error_msg = "\n".join(all_errors[:5]) # 최대 5개
            if len(all_errors) > 5: error_msg += f"\n...외 {len(all_errors)-5}개"
            embed.add_field(name="❌ 발견된 문제", value=f"```{error_msg}```", inline=False)
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Admin(bot))
