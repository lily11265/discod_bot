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
        """매일 허기 감소"""
        # 구현 필요: 모든 유저의 허기를 감소시키고 update_user_stat 호출
        pass

    @tasks.loop(hours=24)
    async def daily_sanity_recovery(self):
        """매일 정신력 회복 (조건부)"""
        pass

    @tasks.loop(hours=24)
    async def daily_madness_recovery_check(self):
        """매일 광기 회복 체크"""
        pass

    @tasks.loop(minutes=10)
    async def check_hunger_penalties(self):
        """허기 0일 때 페널티 적용"""
        pass

async def setup(bot):
    await bot.add_cog(Survival(bot))