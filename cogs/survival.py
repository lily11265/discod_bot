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
        self.db = self.bot.db_manager
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
        # 1. DB에서 현재 상태 조회 (Async)
        state = await self.db.fetch_one("SELECT * FROM user_state WHERE user_id = ?", (user_id,))
        
        # 2. Sheets에서 최대 스탯 조회 (Async)
        # user_id로 닉네임을 찾거나, DB에 저장된 닉네임이 있다면 그것을 사용해야 함.
        # 하지만 여기선 user_id로 조회 시도.
        sheet_stats = await self.sheets.get_user_stats_async(discord_id=str(user_id))
        
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
            # 초기 데이터 생성 (Async)
            # 초기값은 Max 값으로 설정
            await self.db.execute_query(
                "INSERT INTO user_state (user_id, current_hp, current_sanity, current_hunger) VALUES (?, ?, ?, ?)", 
                (user_id, max_hp, max_sanity, 50) # 허기 초기값 50 (최대치)
            )
            state = await self.db.fetch_one("SELECT * FROM user_state WHERE user_id = ?", (user_id,))
        
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
            
        # DB 업데이트 (Async)
        await self.db.execute_query(
            f"UPDATE user_state SET current_{stat_type} = ? WHERE user_id = ?",
            (new_val, user_id)
        )
        
        # 닉네임 업데이트 (HP나 Sanity 변경 시)
        if stat_type in ['hp', 'sanity']:
            hp = new_val if stat_type == 'hp' else state['hp']
            sanity = new_val if stat_type == 'sanity' else state['sanity']
            await self.update_nickname(user_id, hp, sanity)
            
        return new_val

    async def check_hp_zero(self, user_id):
        """체력이 0이 되었는지 확인하고 처리"""
        state = await self.db.fetch_one("SELECT current_hp FROM user_state WHERE user_id = ?", (user_id,))
        if state and state[0] <= 0:
            user = self.bot.get_user(user_id)
            if user:
                try:
                    await user.send("💀 **행동불능**\n체력이 0이 되어 쓰러졌습니다. 누군가의 도움이 필요합니다.")
                except: pass
            logger.info(f"User {user_id} is incapacitated (HP <= 0).")

    async def trigger_madness_check(self, user_id):
        """정신력이 낮아졌을 때 광기 발병 체크"""
        # 1. 유저 정보 조회
        stats = await self.sheets.get_user_stats_async(discord_id=str(user_id))
        if not stats: return

        intelligence = stats.get('intelligence', 0)
        
        # 2. 저항 판정 (GameLogic 위임)
        # 성공(True)하면 광기 면역, 실패(False)하면 광기 획득
        if GameLogic.check_madness_resistance(intelligence):
            return

        # 3. 광기 획득
        # 광기 데이터 가져오기
        madness_data = await self.sheets.get_madness_data_async()
        if not madness_data: return
        
        # 랜덤 광기 선택
        madness = random.choice(madness_data)
        
        # DB 저장
        await self.db.execute_query(
            "INSERT INTO user_madness (user_id, madness_id, madness_name) VALUES (?, ?, ?)",
            (user_id, madness['id'], madness['name'])
        )
        
        # 알림
        user = self.bot.get_user(user_id)
        if user:
            try:
                await user.send(
                    f"😵 **광기 발병!**\n"
                    f"정신적 충격을 이기지 못했습니다.\n"
                    f"획득한 광기: **{madness['name']}**\n"
                    f"_{madness['description']}_"
                )
            except: pass
        
        logger.info(f"User {user_id} acquired madness: {madness['name']}")

    # --- Periodic Tasks ---

    @tasks.loop(time=datetime.time(0, 0, 0))
    async def daily_hunger_decay(self):
        """
        매일 허기 감소 (Daily Hunger Decay)
        
        작동 원리:
        1. 모든 유저의 목록을 가져옵니다.
        2. 각 유저의 '의지(Willpower)' 스탯을 기반으로 허기 소모량을 계산합니다.
           - 공식: 소모량 = 10 + (의지 * 0.1)
        3. 현재 허기에서 소모량을 차감합니다.
        4. 변경된 값을 DB와 닉네임에 반영합니다.
        """
        try:
            # 모든 유저 ID 조회 (Async)
            users = await self.db.fetch_all("SELECT user_id, hunger_zero_days FROM user_state")
            
            update_data = []
            zero_days_update = []
            
            for (user_id, zero_days) in users:
                # 유저 스탯 조회 (Sheets) (Async)
                stats = await self.sheets.get_user_stats_async(discord_id=str(user_id))
                if not stats: continue
                
                # 페널티 적용된 의지 계산
                willpower = stats.get('willpower', 0)
                # 허기 0 지속일수에 따른 페널티 적용
                effective_willpower = GameLogic.calculate_hunger_penalty(willpower, zero_days)
                
                # 소모량 계산 (페널티 적용된 의지 사용)
                decay = 10 + (effective_willpower * 0.1)
                
                # 배치 업데이트를 위한 데이터 수집
                # 쿼리: UPDATE user_state SET current_hunger = MAX(0, current_hunger - ?) WHERE user_id = ?
                update_data.append((decay, user_id))
                
            # 2. 일괄 업데이트 (Batch Update) (Async)
            if update_data:
                await self.db.executemany(
                    "UPDATE user_state SET current_hunger = MAX(0, current_hunger - ?) WHERE user_id = ?",
                    update_data
                )
                logger.info(f"Daily hunger decay executed for {len(update_data)} users.")
            
        except Exception as e:
            logger.error(f"Error in daily_hunger_decay: {e}")

    @tasks.loop(time=datetime.time(0, 0, 0))
    async def daily_sanity_recovery(self):
        """
        매일 정신력 회복 (Daily Sanity Recovery)
        
        작동 원리:
        1. 모든 유저를 순회하며 정신력 회복 조건을 확인합니다.
        2. 조건: 현재 허기가 '회복 임계치' 이상이어야 함.
           - 임계치 공식: 20 + (지성 * 0.2)
        3. 조건을 만족하면 정신력을 회복합니다.
           - 회복량 공식: 5 (기본 자연 회복량, 기획에 따라 조정 가능)
        4. 조건을 만족하지 못하면(배고픔), 회복하지 않습니다.
        """
        try:
            users = await self.db.fetch_all("SELECT user_id, current_hunger, hunger_zero_days FROM user_state")
            
            for user_id, current_hunger, zero_days in users:
                stats = await self.sheets.get_user_stats_async(discord_id=str(user_id))
                if not stats: continue
                
                intelligence = stats.get('intelligence', 0)
                # 페널티 적용된 지성 계산
                effective_intelligence = GameLogic.calculate_hunger_penalty(intelligence, zero_days)
                
                # 회복 임계치 계산 (페널티 적용된 지성 사용)
                threshold = 20 + (effective_intelligence * 0.2)
                
                if current_hunger >= threshold:
                    # 조건 만족 시 정신력 회복 (예: +5)
                    await self.update_user_stat(user_id, 'sanity', 5)
                else:
                    # 조건 불만족 (로그만 남김)
                    pass
                    
            logger.info("Daily sanity recovery check executed.")
            
        except Exception as e:
            logger.error(f"Error in daily_sanity_recovery: {e}")

    @tasks.loop(time=datetime.time(0, 0, 0))
    async def daily_madness_recovery_check(self):
        """
        매일 광기 회복 체크 (변경된 로직: 지성+의지 기반)
        공식: Target = 100 - (지성*0.4 + 의지*0.6)
        """
        try:
            # 광기 보유 유저 조회
            madness_entries = self.db.fetch_all("SELECT id, user_id, madness_id, madness_name FROM user_madness")
            
            # (기존의 madness_data_list 로딩 부분은 삭제하거나 유지해도 됨, 여기선 사용 안 함)
            
            for entry_id, user_id, madness_id, madness_name in madness_entries:
                # 유저 스탯 조회
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                if not stats: continue
                
                intelligence = stats.get('intelligence', 0)
                willpower = stats.get('willpower', 0)
                
                # ✅ 새로운 임계값 공식 적용
                # 기본값 100에서 (지성 비중 40% + 의지 비중 60%) 만큼 차감하여 난이도 하락시킴
                # 예: 지성50, 의지50 -> 100 - (20 + 30) = 목표 50
                target_threshold = 100 - (intelligence * 0.4 + willpower * 0.6)
                
                # 최소 5% 확률(95)은 보장, 최대 95% 확률(5)로 제한
                target_threshold = max(5, min(95, target_threshold))
                
                # 판정 (1d100 >= 목표치)
                dice = GameLogic.roll_dice()
                
                # 로그 출력 (디버깅용)
                logger.debug(f"Madness Recovery: User {user_id} | Stat({intelligence}/{willpower}) | Target {target_threshold} | Dice {dice}")

                if dice >= target_threshold:
                    # 회복 성공: DB에서 제거
                    self.db.execute_query("DELETE FROM user_madness WHERE id = ?", (entry_id,))
                    
                    # 유저에게 알림
                    user = self.bot.get_user(user_id)
                    if user:
                        try:
                            await user.send(
                                f"✨ **내면의 힘으로 광기 극복!**\n"
                                f"지성({intelligence})과 의지({willpower})가 당신을 붙잡아주었습니다.\n"
                                f"'{madness_name}' 증세가 사라졌습니다. (주사위 {dice} ≥ 목표 {int(target_threshold)})"
                            )
                        except: pass
                        
            logger.info("Daily madness recovery check executed (Stat-based).")
            
        except Exception as e:
            logger.error(f"Error in daily_madness_recovery_check: {e}")

    @tasks.loop(time=datetime.time(0, 0, 0))
    async def check_hunger_penalties(self):
        """
        허기 페널티 체크 (매일 실행)
        
        Case 1: 허기 > 0
          - 페널티 없음, 정상 활동 가능
          - hunger_zero_days = 0 으로 리셋 (recover 커맨드 등에서 이미 처리하지만 안전장치)
        
        Case 2: 허기 = 0 (0~2일차)
          - 모든 스탯 -5% (GameLogic에서 계산 시 적용)
          - 체력 -5 감소
          - 경고 메시지: "배가 고파 몸이 무겁습니다."
        
        Case 3: 허기 = 0 (3~6일차)
          - 모든 스탯 -10%
          - 체력 -10 감소
          - 정신력 -5 감소
          - 경고 메시지: "굶주림으로 몸이 쇠약해집니다."
        
        Case 4: 허기 = 0 (7일차 이상)
          - 캐릭터 행동불능 (HP 0 처리?)
          - 여기서는 HP를 0으로 만들고 메시지 전송
        """
        try:
            # 모든 유저 상태 조회
            users = await self.db.fetch_all("SELECT user_id, current_hunger, hunger_zero_days, current_hp FROM user_state")
            
            for user_id, hunger, zero_days, hp in users:
                if hunger > 0:
                    # Case 1: 허기 > 0 -> 카운트 리셋 (혹시 안된 경우)
                    if zero_days > 0:
                        await self.db.execute_query("UPDATE user_state SET hunger_zero_days = 0 WHERE user_id = ?", (user_id,))
                    continue
                
                # 허기 = 0 인 경우
                # 일수 증가
                new_zero_days = zero_days + 1
                await self.db.execute_query("UPDATE user_state SET hunger_zero_days = ? WHERE user_id = ?", (new_zero_days, user_id))
                
                user = self.bot.get_user(user_id)
                msg = None
                hp_loss = 0
                sp_loss = 0
                
                if new_zero_days >= 7:
                    # Case 4: 7일 이상 -> 행동불능
                    # HP를 0으로 만듦 (또는 매우 큰 데미지)
                    await self.update_user_stat(user_id, 'hp', -hp) # 현재 HP만큼 깎아서 0으로
                    msg = "💀 **아사**\n극심한 굶주림 끝에 의식을 잃고 쓰러졌습니다. (행동불능)"
                    
                elif new_zero_days >= 3:
                    # Case 3: 3~6일차
                    hp_loss = 10
                    sp_loss = 5
                    msg = "⚠️ **굶주림**\n굶주림으로 몸이 쇠약해집니다. (체력 -10, 정신력 -5)"
                    
                else:
                    # Case 2: 1~2일차 (0일차 포함 여부는 기획에 따라, 여기선 1일차부터 적용)
                    hp_loss = 5
                    msg = "⚠️ **배고픔**\n배가 고파 몸이 무겁습니다. (체력 -5)"
                
                # 감소 적용
                if hp_loss > 0:
                    await self.update_user_stat(user_id, 'hp', -hp_loss)
                if sp_loss > 0:
                    await self.update_user_stat(user_id, 'sanity', -sp_loss)
                    
                # 메시지 전송
                if user and msg:
                    try:
                        await user.send(msg)
                    except: pass
                            
            logger.info("Daily hunger penalty check executed.")
                            
        except Exception as e:
            logger.error(f"Error in check_hunger_penalties: {e}")

    @check_hunger_penalties.before_loop
    async def before_check_hunger_penalties(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Survival(bot))
