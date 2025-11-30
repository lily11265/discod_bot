import discord
from discord.ext import commands, tasks
from discord import app_commands
from utils.game_logic import GameLogic
from utils.sheets import SheetsManager
import logging

logger = logging.getLogger('cogs.clues')

class Clues(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sheets = SheetsManager()
        self.check_combinations_task.start()
    
    def cog_unload(self):
        self.check_combinations_task.cancel()
    
    @tasks.loop(minutes=5)
    async def check_combinations_task(self):
        """5분마다 모든 유저의 정보 조합 가능성 체크"""
        try:
            # ✅ Survival Cog이 로드되었는지 확인
            survival_cog = self.bot.get_cog("Survival")
            if not survival_cog:
                logger.warning("Survival Cog이 로드되지 않아 정보 조합 체크를 건너뜠니다.")
                return
            
            db = survival_cog.db
            
            users = db.fetch_all("SELECT DISTINCT user_id FROM user_clues")
            
            for (user_id,) in users:
                await self.check_user_combinations(user_id)
        except Exception as e:
            logger.error(f"Error in check_combinations_task: {e}")

    async def check_user_combinations(self, user_id):
        """유저의 단서 조합 확인 (구현 예정)"""
        pass

    @app_commands.command(name="단서", description="획득한 단서 목록을 확인합니다.")
    async def list_clues(self, interaction: discord.Interaction):
        """자신의 단서 목록 확인 (자신만 볼 수 있음)"""
        await interaction.response.defer(ephemeral=True)
        
        survival_cog = self.bot.get_cog("Survival")
        if not survival_cog:
            await interaction.followup.send("시스템 오류: Survival Cog을 찾을 수 없습니다.", ephemeral=True)
            return

        db = survival_cog.db
        clues = db.fetch_all("SELECT clue_id FROM user_clues WHERE user_id = ?", (interaction.user.id,))
        
        if not clues:
            await interaction.followup.send("획득한 단서가 없습니다.", ephemeral=True)
            return
            
        clue_list = [clue[0] for clue in clues]
        # TODO: 단서 ID를 이름으로 변환하는 로직 필요 (SheetsManager 등 활용)
        
        await interaction.followup.send(f"📜 **획득한 단서 목록**:\n" + "\n".join(clue_list), ephemeral=True)

async def setup(bot):
    await bot.add_cog(Clues(bot))