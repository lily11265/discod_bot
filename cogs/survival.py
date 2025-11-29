import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import logging
from utils.database import DatabaseManager
from utils.sheets import SheetsManager
import config

logger = logging.getLogger('cogs.survival')

class Survival(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.sheets = SheetsManager()
        self.daily_hunger_decay.start()
        self.daily_sanity_recovery.start()

    def cog_unload(self):
        self.daily_hunger_decay.cancel()
        self.daily_sanity_recovery.cancel()

    async def get_user_state(self, user_id):
        """DB에서 유저 상태를 가져옵니다. 없으면 생성합니다."""
        state = self.db.fetch_one("SELECT * FROM user_state WHERE user_id = ?", (user_id,))
        if not state:
            # 초기 데이터 생성 (시트에서 기본 스탯 가져와야 함)
            # 여기서는 기본값으로 생성하고 추후 동기화
            self.db.execute_query("INSERT INTO user_state (user_id) VALUES (?)", (user_id,))
            state = self.db.fetch_one("SELECT * FROM user_state WHERE user_id = ?", (user_id,))
        
        # Tuple to Dict
        return {
            "user_id": state[0],
            "hp": state[1],
            "sanity": state[2],
            "hunger": state[3],
            "infection": state[4],
            "last_hunger_update": state[5],
            "last_sanity_recovery": state[6],
            "hunger_zero_days": state[7]
        }

    # --- Hunger System ---

    @tasks.loop(hours=24)
    async def daily_hunger_decay(self):
        """매일 자정에 허기 감소"""
        logger.info("Running daily hunger decay task.")
        # 모든 유저 가져오기
        users = self.db.fetch_all("SELECT user_id FROM user_state")
        
        for (user_id,) in users:
            try:
                # 스탯 가져오기
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                willpower = stats['willpower'] if stats else 50 # 기본값
                
                # 감소량 계산: 10 + (의지 * 0.04)
                decay = 10 + (willpower * 0.04)
                
                # DB 업데이트
                self.db.execute_query(
                    "UPDATE user_state SET current_hunger = MAX(0, current_hunger - ?), last_hunger_update = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (decay, user_id)
                )
                
                # 허기 0 체크 및 페널티는 별도 로직이나 여기서 처리
                # ...
                
            except Exception as e:
                logger.error(f"Error processing hunger decay for {user_id}: {e}")

    @app_commands.command(name="허기확인", description="현재 허기 상태를 확인합니다.")
    async def check_hunger(self, interaction: discord.Interaction):
        state = await self.get_user_state(interaction.user.id)
        stats = self.sheets.get_user_stats(discord_id=str(interaction.user.id))
        willpower = stats['willpower'] if stats else 50
        
        decay = 10 + (willpower * 0.04)
        days_left = state['hunger'] / decay if decay > 0 else 999
        
        embed = discord.Embed(title="🍞 허기 상태", color=0xe67e22)
        embed.add_field(name="현재 허기", value=f"{int(state['hunger'])}/100", inline=True)
        embed.add_field(name="일일 소모량", value=f"{decay:.1f}", inline=True)
        embed.add_field(name="예상 지속일", value=f"{days_left:.1f}일", inline=True)
        
        if state['hunger'] <= 0:
            embed.description = "⚠️ **굶주림 상태입니다! 즉시 식사가 필요합니다.**"
            embed.color = 0xff0000
        elif state['hunger'] <= 20:
            embed.description = "배가 많이 고픕니다..."
            
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="식사", description="음식을 먹어 허기를 회복합니다.")
    @app_commands.describe(item_name="먹을 음식 이름")
    async def eat_food(self, interaction: discord.Interaction, item_name: str):
        # 1. 인벤토리 확인
        inventory_item = self.db.fetch_one(
            "SELECT count FROM user_inventory WHERE user_id = ? AND item_name = ?",
            (interaction.user.id, item_name)
        )
        
        if not inventory_item or inventory_item[0] < 1:
            await interaction.response.send_message("❌ 해당 아이템을 가지고 있지 않습니다.", ephemeral=True)
            return

        # 2. 아이템 데이터 확인 (음식 여부, 회복량)
        # TODO: SheetsManager에 get_item_data 구현 필요 (아이템데이터 시트 조회)
        # 임시 로직: 이름에 '빵'이나 '통조림'이 들어가면 음식으로 간주
        recovery = 0
        if "빵" in item_name or "건빵" in item_name:
            recovery = 15
        elif "통조림" in item_name:
            recovery = 30
        else:
            await interaction.response.send_message("❌ 음식이 아닌 것 같습니다.", ephemeral=True)
            return

        # 3. 허기 회복
        state = await self.get_user_state(interaction.user.id)
        if state['hunger'] >= 100:
            await interaction.response.send_message("❌ 배가 부릅니다.", ephemeral=True)
            return
            
        new_hunger = min(100, state['hunger'] + recovery)
        
        # 4. DB 업데이트 (허기 증가, 아이템 감소)
        self.db.execute_query(
            "UPDATE user_state SET current_hunger = ? WHERE user_id = ?",
            (new_hunger, interaction.user.id)
        )
        
        if inventory_item[0] == 1:
            self.db.execute_query("DELETE FROM user_inventory WHERE user_id = ? AND item_name = ?", (interaction.user.id, item_name))
        else:
            self.db.execute_query("UPDATE user_inventory SET count = count - 1 WHERE user_id = ? AND item_name = ?", (interaction.user.id, item_name))
            
        await interaction.response.send_message(f"🍞 {item_name}을(를) 먹었습니다. (허기 {int(state['hunger'])} -> {new_hunger})")

    # --- Sanity System ---

    @tasks.loop(hours=24)
    async def daily_sanity_recovery(self):
        """매일 아침 정신력 회복"""
        # 시간 체크 (06:00) 로직 필요하지만 일단 24시간 주기로 실행
        logger.info("Running daily sanity recovery task.")
        users = self.db.fetch_all("SELECT user_id, current_sanity, current_hunger FROM user_state")
        
        for (user_id, sanity, hunger) in users:
            try:
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                if not stats: continue
                
                intelligence = stats['intelligence']
                willpower = stats['willpower']
                
                # 허기 임계값: 30 + (지성 * 0.2)
                threshold = 30 + (intelligence * 0.2)
                
                if hunger >= threshold:
                    # 회복량: 10 + (의지 / 10)
                    recovery = 10 + (willpower / 10)
                    new_sanity = min(100, sanity + recovery)
                    
                    self.db.execute_query(
                        "UPDATE user_state SET current_sanity = ?, last_sanity_recovery = CURRENT_TIMESTAMP WHERE user_id = ?",
                        (new_sanity, user_id)
                    )
                    # 알림 전송 (선택사항)
            except Exception as e:
                logger.error(f"Error processing sanity recovery for {user_id}: {e}")

    @app_commands.command(name="휴식", description="휴식을 취해 정신력을 회복합니다. (하루 1회)")
    async def rest(self, interaction: discord.Interaction):
        state = await self.get_user_state(interaction.user.id)
        
        # 하루 1회 체크 (last_sanity_recovery 날짜 비교)
        if state['last_sanity_recovery']:
            last_date = datetime.datetime.strptime(state['last_sanity_recovery'], "%Y-%m-%d %H:%M:%S").date()
            if last_date == datetime.date.today():
                await interaction.response.send_message("❌ 이미 오늘 휴식을 취했습니다.", ephemeral=True)
                return

        stats = self.sheets.get_user_stats(discord_id=str(interaction.user.id))
        if not stats:
            await interaction.response.send_message("❌ 스탯 정보를 불러올 수 없습니다.", ephemeral=True)
            return

        # 허기 체크
        threshold = 30 + (stats['intelligence'] * 0.2)
        if state['hunger'] < threshold:
            await interaction.response.send_message(f"❌ 배가 너무 고파 휴식을 취할 수 없습니다. (필요 허기: {int(threshold)})", ephemeral=True)
            return

        # 회복
        recovery = 10 + (stats['willpower'] / 10)
        new_sanity = min(100, state['sanity'] + recovery)
        
        self.db.execute_query(
            "UPDATE user_state SET current_sanity = ?, last_sanity_recovery = CURRENT_TIMESTAMP WHERE user_id = ?",
            (new_sanity, interaction.user.id)
        )
        
        await interaction.response.send_message(f"💤 휴식을 취했습니다. (정신력 {int(state['sanity'])} -> {int(new_sanity)})")

    @app_commands.command(name="정신상태", description="현재 정신력과 광기 상태를 확인합니다.")
    async def check_sanity(self, interaction: discord.Interaction):
        state = await self.get_user_state(interaction.user.id)
        stats = self.sheets.get_user_stats(discord_id=str(interaction.user.id))
        
        # 광기 목록 조회
        madness_list = self.db.fetch_all("SELECT madness_name FROM user_madness WHERE user_id = ?", (interaction.user.id,))
        madness_names = [m[0] for m in madness_list] if madness_list else ["없음"]
        
        embed = discord.Embed(title="🧠 정신 상태", color=0x9b59b6)
        embed.add_field(name="현재 정신력", value=f"{int(state['sanity'])}/100", inline=True)
        embed.add_field(name="보유 광기", value=", ".join(madness_names), inline=False)
        
        if stats:
            threshold = 30 + (stats['intelligence'] * 0.2)
            embed.add_field(name="회복 필요 허기", value=f"{int(threshold)} 이상", inline=True)
            
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Survival(bot))
