import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import logging
import random
import re
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
        
        # 태스크 시작
        self.daily_hunger_decay.start()
        self.daily_sanity_recovery.start()
        self.daily_madness_recovery_check.start()
        self.check_hunger_penalties.start()

    def cog_unload(self):
        self.daily_hunger_decay.cancel()
        self.daily_sanity_recovery.cancel()
        self.daily_madness_recovery_check.cancel()
        self.check_hunger_penalties.cancel()

    async def get_user_state(self, user_id):
        """
        DB에서 유저의 현재 상태(Current)를 가져오고,
        Sheets에서 유저의 최대 스탯(Max)을 가져와 병합하여 반환합니다.
        """
        # 1. DB에서 현재 상태 조회
        state = self.db.fetch_one("SELECT * FROM user_state WHERE user_id = ?", (user_id,))
        
        # 2. Sheets에서 최대 스탯 조회
        # user_id로 닉네임을 찾거나, DB에 저장된 닉네임이 있다면 그것을 사용해야 함.
        # 하지만 여기선 user_id로 조회 시도.
        sheet_stats = self.sheets.get_user_stats(discord_id=str(user_id))
        
        # 기본값 설정 (시트 데이터가 없을 경우)
        max_hp = 100
        max_sanity = 80
        # "초기 스탯 합이 180이어야 한다"는 규칙에 따라 기본값 설정 (예: 100+80=180)
        
        if sheet_stats:
            max_hp = sheet_stats.get('hp', 100)
            max_sanity = sheet_stats.get('sanity', 80)
            
            # 합계 180 검증 (경고만 로그)
            if max_hp + max_sanity != 180:
                logger.warning(f"User {user_id} stats sum is {max_hp + max_sanity}, expected 180.")

        if not state:
            # 초기 데이터 생성
            # 초기값은 Max 값으로 설정
            self.db.execute_query(
                "INSERT INTO user_state (user_id, current_hp, current_sanity, current_hunger) VALUES (?, ?, ?, ?)", 
                (user_id, max_hp, max_sanity, 50) # 허기 초기값 50 (최대치)
            )
            state = self.db.fetch_one("SELECT * FROM user_state WHERE user_id = ?", (user_id,))
        
        # Tuple to Dict (DB 스키마에 따라 인덱스 확인 필요)
        # user_state: user_id, current_hp, current_sanity, current_hunger, infection_level, last_hunger_update, last_sanity_recovery
        return {
            "user_id": state[0],
            "hp": state[1],
            "sanity": state[2],
            "hunger": state[3],
            "infection": state[4],
            "last_hunger_update": state[5],
            "max_hp": max_hp,
            "max_sanity": max_sanity,
            "max_hunger": 50 # 허기 최대치는 50으로 고정
        }

    async def update_nickname(self, user_id, hp, sanity):
        """유저 닉네임의 HP/Sanity 수치를 업데이트합니다."""
        try:
            guild = self.bot.guilds[0] # 첫 번째 길드 사용
            member = guild.get_member(user_id)
            if not member:
                return

            current_nick = member.display_name
            
            # 닉네임 파싱
            # SheetsManager의 parse_nickname을 사용하거나 직접 파싱
            # 여기서는 이름 부분만 추출하여 재구성
            name_part = self.sheets.parse_nickname(current_nick)
            
            # 새 닉네임 생성 (이름/HP/Sanity)
            new_nick = f"{name_part}/{int(hp)}/{int(sanity)}"
            
            if current_nick != new_nick:
                await member.edit(nick=new_nick)
                logger.info(f"Updated nickname for {member.name}: {new_nick}")
                
        except Exception as e:
            logger.error(f"Failed to update nickname for {user_id}: {e}")

    async def update_user_stat(self, user_id, stat_type, change):
        """
        유저 스탯을 업데이트하고 닉네임 및 DB에 반영합니다.
        Max 값을 초과하지 않도록 제한합니다.
        """
        state = await self.get_user_state(user_id)
        current_val = state[stat_type] # hp, sanity, hunger
        
        max_val = 0
        if stat_type == 'hp': max_val = state['max_hp']
        elif stat_type == 'sanity': max_val = state['max_sanity']
        elif stat_type == 'hunger': max_val = state['max_hunger']
        
        # 새 값 계산
        new_val = current_val + change
        
        # 한계치 적용 (0 ~ Max)
        new_val = max(0, min(max_val, new_val))
            
        # DB 업데이트
        self.db.execute_query(
            f"UPDATE user_state SET current_{stat_type} = ? WHERE user_id = ?",
            (new_val, user_id)
        )
        
        # 닉네임 업데이트 (HP나 Sanity 변경 시)
        if stat_type in ['hp', 'sanity']:
            hp = new_val if stat_type == 'hp' else state['hp']
            sanity = new_val if stat_type == 'sanity' else state['sanity']
            await self.update_nickname(user_id, hp, sanity)
            
        return new_val

    # --- Periodic Tasks ---

    @tasks.loop(hours=24)
    async def daily_hunger_decay(self):
        """
        매일 허기 감소 (Daily Hunger Decay)
        
        작동 원리:
        1. 모든 유저의 목록을 가져옵니다.
        2. 각 유저의 '의지(Willpower)' 스탯을 기반으로 허기 소모량을 계산합니다.
           - 공식: 소모량 = 10 + (의지 * 0.04)
        3. 현재 허기에서 소모량을 차감합니다.
        4. 변경된 값을 DB와 닉네임에 반영합니다.
        """
        try:
            # 모든 유저 ID 조회
            users = self.db.fetch_all("SELECT user_id FROM user_state")
            
            for (user_id,) in users:
                # 유저 스탯 조회 (Sheets)
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                if not stats: continue
                
                # 소모량 계산
                willpower = stats.get('willpower', 0)
                decay = 10 + (willpower * 0.04)
                
                # 허기 감소 적용 (음수 허용 안 함, 0까지만)
                # update_user_stat 내부에서 0 미만 방지 로직이 있음
                await self.update_user_stat(user_id, 'hunger', -decay)
                
            logger.info("Daily hunger decay executed for all users.")
            
        except Exception as e:
            logger.error(f"Error in daily_hunger_decay: {e}")

    @tasks.loop(hours=24)
    async def daily_sanity_recovery(self):
        """
        매일 정신력 회복 (Daily Sanity Recovery)
        
        작동 원리:
        1. 모든 유저를 순회하며 정신력 회복 조건을 확인합니다.
        2. 조건: 현재 허기가 '회복 임계치' 이상이어야 함.
           - 임계치 공식: 30 + (지성 * 0.2)
        3. 조건을 만족하면 정신력을 회복합니다.
           - 회복량 공식: 5 (기본 자연 회복량, 기획에 따라 조정 가능)
        4. 조건을 만족하지 못하면(배고픔), 회복하지 않습니다.
        """
        try:
            users = self.db.fetch_all("SELECT user_id, current_hunger FROM user_state")
            
            for user_id, current_hunger in users:
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                if not stats: continue
                
                intelligence = stats.get('intelligence', 0)
                
                # 회복 임계치 계산
                threshold = 30 + (intelligence * 0.2)
                
                if current_hunger >= threshold:
                    # 조건 만족 시 정신력 회복 (예: +5)
                    await self.update_user_stat(user_id, 'sanity', 5)
                else:
                    # 조건 불만족 (로그만 남김)
                    pass
                    
            logger.info("Daily sanity recovery check executed.")
            
        except Exception as e:
            logger.error(f"Error in daily_sanity_recovery: {e}")

    @tasks.loop(hours=24)
    async def daily_madness_recovery_check(self):
        """
        매일 광기 회복 체크 (Daily Madness Recovery Check)
        
        작동 원리:
        1. 광기를 보유한 유저들을 조회합니다.
        2. 각 광기의 '회복 난이도'와 유저의 '의지'를 비교하여 회복 여부를 판정합니다.
        3. 판정 성공 시 해당 광기를 제거합니다.
        """
        try:
            # 광기 보유 유저 조회
            madness_entries = self.db.fetch_all("SELECT id, user_id, madness_id, madness_name FROM user_madness")
            
            # 광기 데이터(난이도 등) 로드
            madness_data_list = self.sheets.get_madness_data()
            madness_info = {m['madness_id']: m for m in madness_data_list}
            
            for entry_id, user_id, madness_id, madness_name in madness_entries:
                if madness_id not in madness_info: continue
                
                info = madness_info[madness_id]
                difficulty = info.get('recovery_difficulty', '보통') # 쉬움, 보통, 어려움, 불가능 등
                
                # 난이도별 목표치 설정 (예시)
                target = 50
                if difficulty == '쉬움': target = 30
                elif difficulty == '어려움': target = 70
                elif difficulty == '불가능': continue
                
                # 유저 의지 스탯 조회
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                if not stats: continue
                willpower = stats.get('willpower', 0)
                
                # 판정 (1d100 + 의지 > 목표)
                dice = GameLogic.roll_dice()
                if dice + willpower >= target:
                    # 회복 성공: DB에서 제거
                    self.db.execute_query("DELETE FROM user_madness WHERE id = ?", (entry_id,))
                    
                    # 유저에게 알림
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            await user.send(f"✨ **광기 회복!**\n안정을 되찾아 '{madness_name}' 증세가 사라졌습니다.")
                        except: pass
                        
            logger.info("Daily madness recovery check executed.")
            
        except Exception as e:
            logger.error(f"Error in daily_madness_recovery_check: {e}")

    @tasks.loop(minutes=10)
    async def check_hunger_penalties(self):
        """
        허기 0일 때 페널티 적용 (Hunger Penalty Check)
        
        작동 원리:
        1. 10분마다 실행됩니다.
        2. 현재 허기가 0인 유저를 찾습니다.
        3. 해당 유저의 체력을 감소시킵니다. (예: -1 HP)
        4. 유저에게 경고 메시지를 보냅니다 (너무 자주는 아니게, 쿨타임 적용 가능).
        """
        try:
            # 허기가 0인 유저 조회
            starving_users = self.db.fetch_all("SELECT user_id, current_hp FROM user_state WHERE current_hunger <= 0")
            
            for user_id, current_hp in starving_users:
                if current_hp <= 0: continue # 이미 행동불능이면 스킵
                
                # 체력 감소 (-1)
                new_hp = await self.update_user_stat(user_id, 'hp', -1)
                
                # 사망(행동불능) 체크
                if new_hp <= 0:
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            await user.send("💀 **아사 직전...**\n배가 너무 고파 쓰러졌습니다. 누군가의 도움이 필요합니다.")
                        except: pass
                else:
                    # 경고 메시지 (확률적으로 또는 쿨타임 두어 발송)
                    # 여기서는 10% 확률로 경고
                    if random.random() < 0.1:
                        user = self.bot.get_user(user_id)
                        if user:
                            try:
                                await user.send("⚠️ **극심한 배고픔**\n배가 너무 고파 체력이 깎이고 있습니다. 무언가를 먹어야 합니다!")
                            except: pass
                            
        except Exception as e:
            logger.error(f"Error in check_hunger_penalties: {e}")

async def setup(bot):
    await bot.add_cog(Survival(bot))