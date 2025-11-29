import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import logging
from utils.database import DatabaseManager
from utils.sheets import SheetsManager
from utils.game_logic import GameLogic
import config

logger = logging.getLogger('cogs.survival')

class Survival(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()
        self.sheets = SheetsManager()
        
        # ✅ 태스크 시작
        self.daily_hunger_decay.start()
        self.daily_sanity_recovery.start()  # ✅ 추가
        self.daily_madness_recovery_check.start()
        self.check_hunger_penalties.start()

    def cog_unload(self):
        self.daily_hunger_decay.cancel()
        self.daily_sanity_recovery.cancel()
        self.daily_madness_recovery_check.cancel()
        self.check_hunger_penalties.cancel()

    async def get_user_state(self, user_id):
        """DB에서 유저 상태를 가져옵니다. 없으면 생성합니다."""
        state = self.db.fetch_one("SELECT * FROM user_state WHERE user_id = ?", (user_id,))
        if not state:
            # 초기 데이터 생성
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
        users = self.db.fetch_all("SELECT user_id FROM user_state")
        
        for (user_id,) in users:
            try:
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                willpower = stats['willpower'] if stats else 50
                
                decay = 10 + (willpower * 0.04)
                
                self.db.execute_query(
                    "UPDATE user_state SET current_hunger = MAX(0, current_hunger - ?), last_hunger_update = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (decay, user_id)
                )
                
            except Exception as e:
                logger.error(f"Error processing hunger decay for {user_id}: {e}")

    @daily_hunger_decay.before_loop
    async def before_daily_hunger_decay(self):
        await self.bot.wait_until_ready()

    # ✅ 정신력 회복 태스크 추가
    @tasks.loop(hours=24)
    async def daily_sanity_recovery(self):
        """매일 06:00에 정신력 자동 회복"""
        logger.info("Running daily sanity recovery task.")
        users = self.db.fetch_all("SELECT user_id, current_sanity, current_hunger FROM user_state")
        
        for (user_id, sanity, hunger) in users:
            try:
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                if not stats:
                    continue
                
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
                            pass

            except Exception as e:
                logger.error(f"Error processing sanity recovery for {user_id}: {e}")

    @daily_sanity_recovery.before_loop
    async def before_daily_sanity_recovery(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def daily_madness_recovery_check(self):
        """매일 광기 회복 가능성 체크"""
        try:
            users_with_madness = self.db.fetch_all(
                "SELECT DISTINCT user_id FROM user_madness"
            )
            
            for (user_id,) in users_with_madness:
                await self.check_madness_recovery(user_id)
        except Exception as e:
            logger.error(f"Error in daily_madness_recovery_check: {e}")

    @daily_madness_recovery_check.before_loop
    async def before_daily_madness_recovery_check(self):
        await self.bot.wait_until_ready()

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
                    pass
                elif zero_days == 2:
                    hp_damage = 10
                elif zero_days >= 3:
                    hp_damage = 20
                    sanity_damage = 10
                
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
                
                self.db.execute_query(
                    "UPDATE user_state SET hunger_zero_days = ? WHERE user_id = ?",
                    (zero_days, user_id)
                )
                
                user = self.bot.get_user(user_id)
                if user:
                    msg = f"⚠️ **굶주림 {zero_days}일차**\n"
                    if hp_damage > 0:
                        msg += f"체력 -{hp_damage}\n"
                    if sanity_damage > 0:
                        msg += f"정신력 -{sanity_damage}\n"
                    msg += "빨리 식사를 하세요!"
                    
                    try:
                        await user.send(msg)
                    except:
                        pass
                
                await self.check_hp_zero(user_id)
        except Exception as e:
            logger.error(f"Error in check_hunger_penalties: {e}")

    @check_hunger_penalties.before_loop
    async def before_check_hunger_penalties(self):
        await self.bot.wait_until_ready()

    async def check_hp_zero(self, user_id):
        """체력 0 체크 및 실신 처리"""
        try:
            state = self.db.fetch_one(
                "SELECT current_hp FROM user_state WHERE user_id = ?",
                (user_id,)
            )
            
            if state and state[0] <= 0:
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
                    self.db.execute_query(
                        "UPDATE user_state SET current_hp = 1 WHERE user_id = ?",
                        (user_id,)
                    )
                    
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            await user.send(
                                f"💪 **의지로 버텼습니다!**\n"
                                f"쓰러질 뻔했지만 의지력으로 견뎌냈습니다. (체력 1 유지)"
                            )
                        except:
                            pass
                else:
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            await user.send(
                                f"💀 **실신했습니다!**\n"
                                f"체력이 바닥나 의식을 잃었습니다. 동료의 도움이 필요합니다."
                            )
                        except:
                            pass
        except Exception as e:
            logger.error(f"Error in check_hp_zero: {e}")

    async def check_madness_recovery(self, user_id):
        """광기 회복 조건 체크"""
        try:
            stats = self.sheets.get_user_stats(discord_id=str(user_id))
            
            if not stats:
                return
            
            threshold = 50 + (stats['intelligence'] * 0.3)
            
            user_state = self.db.fetch_one(
                "SELECT current_sanity FROM user_state WHERE user_id = ?",
                (user_id,)
            )
            
            current_sanity = user_state[0] if user_state else 0
            
            if current_sanity >= threshold:
                madness_list = self.db.fetch_all(
                    "SELECT id, madness_id, madness_name FROM user_madness WHERE user_id = ?",
                    (user_id,)
                )
                
                for madness_id_pk, madness_id, madness_name in madness_list:
                    madness_data = self.sheets.get_madness_data(madness_id)
                    if not madness_data:
                        continue
                    
                    difficulty = madness_data.get('recovery_difficulty', 0)
                    dice = GameLogic.roll_dice()
                    
                    if dice >= (100 - difficulty):
                        self.db.execute_query(
                            "DELETE FROM user_madness WHERE id = ?",
                            (madness_id_pk,)
                        )
                        
                        user = self.bot.get_user(user_id)
                        if user:
                            try:
                                await user.send(
                                    f"🌟 **광기 회복!**\n"
                                    f"'{madness_name}' 광기에서 벗어났습니다!"
                                )
                            except:
                                pass
        except Exception as e:
            logger.error(f"Error in check_madness_recovery: {e}")

    async def trigger_madness_check(self, user_id):
        """정신력이 0에 도달했을 때 자동 호출되는 광기 판정"""
        stats = self.sheets.get_user_stats(discord_id=str(user_id))
        if not stats:
            return

        intelligence = stats['intelligence']
        target_value = 10 - (intelligence - 40) * 0.6
        dice_roll = GameLogic.roll_dice()
        
        user = self.bot.get_user(user_id)
        if not user:
            try:
                user = await self.bot.fetch_user(user_id)
            except:
                pass
            
        if dice_roll <= target_value:
            self.db.execute_query("UPDATE user_state SET current_sanity = 1 WHERE user_id = ?", (user_id,))
            if user:
                try:
                    await user.send(f"🧠 **광기 저항 성공!** (주사위: {dice_roll} / 목표: {int(target_value)})\n논리로 광기를 버텨냈습니다. 정신력이 1이 됩니다.")
                except:
                    pass
        else:
            await self.acquire_random_madness(user_id)
            if user:
                try:
                    await user.send(f"😱 **광기 저항 실패...** (주사위: {dice_roll} / 목표: {int(target_value)})\n광기에 잠식됩니다.")
                except:
                    pass

    async def acquire_random_madness(self, user_id, context='default'):
        """랜덤 광기 획득"""
        import random
        
        all_madness = self.sheets.get_madness_data()
        if not all_madness:
            logger.error("No madness data found.")
            return

        owned_madness = self.db.fetch_all("SELECT madness_id FROM user_madness WHERE user_id = ?", (user_id,))
        owned_ids = [m[0] for m in owned_madness]
        
        available_madness = [m for m in all_madness if m['madness_id'] not in owned_ids]
        
        if not available_madness:
            return
            
        selected = random.choice(available_madness)
        
        self.db.execute_query(
            "INSERT INTO user_madness (user_id, madness_id, madness_name) VALUES (?, ?, ?)",
            (user_id, selected['madness_id'], selected['name'])
        )
        
        user = self.bot.get_user(user_id)
        if not user:
            try:
                user = await self.bot.fetch_user(user_id)
            except:
                pass
            
        if user:
            try:
                await user.send(
                    f"🎭 **새로운 광기 획득: {selected['name']}**\n"
                    f"{selected['description']}\n"
                    f"효과: {selected['effect_type']} {selected['effect_value']}"
                )
            except:
                pass

    @app_commands.command(name="허기확인", description="현재 허기 상태를 확인합니다.")
    async def check_hunger(self, interaction: discord.Interaction):
        state = await self.get_user_state(interaction.user.id)
        stats = self.sheets.get_user_stats(discord_id=str(interaction.user.id))
        willpower = stats['willpower'] if stats else 50
        
        decay = 10 + (willpower * 0.04)
        days_left = state['hunger'] / decay if decay > 0 else 999
        
        embed = discord.Embed(title="🍞 허기 상태", color=0xe67e22)
        embed.add_field(name="현재 허기", value=f"{int(state['hunger'])}/50", inline=True)
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
        inventory_item = self.db.fetch_one(
            "SELECT count FROM user_inventory WHERE user_id = ? AND item_name = ?",
            (interaction.user.id, item_name)
        )
        
        if not inventory_item or inventory_item[0] < 1:
            await interaction.response.send_message("❌ 해당 아이템을 가지고 있지 않습니다.", ephemeral=True)
            return

        item_data = self.sheets.get_item_data(item_name)
        
        if not item_data:
            recovery = 0
            if "빵" in item_name or "건빵" in item_name:
                recovery = 15
            elif "통조림" in item_name:
                recovery = 30
            else:
                await interaction.response.send_message("❌ 알 수 없는 아이템입니다.", ephemeral=True)
                return
        else:
            if item_data['type'] != '음식':
                await interaction.response.send_message("❌ 음식이 아닙니다.", ephemeral=True)
                return
            recovery = item_data['hunger_recovery']

        state = await self.get_user_state(interaction.user.id)
        MAX_HUNGER = 50
        
        if state['hunger'] >= MAX_HUNGER:
            await interaction.response.send_message("❌ 배가 부릅니다.", ephemeral=True)
            return
            
        new_hunger = min(MAX_HUNGER, state['hunger'] + recovery)
        
        # ✅ 허기 업데이트 + hunger_zero_days 리셋
        self.db.execute_query(
            """UPDATE user_state 
               SET current_hunger = ?, hunger_zero_days = 0 
               WHERE user_id = ?""",
            (new_hunger, interaction.user.id)
        )
        
        # ✅ 아이템 감소
        self.db.execute_query(
            """UPDATE user_inventory 
               SET count = count - 1 
               WHERE user_id = ? AND item_name = ?""",
            (interaction.user.id, item_name)
        )
        
        # count가 0이 되면 삭제
        self.db.execute_query(
            "DELETE FROM user_inventory WHERE user_id = ? AND count <= 0",
            (interaction.user.id,)
        )
        
        await interaction.response.send_message(
            f"🍞 {item_name}을(를) 먹었습니다. (허기 {int(state['hunger'])} -> {int(new_hunger)})"
        )

    @app_commands.command(name="휴식", description="휴식을 취해 정신력을 회복합니다. (하루 1회)")
    async def rest(self, interaction: discord.Interaction):
        state = await self.get_user_state(interaction.user.id)
        
        if state['last_sanity_recovery']:
            last_date = datetime.datetime.strptime(state['last_sanity_recovery'], "%Y-%m-%d %H:%M:%S").date()
            if last_date == datetime.date.today():
                await interaction.response.send_message("❌ 이미 오늘 휴식을 취했습니다.", ephemeral=True)
                return

        stats = self.sheets.get_user_stats(discord_id=str(interaction.user.id))
        if not stats:
            await interaction.response.send_message("❌ 스탯 정보를 불러올 수 없습니다.", ephemeral=True)
            return

        threshold = 30 + (stats['intelligence'] * 0.2)
        if state['hunger'] < threshold:
            await interaction.response.send_message(f"❌ 배가 너무 고파 휴식을 취할 수 없습니다. (필요 허기: {int(threshold)})", ephemeral=True)
            return

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