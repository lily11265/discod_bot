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
        self.daily_madness_recovery_check.start()
        self.check_hunger_penalties.start()

    async def check_hp_zero(self, user_id):
        """체력 0 체크 및 실신 처리"""
        try:
            state = self.db.fetch_one(
                "SELECT current_hp FROM user_state WHERE user_id = ?",
                (user_id,)
            )
            
            if state and state[0] <= 0:
                # 행동불능 회피 판정
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                if not stats:
                    return
                
                user_state = self.db.fetch_one(
                    "SELECT current_sanity FROM user_state WHERE user_id = ?",
                    (user_id,)
                )
                
                sanity_percent = user_state[0] / 100.0 if user_state else 1.0
                current_willpower = GameLogic.calculate_current_stat(
                    stats['willpower'],
                    sanity_percent
                )
                
                if GameLogic.check_incapacitated_evasion(current_willpower):
                    # 회피 성공: 체력 1 유지
                    self.db.execute_query(
                        "UPDATE user_state SET current_hp = 1 WHERE user_id = ?",
                        (user_id,)
                    )
                    
                    user = self.bot.get_user(user_id)
                    if user:
                        await user.send(
                            f"💪 **의지로 버텼습니다!**\n"
                            f"쓰러질 뻔했지만 의지력으로 견뎌냈습니다. (체력 1 유지)"
                        )
                else:
                    # 행동불능 상태
                    user = self.bot.get_user(user_id)
                    if user:
                        await user.send(
                            f"💀 **실신했습니다!**\n"
                            f"체력이 바닥나 의식을 잃었습니다. 동료의 도움이 필요합니다."
                        )
        except Exception as e:
            logger.error(f"Error in check_hp_zero: {e}")

    @tasks.loop(hours=24)
    async def daily_madness_recovery_check(self):
        """매일 광기 회복 가능성 체크"""
        try:
            # 광기를 가진 모든 유저
            users_with_madness = self.db.fetch_all(
                "SELECT DISTINCT user_id FROM user_madness"
            )
            
            for (user_id,) in users_with_madness:
                await self.check_madness_recovery(user_id)
        except Exception as e:
            logger.error(f"Error in daily_madness_recovery_check: {e}")

    async def check_madness_recovery(self, user_id):
        """광기 회복 조건 체크"""
        try:
            stats = self.sheets.get_user_stats(discord_id=str(user_id))
            
            if not stats:
                return
            
            # 정신력 임계값: 50 + (지성 * 0.3)
            threshold = 50 + (stats['intelligence'] * 0.3)
            
            user_state = self.db.fetch_one(
                "SELECT current_sanity FROM user_state WHERE user_id = ?",
                (user_id,)
            )
            
            current_sanity = user_state[0] if user_state else 0
            
            if current_sanity >= threshold:
                # 광기 목록 조회
                madness_list = self.db.fetch_all(
                    "SELECT id, madness_id, madness_name FROM user_madness WHERE user_id = ?",
                    (user_id,)
                )
                
                for madness_id_pk, madness_id, madness_name in madness_list:
                    # 광기 데이터에서 난이도 조회
                    madness_data = self.sheets.get_madness_data(madness_id)
                    if not madness_data:
                        continue
                    
                    difficulty = madness_data.get('recovery_difficulty', 0)
                    
                    # 회복 판정 (난이도가 높을수록 어려움)
                    dice = GameLogic.roll_dice()
                    
                    if dice >= (100 - difficulty):  # 난이도 5 → 95 이상 필요
                        # 회복 성공
                        self.db.execute_query(
                            "DELETE FROM user_madness WHERE id = ?",
                            (madness_id_pk,)
                        )
                        
                        user = self.bot.get_user(user_id)
                        if user:
                            await user.send(
                                f"🌟 **광기 회복!**\n"
                                f"'{madness_name}' 광기에서 벗어났습니다!"
                            )
        except Exception as e:
            logger.error(f"Error in check_madness_recovery: {e}")

    @tasks.loop(hours=24)
    async def check_hunger_penalties(self):
        """허기 0 상태 체크 및 페널티 적용"""
        try:
            users = self.db.fetch_all(
                "SELECT user_id, current_hunger, hunger_zero_days FROM user_state WHERE current_hunger <= 0"
            )
            
            for user_id, hunger, zero_days in users:
                zero_days += 1
                
                hp_damage = 0
                sanity_damage = 0
                
                if zero_days == 1:
                    # 경고만
                    pass
                elif zero_days == 2:
                    hp_damage = 10
                elif zero_days >= 3:
                    hp_damage = 20
                    sanity_damage = 10
                
                # 피해 적용
                if hp_damage > 0:
                    self.db.execute_query(
                        "UPDATE user_state SET current_hp = MAX(0, current_hp - ?) WHERE user_id = ?",
                        (hp_damage, user_id)
                    )
                
                if sanity_damage > 0:
                    self.db.execute_query(
                        "UPDATE user_state SET current_sanity = MAX(0, current_sanity - ?) WHERE user_id = ?",
                        (sanity_damage, user_id)
                    )
                
                # 일수 업데이트
                self.db.execute_query(
                    "UPDATE user_state SET hunger_zero_days = ? WHERE user_id = ?",
                    (zero_days, user_id)
                )
                
                # 알림
                user = self.bot.get_user(user_id)
                if user:
                    msg = f"⚠️ **굶주림 {zero_days}일차**\n"
                    if hp_damage > 0:
                        msg += f"체력 -{hp_damage}\n"
                    if sanity_damage > 0:
                        msg += f"정신력 -{sanity_damage}\n"
                    msg += "빨리 식사를 하세요!"
                    
                    await user.send(msg)
                
                # 체력 0 체크
                await self.check_hp_zero(user_id)
        except Exception as e:
            logger.error(f"Error in check_hunger_penalties: {e}")

    def cog_unload(self):
        self.daily_hunger_decay.cancel()
        self.daily_sanity_recovery.cancel()
        self.daily_madness_recovery_check.cancel()
        self.check_hunger_penalties.cancel()

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

        # 2. 아이템 데이터 확인 (시트 연동)
        item_data = self.sheets.get_item_data(item_name)
        
        if not item_data:
            # 시트에 없으면 기존 하드코딩 로직 (Fallback)
            recovery = 0
            if "빵" in item_name or "건빵" in item_name: recovery = 15
            elif "통조림" in item_name: recovery = 30
            else:
                await interaction.response.send_message("❌ 알 수 없는 아이템입니다.", ephemeral=True)
                return
        else:
            if item_data['type'] != '음식':
                await interaction.response.send_message("❌ 음식이 아닙니다.", ephemeral=True)
                return
            recovery = item_data['hunger_recovery']

        # 3. 허기 회복
        state = await self.get_user_state(interaction.user.id)
        # 최대 허기 50 (유저 요청 5.1)
        MAX_HUNGER = 50 
        
        if state['hunger'] >= MAX_HUNGER:
            await interaction.response.send_message("❌ 배가 부릅니다.", ephemeral=True)
            return
            
        new_hunger = min(MAX_HUNGER, state['hunger'] + recovery)
        
        # 4. DB 업데이트 (허기 증가, 아이템 감소)
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
                else:
                    # 회복 실패 알림 (DM)
                    user = self.bot.get_user(user_id)
                    if not user:
                        try:
                            user = await self.bot.fetch_user(user_id)
                        except:
                            pass
                    
                    if user:
                        try:
                            await user.send(
                                f"⚠️ 배고픔 때문에 정신이 회복되지 않습니다.\n"
                                f"필요 허기: {int(threshold)} (현재: {int(hunger)})"
                            )
                        except discord.Forbidden:
                            pass # DM 차단 등

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

    # --- Madness System ---

    async def trigger_madness_check(self, user_id):
        """
        정신력이 0에 도달했을 때 자동 호출되는 광기 판정
        """
        stats = self.sheets.get_user_stats(discord_id=str(user_id))
        if not stats: return

        intelligence = stats['intelligence']
        
        # 광기 저항 판정 (GameLogic 사용 권장하지만 여기서는 직접 구현)
        # 목표값 = 10 - (지성 - 40) * 0.6
        # (지성이 높을수록 목표값이 낮아짐 -> 성공 확률 낮아짐? 보통 지성이 높으면 광기에 취약하다는 설정?)
        # 유저 공식: 10 - (지성 - 40) * 0.6
        # 예: 지성 50 -> 10 - (10 * 0.6) = 4. 목표값 4 이하가 나와야 성공? (매우 어려움)
        # 예: 지성 30 -> 10 - (-10 * 0.6) = 16. 목표값 16 이하.
        # 즉, 지성이 높을수록 저항하기 어려움 (크툴루 신화 스타일)
        
        target_value = 10 - (intelligence - 40) * 0.6
        import random
        dice_roll = random.randint(1, 100)
        
        user = self.bot.get_user(user_id)
        if not user:
            try: user = await self.bot.fetch_user(user_id)
            except: pass
            
        if dice_roll <= target_value:
            # 저항 성공
            self.db.execute_query("UPDATE user_state SET current_sanity = 1 WHERE user_id = ?", (user_id,))
            if user:
                await user.send(f"🧠 **광기 저항 성공!** (주사위: {dice_roll} / 목표: {int(target_value)})\n논리로 광기를 버텨냈습니다. 정신력이 1이 됩니다.")
        else:
            # 저항 실패 -> 광기 획득
            await self.acquire_random_madness(user_id)
            if user:
                await user.send(f"😱 **광기 저항 실패...** (주사위: {dice_roll} / 목표: {int(target_value)})\n광기에 잠식됩니다.")

    async def acquire_random_madness(self, user_id, context='default'):
        """랜덤 광기 획득"""
        import random
        
        all_madness = self.sheets.get_madness_data()
        if not all_madness:
            logger.error("No madness data found.")
            return

        # 이미 보유한 광기 제외
        owned_madness = self.db.fetch_all("SELECT madness_id FROM user_madness WHERE user_id = ?", (user_id,))
        owned_ids = [m[0] for m in owned_madness]
        
        available_madness = [m for m in all_madness if m['madness_id'] not in owned_ids]
        
        if not available_madness:
            # 모든 광기 보유 중
            return
            
        # 랜덤 선택
        selected = random.choice(available_madness)
        
        # DB 저장
        self.db.execute_query(
            "INSERT INTO user_madness (user_id, madness_id, madness_name) VALUES (?, ?, ?)",
            (user_id, selected['madness_id'], selected['name'])
        )
        
        # 알림
        user = self.bot.get_user(user_id)
        if not user:
            try: user = await self.bot.fetch_user(user_id)
            except: pass
            
        if user:
            await user.send(
                f"🎭 **새로운 광기 획득: {selected['name']}**\n"
                f"{selected['description']}\n"
                f"효과: {selected['effect_type']} {selected['effect_value']}"
            )

async def setup(bot):
    await bot.add_cog(Survival(bot))
