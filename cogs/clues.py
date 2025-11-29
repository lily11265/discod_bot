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
            db = self.bot.get_cog("Survival").db
            
            # 모든 유저 조회
            users = db.fetch_all("SELECT DISTINCT user_id FROM user_clues")
            
            for (user_id,) in users:
                await self.check_user_combinations(user_id)
        except Exception as e:
            logger.error(f"Error in check_combinations_task: {e}")
    
    async def check_user_combinations(self, user_id):
        """특정 유저의 정보 조합 체크"""
        try:
            db = self.bot.get_cog("Survival").db
            
            # 유저가 보유한 단서 목록
            user_clues = db.fetch_all(
                "SELECT clue_id FROM user_clues WHERE user_id = ?", 
                (user_id,)
            )
            clue_ids = [c[0] for c in user_clues]
            
            # 조합 규칙 로드 (시트 또는 DB)
            combinations = self.get_combination_rules()
            
            for combo_key, result_clue in combinations.items():
                required_clues = combo_key.split('+')
                
                # 모든 필요 단서를 가지고 있는지 확인
                if all(req in clue_ids for req in required_clues):
                    # 이미 결과 단서를 가지고 있는지 확인
                    if result_clue in clue_ids:
                        continue
                    
                    # 지성 판정
                    stats = self.sheets.get_user_stats(discord_id=str(user_id))
                    if not stats:
                        continue
                    
                    user_state = db.fetch_one(
                        "SELECT current_sanity FROM user_state WHERE user_id = ?",
                        (user_id,)
                    )
                    
                    sanity_percent = user_state[0] / 100.0 if user_state else 1.0
                    current_intelligence = GameLogic.calculate_current_stat(
                        stats['intelligence'],
                        sanity_percent
                    )
                    
                    target = GameLogic.calculate_target_value(current_intelligence)
                    dice = GameLogic.roll_dice()
                    
                    if dice >= target:
                        # 조합 성공
                        db.execute_query(
                            "INSERT INTO user_clues (user_id, clue_id, clue_name) VALUES (?, ?, ?)",
                            (user_id, result_clue, result_clue)  # clue_name은 별도 조회 필요
                        )
                        
                        user = self.bot.get_user(user_id)
                        if user:
                            await user.send(
                                f"💡 **정보 조합 성공!**\n"
                                f"{' + '.join(required_clues)} → **{result_clue}**\n"
                                f"새로운 정보를 도출했습니다!"
                            )
        except Exception as e:
            logger.error(f"Error in check_user_combinations for {user_id}: {e}")
    
    def get_combination_rules(self) -> dict:
        """조합 규칙 로드"""
        # TODO: 구글 시트 B의 "정보 조합" 시트에서 로드
        # 또는 설정 파일에서 로드
        return {
            "clue_desk1_basic+clue_calendar": "clue_ritual_date",
            "clue_ritual_date+clue_seven_pits": "clue_seven_disciples",
            # ...
        }
    
    @app_commands.command(name="단서목록", description="보유한 단서 목록을 확인합니다.")
    async def list_clues(self, interaction: discord.Interaction):
        db = self.bot.get_cog("Survival").db
        
        clues = db.fetch_all(
            "SELECT clue_name, acquired_at FROM user_clues WHERE user_id = ? ORDER BY acquired_at DESC",
            (interaction.user.id,)
        )
        
        if not clues:
            await interaction.response.send_message("보유한 단서가 없습니다.", ephemeral=True)
            return
        
        embed = discord.Embed(title="🔍 보유 단서 목록", color=0xe67e22)
        
        for clue_name, acquired_at in clues:
            embed.add_field(
                name=clue_name,
                value=f"획득: {acquired_at}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Clues(bot))
