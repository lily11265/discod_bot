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
        """
        유저의 단서 조합을 확인하고, 조건을 만족하면 새로운 단서나 아이템을 지급합니다.
        
        작동 원리:
        1. DB에서 해당 유저가 보유한 모든 단서 ID를 가져옵니다.
        2. Google Sheets(Sheet B)에서 정의된 '단서 조합 레시피' 목록을 가져옵니다.
        3. 각 레시피에 대해 다음을 확인합니다:
           - 유저가 레시피의 '필요 단서'를 모두 가지고 있는가?
           - 유저가 이미 '결과물'(단서 또는 아이템)을 가지고 있지 않은가? (중복 지급 방지)
        4. 조건을 만족하면:
           - 결과물이 '단서'인 경우: DB의 user_clues 테이블에 추가합니다.
           - 결과물이 '아이템'인 경우: DB의 user_inventory 테이블에 추가합니다.
           - 유저에게 DM으로 성공 메시지(조합된 내용)를 보냅니다.
        """
        try:
            # 1. 유저가 보유한 단서 목록 조회 (DB)
            # Survival Cog의 DB 인스턴스를 빌려옵니다.
            survival_cog = self.bot.get_cog("Survival")
            if not survival_cog: return
            db = survival_cog.db
            
            # user_clues 테이블에서 user_id에 해당하는 모든 clue_id를 조회합니다.
            user_clues_data = db.fetch_all("SELECT clue_id FROM user_clues WHERE user_id = ?", (user_id,))
            # 조회된 튜플 리스트를 set으로 변환하여 검색 속도를 높입니다. (예: {'clue_A', 'clue_B'})
            user_clues = set(row[0] for row in user_clues_data)
            
            # 2. 단서 조합 레시피 조회 (Google Sheets)
            # SheetsManager를 통해 정의된 조합식을 가져옵니다.
            recipes = self.sheets.get_clue_combinations()
            
            # 3. 각 레시피 검사
            for recipe in recipes:
                # 레시피 구조: 
                # {
                #   "recipe_id": "comb_001", 
                #   "required_clues": ["clue_A", "clue_B"], 
                #   "result_type": "단서", 
                #   "result_id": "clue_C", 
                #   "message": "두 단서를 조합하여 새로운 사실을 알게 되었습니다!"
                # }
                
                required = set(recipe['required_clues'])
                
                # 3-1. 필요 단서를 모두 가지고 있는지 확인 (부분집합 여부 확인)
                if required.issubset(user_clues):
                    
                    # 3-2. 이미 보상을 받았는지 확인 (중복 지급 방지)
                    if recipe['result_type'] == '단서':
                        # 결과 단서를 이미 가지고 있는지 확인
                        if recipe['result_id'] in user_clues:
                            continue # 이미 가지고 있으면 스킵
                            
                        # 보상 지급: 단서 추가
                        db.execute_query(
                            "INSERT INTO user_clues (user_id, clue_id, clue_name) VALUES (?, ?, ?)",
                            (user_id, recipe['result_id'], recipe['result_id']) # 이름은 ID와 동일하게 처리하거나 별도 조회 필요
                        )
                        logger.info(f"User {user_id} combined clues {required} -> New Clue: {recipe['result_id']}")
                        
                    elif recipe['result_type'] == '아이템':
                        # 결과 아이템을 이미 가지고 있는지 확인 (인벤토리 조회)
                        has_item = db.fetch_one(
                            "SELECT count FROM user_inventory WHERE user_id = ? AND item_name = ?",
                            (user_id, recipe['result_id'])
                        )
                        if has_item and has_item[0] > 0:
                            continue # 이미 가지고 있으면 스킵 (아이템은 중복 소지 가능하게 할지 기획에 따라 다르나, 보통 조합 이벤트는 1회성)
                        
                        # 보상 지급: 아이템 추가
                        db.execute_query(
                            "INSERT INTO user_inventory (user_id, item_name, count) VALUES (?, ?, 1) "
                            "ON CONFLICT(user_id, item_name) DO UPDATE SET count = count + 1",
                            (user_id, recipe['result_id'])
                        )
                        logger.info(f"User {user_id} combined clues {required} -> New Item: {recipe['result_id']}")
                    
                    # 4. 유저에게 알림 전송
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            embed = discord.Embed(
                                title="🧩 단서 조합 성공!",
                                description=f"{recipe['message']}\n\n**획득**: {recipe['result_id']} ({recipe['result_type']})",
                                color=0x9b59b6 # 보라색
                            )
                            await user.send(embed=embed)
                        except discord.Forbidden:
                            logger.warning(f"Cannot send DM to user {user_id}")
                            
        except Exception as e:
            logger.error(f"Error checking combinations for user {user_id}: {e}")

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