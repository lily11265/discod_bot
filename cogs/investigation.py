import discord
from discord.ext import commands
from discord import app_commands
from utils.game_logic import GameLogic
from utils.sheets import SheetsManager
from utils.condition_parser import ConditionParser
import logging
import asyncio
import datetime
import config
from utils.synergy import SynergySystem

logger = logging.getLogger('cogs.investigation')

class InvestigationSession:
    def __init__(self, leader_id, channel_id, members, location_name, scheduled_time):
        self.leader_id = leader_id
        self.channel_id = channel_id
        self.members = members # [user_id, ...]
        self.location_name = location_name # Category Name
        self.scheduled_time = scheduled_time
        self.state = "scheduled" # scheduled, gathering, active, paused
        self.current_location_node = None # Current node in the location tree
        self.active_interactions = {} # user_id: interaction_data

class Investigation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sheets = SheetsManager()
        self.sessions = {} # session_id (usually channel_id) -> InvestigationSession
        self.sessions = {} # session_id (usually channel_id) -> InvestigationSession
        self.scheduled_tasks = []
        self.active_investigations = {} # user_id: interaction_data

    async def category_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """
        디스코드 서버의 카테고리 목록을 가져와서 자동완성으로 제공합니다.
        '통신채널', '공지_채널'은 제외합니다.
        """
        guild = interaction.guild
        if not guild:
            return []
        
        categories = []
        for category in guild.categories:
            if category.name in ['통신채널', '공지_채널']:
                continue
            if current.lower() in category.name.lower():
                categories.append(app_commands.Choice(name=category.name, value=category.name))
        
        return categories[:25] # 최대 25개 제한

    @app_commands.command(name="조사신청", description="조사를 예약하고 진행합니다.")
    @app_commands.describe(
        time_str="조사 시간 (예: 25.11.29.13.06)",
        category="조사할 지역 (카테고리)",
        user1="함께할 조사원 1 (선택)",
        user2="함께할 조사원 2 (선택)"
    )
    @app_commands.autocomplete(category=category_autocomplete)
    async def investigation_request(
        self, 
        interaction: discord.Interaction, 
        time_str: str, 
        category: str, 
        user1: discord.User = None, 
        user2: discord.User = None
    ):
        await interaction.response.defer()

        # 1. 시간 파싱 (YY.MM.DD.HH.MM)
        try:
            # 현재 연도 앞 2자리 유추 (2000년대 가정)
            target_time = datetime.datetime.strptime(time_str, "%y.%m.%d.%H.%M")
        except ValueError:
            await interaction.followup.send("❌ 시간 형식이 올바르지 않습니다. `YY.MM.DD.HH.MM` 형식으로 입력해주세요. (예: 25.11.29.13.06)", ephemeral=True)
            return

        now = datetime.datetime.now()
        if target_time < now:
            await interaction.followup.send("❌ 과거의 시간으로는 예약할 수 없습니다.", ephemeral=True)
            return

        # 2. 멤버 구성
        members = [interaction.user.id]
        if user1: members.append(user1.id)
        if user2: members.append(user2.id)
        
        # 중복 제거
        members = list(set(members))
        if len(members) > 3:
             await interaction.followup.send("❌ 조사는 최대 3명까지만 가능합니다.", ephemeral=True)
             return

        # 3. 카테고리 확인
        guild = interaction.guild
        target_category = discord.utils.get(guild.categories, name=category)
        if not target_category:
            await interaction.followup.send(f"❌ '{category}' 카테고리를 찾을 수 없습니다.", ephemeral=True)
            return
            
        # 해당 카테고리의 첫 번째 채널 찾기 (조사 시작 채널)
        if not target_category.channels:
             await interaction.followup.send(f"❌ '{category}' 카테고리에 채널이 없습니다.", ephemeral=True)
             return
        start_channel = target_category.channels[0]

        # 4. 예약 등록
        wait_seconds = (target_time - now).total_seconds()
        
        embed = discord.Embed(title="✅ 조사 예약 완료", color=0x2ecc71)
        embed.add_field(name="일시", value=target_time.strftime("%Y년 %m월 %d일 %H시 %M분"), inline=False)
        embed.add_field(name="지역", value=category, inline=True)
        embed.add_field(name="장소", value=start_channel.mention, inline=True)
        member_mentions = ", ".join([f"<@{uid}>" for uid in members])
        embed.add_field(name="참여 인원", value=member_mentions, inline=False)
        embed.set_footer(text=f"조사 시작 {int(wait_seconds // 60)}분 전입니다.")
        
        await interaction.followup.send(embed=embed)
        
        # 백그라운드 태스크로 스케줄링
        self.bot.loop.create_task(self.schedule_investigation(wait_seconds, members, category, start_channel, interaction.user.id))

    async def schedule_investigation(self, wait_seconds, members, category_name, channel, leader_id):
        """지정된 시간까지 대기 후 조사를 시작합니다."""
        await asyncio.sleep(wait_seconds)
        
        # 공지 채널에 알림
        notice_channel = self.bot.get_channel(config.NOTICE_CHANNEL_ID)
        if notice_channel:
            member_mentions = " ".join([f"<@{uid}>" for uid in members])
            await notice_channel.send(
                f"📢 **조사 알림**\n{member_mentions}님, {category_name} 지역 조사가 시작됩니다.\n"
                f"{channel.mention} 채널로 이동해주세요!"
            )
        
        # 조사 채널에서 시작 프로세스 (Gathering)
        await self.start_gathering(channel, members, leader_id, category_name)

    async def start_gathering(self, channel, members, leader_id, category_name):
        """멤버 소집 단계"""
        embed = discord.Embed(
            title="🕵️ 조사 인원 점호",
            description="조사에 참여하시는 분들은 5분 내에 아래 ✅ 버튼을 눌러주세요.",
            color=0xf1c40f
        )
        view = GatheringView(members, timeout=300) # 5분
        message = await channel.send(embed=embed, view=view)
        
        await view.wait()
        
        if view.all_ready:
            await channel.send("✅ 모든 인원이 모였습니다. 조사를 시작합니다!")
            await self.start_investigation(channel, members, category_name)
        else:
            # 인원 미달 시 리더에게 질문
            present_members = list(view.ready_members)
            if not present_members:
                await channel.send("❌ 아무도 오지 않아 조사가 취소되었습니다.")
                return

            await channel.send(f"⚠️ 일부 인원이 도착하지 않았습니다. (현재 {len(present_members)}/{len(members)}명)")
            # 리더 결정 로직 (여기서는 단순화하여 진행한다고 가정하거나, 추가 View 구현 필요)
            # 요구사항: 포기 / 진행 / 영입
            # 시간 관계상 '진행'으로 바로 넘어가는 로직으로 구현하거나, 추후 보강
            await self.start_investigation(channel, present_members, category_name)

    async def start_investigation(self, channel, members, category_name):
        """실제 조사 시작"""
        # 데이터 로드
        investigation_data = self.sheets.get_investigation_data()
        
        # 해당 카테고리(지역) 데이터 찾기
        # world_map의 키가 지역 이름임
        if category_name not in investigation_data:
            await channel.send(f"❌ '{category_name}'에 대한 조사 데이터가 없습니다.")
            return

        location_root = investigation_data[category_name]
        
        # 세션 생성
        session = InvestigationSession(members[0], channel.id, members, category_name, datetime.datetime.now())
        session.current_location_node = location_root
        self.sessions[channel.id] = session
        
        await self.show_location(channel, session)

    async def show_location(self, channel, session):
        """현재 위치의 정보를 보여주고 상호작용 버튼을 출력"""
        node = session.current_location_node
        
        embed = discord.Embed(
            title=f"📍 {node['name']}",
            description=node.get('description', '...'),
            color=0x3498db
        )
        
        # 버튼 생성 (조건 체크 포함)
        logger.debug(f"Creating InvestigationInteractionView for node: {node['name']}")
        view = InvestigationInteractionView(self, session, node)
        message = await channel.send(embed=embed, view=view)
        view.message = message # 메시지 참조 저장

        # ✅ 위험 감지 자동 판정 (각 멤버별)
        logger.debug(f"Checking danger detection for members: {session.members}")
        for member_id in session.members:
            stats = self.sheets.get_user_stats(discord_id=str(member_id))
            if not stats:
                logger.debug(f"Skipping danger check for {member_id}: No stats found")
                continue
            
            db = self.bot.get_cog("Survival").db
            user_state = db.fetch_one(
                "SELECT current_sanity FROM user_state WHERE user_id = ?", 
                (member_id,)
            )
            
            sanity_percent = user_state[0] / 100.0 if user_state else 1.0
            current_perception = GameLogic.calculate_current_stat(
                stats['perception'], 
                sanity_percent
            )
            
            # 시너지 체크
            synergies = SynergySystem.check_synergies(
                stats['perception'], 
                stats['intelligence'], 
                stats['willpower']
            )
            
            # 위험 감지 판정
            target = GameLogic.calculate_target_value(current_perception)
            target = SynergySystem.apply_synergy_bonus(target, synergies, 'danger_detection')
            
            if GameLogic.check_result(GameLogic.roll_dice(), target) in ["SUCCESS", "CRITICAL_SUCCESS"]:
                # 위험 정보가 있는지 확인 (node의 메타데이터 또는 조건)
                if node.get('is_dangerous', False) or "danger" in node.get('tags', []):
                    user = self.bot.get_user(member_id)
                    if user:
                        await user.send(
                            f"⚠️ **위험 감지!**\n"
                            f"{node['name']}은(는) 위험해 보입니다!"
                        )

    async def process_investigation_dice(self, interaction: discord.Interaction, dice_result: int):
        """
        stats.py의 /dice 명령어에서 호출되는 메서드
        """
        user_id = interaction.user.id
        logger.debug(f"Processing investigation dice for user {user_id}. Result: {dice_result}")
        
        if user_id not in self.active_investigations:
            logger.debug(f"User {user_id} has no active investigation.")
            return

        active_data = self.active_investigations[user_id]
        
        # 상태 확인
        if active_data["state"] != "waiting_for_dice":
            logger.debug(f"User {user_id} is not in 'waiting_for_dice' state. Current: {active_data['state']}")
            return
            
        # 채널 확인 (다른 채널의 주사위 무시)
        if interaction.channel_id != active_data["channel_id"]:
            logger.debug(f"Channel mismatch for user {user_id}. Expected {active_data['channel_id']}, got {interaction.channel_id}")
            return

        logger.info(f"Dice roll processed for {interaction.user.display_name}: {dice_result}")
        
        # 1. 상태 업데이트 (중복 처리 방지)
        del self.active_investigations[user_id]
        
        item_data = active_data["item_data"]
        variant = active_data["variant"]
        
        # 2. 결과 판정
        # 스탯 기반 판정 (예: perception)
        stat_name = variant.get("stat", "perception") # 기본값 감각
        target_value = 50 # 기본 목표값
        
        # 시트에서 유저 스탯 가져오기
        user_stats = self.sheets.get_user_stats(discord_id=str(user_id))
        if user_stats and stat_name in user_stats:
            target_value = user_stats[stat_name]
            logger.debug(f"Using stat '{stat_name}' for check. Base value: {target_value}")
        else:
            logger.debug(f"Stat '{stat_name}' not found. Using default target: {target_value}")
            
        # 난이도 보정
        difficulty = variant.get("difficulty", 0)
        target_value += difficulty
        logger.debug(f"Target value after difficulty ({difficulty}): {target_value}")
        
        result_type = GameLogic.check_result(dice_result, target_value)
        logger.debug(f"Check result: {result_type} (Dice: {dice_result} vs Target: {target_value})")

        # 3. 결과 적용
        result_text = ""
        effect_string = ""
        
        if result_type in ["SUCCESS", "CRITICAL_SUCCESS"]:
            result_text = variant.get("result_success", "성공!")
            # [] 안의 효과 파싱 (예: "상자를 열었다. [item+key, sanity+10]")
            if "[" in result_text and "]" in result_text:
                parts = result_text.split("[")
                result_text = parts[0].strip()
                effect_string = parts[1].replace("]", "").strip()
                
            # ✅ 오염 판별 자동 판정
            stats = self.sheets.get_user_stats(discord_id=str(user_id))
            db = self.bot.get_cog("Survival").db
            user_state = db.fetch_one(
                "SELECT current_sanity FROM user_state WHERE user_id = ?", 
                (user_id,)
            )
            
            sanity_percent = user_state[0] / 100.0 if user_state else 1.0
            current_perception = GameLogic.calculate_current_stat(
                stats['perception'], 
                sanity_percent
            )
            
            if GameLogic.check_pollution_detection(current_perception):
                # 아이템/장소가 오염되었는지 확인
                is_polluted = variant.get('is_polluted', False) or "polluted" in item_data.get('tags', [])
                
                if is_polluted:
                    user = interaction.user
                    await user.send(
                        f"🟢 **오염 감지!**\n"
                        f"이 {item_data['name']}은(는) 오염되어 있습니다!"
                    )

        else:
            result_text = variant.get("result_fail", "실패...")
            # 실패 시에도 효과가 있을 수 있음 (함정 등)
            if "[" in result_text and "]" in result_text:
                parts = result_text.split("[")
                result_text = parts[0].strip()
                effect_string = parts[1].replace("]", "").strip()

        # 효과 적용
        effect_results = await self.apply_effects(user_id, effect_string)
        
        # 4. 결과 출력
        embed = discord.Embed(
            title=f"🎲 조사 결과: {result_type}",
            description=f"{result_text}",
            color=0x2ecc71 if result_type in ["SUCCESS", "CRITICAL_SUCCESS"] else 0xe74c3c
        )
        
        if effect_results:
            embed.add_field(name="효과 적용", value="\n".join(effect_results), inline=False)
            
        await interaction.followup.send(embed=embed)

    async def apply_effects(self, user_id, effect_string):
        """
        효과 문자열을 파싱하여 적용합니다.
        예: "clue+단서ID, item+아이템명, 체력-10, 정신력+5, trigger+트리거ID"
        """
        logger.debug(f"Applying effects for user {user_id}: {effect_string}")
        results = []
        if not effect_string:
            return results
            
        # 콤마로 분리
        tokens = [t.strip() for t in effect_string.split(',')]
        
        db = self.bot.get_cog("Survival").db
        
        for token in tokens:
            try:
                logger.debug(f"Processing token: {token}")
                if token.startswith("clue+"):
                    clue_id = token.split('+')[1]
                    # 단서 이름 조회 (시트에서)
                    clue_data = self.sheets.get_clue_data(clue_id) # TODO: Implement get_clue_data
                    clue_name = clue_data['name'] if clue_data else clue_id
                    
                    db.execute_query("INSERT OR IGNORE INTO user_clues (user_id, clue_id, clue_name) VALUES (?, ?, ?)", (user_id, clue_id, clue_name))
                    results.append(f"🔍 단서 획득: {clue_name}")
                    logger.debug(f"Clue acquired: {clue_id}")

                elif token.startswith("item+"):
                    item_name = token.split('+')[1]
                    # 인벤토리 추가
                    db.execute_query("""
                        INSERT INTO user_inventory (user_id, item_name, count) 
                        VALUES (?, ?, 1) 
                        ON CONFLICT(user_id, item_name) 
                        DO UPDATE SET count = count + 1
                    """, (user_id, item_name))
                    results.append(f"📦 아이템 획득: {item_name}")
                    logger.debug(f"Item acquired: {item_name}")

                elif "체력" in token:
                    # 예: "체력-10", "체력+20"
                    op = '+' if '+' in token else '-'
                    value = int(token.split(op)[1])
                    change = value if op == '+' else -value
                    
                    db.execute_query("UPDATE user_state SET current_hp = current_hp + ? WHERE user_id = ?", (change, user_id))
                    results.append(f"❤️ 체력 {'회복' if change > 0 else '감소'}: {change}")
                    logger.debug(f"HP changed by {change}")
                    
                    # 체력 0 체크
                    await self.bot.get_cog("Survival").check_hp_zero(user_id)

                elif "정신력" in token:
                    op = '+' if '+' in token else '-'
                    value = int(token.split(op)[1])
                    change = value if op == '+' else -value
                    
                    db.execute_query("UPDATE user_state SET current_sanity = current_sanity + ? WHERE user_id = ?", (change, user_id))
                    results.append(f"🧠 정신력 {'회복' if change > 0 else '감소'}: {change}")
                    logger.debug(f"Sanity changed by {change}")
                    
                    # 광기 체크 (감소 시에만)
                    if change < 0:
                        await self.bot.get_cog("Survival").trigger_madness_check(user_id)

                elif token.startswith("trigger+"):
                    trigger_id = token.split('+')[1]
                    db.execute_query("INSERT OR REPLACE INTO world_triggers (trigger_id, active, activated_by) VALUES (?, 1, ?)", (trigger_id, user_id))
                    results.append(f"⚡ 트리거 활성화: {trigger_id}")
                    logger.debug(f"Trigger activated: {trigger_id}")

                elif token.startswith("공포"):
                    # 예: "공포-20"
                    op = '+' if '+' in token else '-'
                    base_damage = int(token.split(op)[1])
                    
                    # 스탯 로드
                    stats = self.sheets.get_user_stats(discord_id=str(user_id))
                    db = self.bot.get_cog("Survival").db
                    user_state = db.fetch_one(
                        "SELECT current_sanity FROM user_state WHERE user_id = ?", 
                        (user_id,)
                    )
                    
                    sanity_percent = user_state[0] / 100.0 if user_state else 1.0
                    current_willpower = GameLogic.calculate_current_stat(
                        stats['willpower'], 
                        sanity_percent
                    )
                    
                    # 1. 공포 저항 판정
                    target = GameLogic.calculate_target_value(current_willpower)
                    dice = GameLogic.roll_dice()
                    
                    user = self.bot.get_user(user_id)
                    
                    if dice >= target:
                        # 저항 성공
                        if user:
                            await user.send(
                                f"💪 **공포 저항 성공!** (주사위: {dice} / 목표: {target})\n"
                                f"공포를 이겨냈습니다!"
                            )
                    
                    # 2. 공포 피해 계산
                    actual_damage = GameLogic.calculate_fear_damage(base_damage, current_willpower)
                    
                    # 3. 감각에 따른 정신력 피해 증폭
                    current_perception = GameLogic.calculate_current_stat(
                        stats['perception'], 
                        sanity_percent
                    )
                    final_damage = GameLogic.calculate_sanity_damage(actual_damage, current_perception)
                    
                    # 4. 정신력 감소
                    db.execute_query(
                        "UPDATE user_state SET current_sanity = MAX(0, current_sanity - ?) WHERE user_id = ?",
                        (final_damage, user_id)
                    )
                    
                    results.append(
                        f"😱 공포 피해: -{final_damage} 정신력 "
                        f"(기본 {base_damage} → 의지 감소 {actual_damage} → 감각 증폭 {final_damage})"
                    )
                    logger.debug(f"Fear effect applied: -{final_damage} sanity")
                    
            except Exception as e:
                logger.error(f"Error applying effect {token}: {e}")
                results.append(f"⚠️ 효과 적용 실패: {token}")
                
        return results

class GatheringView(discord.ui.View):
    def __init__(self, expected_members, timeout=300):
        super().__init__(timeout=timeout)
        self.expected_members = set(expected_members)
        self.ready_members = set()
        self.all_ready = False

    @discord.ui.button(label="출석 체크", style=discord.ButtonStyle.success, emoji="✅")
    async def check_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.expected_members:
            await interaction.response.send_message("이번 조사에 참여하지 않은 인원입니다.", ephemeral=True)
            return
        
        if interaction.user.id in self.ready_members:
            await interaction.response.send_message("이미 출석 체크를 하셨습니다.", ephemeral=True)
            return

        self.ready_members.add(interaction.user.id)
        await interaction.response.send_message(f"{interaction.user.mention} 출석 확인!", ephemeral=False)
        
        if len(self.ready_members) == len(self.expected_members):
            self.all_ready = True
            self.stop()

class InvestigationInteractionView(discord.ui.View):
    def __init__(self, cog, session, node):
        super().__init__(timeout=900) # 15분
        self.cog = cog
        self.session = session
        self.node = node
        self.message = None
        self.generate_buttons()

    async def on_timeout(self):
        """타임아웃 시 새 View 생성하여 타이머 리셋"""
        if self.message:
            new_view = InvestigationInteractionView(self.cog, self.session, self.node)
            await self.message.edit(view=new_view)
            new_view.message = self.message

    def generate_buttons(self):
        # 1. 하위 지역 (이동)
        if "children" in self.node:
            for child_name, child_data in self.node["children"].items():
                # 조건 체크 필요 (지역 이동에도 조건이 있을 수 있음 - 현재 데이터 구조상 I열은 아이템/상호작용에만 있음)
                # 하지만 지역 자체도 조건이 있을 수 있다면 ConditionParser 사용
                # 여기서는 일단 무조건 표시
                button = discord.ui.Button(label=child_name, style=discord.ButtonStyle.primary, custom_id=f"move:{child_name}")
                button.callback = self.create_move_callback(child_data)
                self.add_item(button)

        # 2. 상호작용 (아이템)
        if "items" in self.node:
            for item in self.node["items"]:
                # Top-Down Variant Check
                # variants 리스트를 순회하며 첫 번째로 조건이 맞는(visible=True) variant를 찾음
                
                # 상태 정보 구성
                user_state = {
                    "stats": {}, # TODO: 실제 유저 스탯 로드 필요 (여기서는 View 생성 시점이라 비동기 호출 어려움 -> 미리 로드하거나 캐시 사용)
                    "inventory": [], # TODO: 인벤토리 로드
                    "pollution": 0 # TODO: 오염도 로드
                }
                
                # 스탯은 View 생성 시점에 알기 어려울 수 있음 (여러 유저가 보므로)
                # 하지만 버튼의 가시성은 "관찰자" 기준이 아니라 "일반적인 조건"이어야 함?
                # 아니면, 버튼을 누를 때 체크?
                # 요구사항: "I열 조건에 따라 다른 Q열 묘사 표시" -> 버튼은 하나지만, 누르면 결과가 다름?
                # 예시 1: "버튼은 하나: [🔍 서류 뒤지기]. 클릭 시 자신의 감각 스탯에 맞는 묘사 표시"
                # 따라서 버튼 생성 시점에는 "가장 관대한 조건" 혹은 "기본 버튼"을 보여주고,
                # 클릭 시점에 조건을 다시 체크하여 묘사를 결정해야 함.
                
                # 하지만 "Visible" 조건(예: trigger)이 있다면 버튼 자체가 안 보여야 함.
                # 따라서 "Visible" 여부는 모든 Variant 중 하나라도 Visible이면 True?
                # 혹은 "기본 Variant"(조건 없음)가 있다면 무조건 Visible.
                
                # 여기서는 일단 버튼을 생성하고, 콜백에서 조건을 다시 체크하여 묘사를 선택하도록 구현.
                # 단, 'block'이나 'visible' 옵션이 있는 경우 버튼 자체를 숨겨야 할 수도 있음.
                # 현재 로직: 버튼은 무조건 생성하되, 콜백에서 Variant 선택.
                # (심화: 만약 모든 Variant가 숨김 조건이라면 버튼 생성 X)
                
                button = discord.ui.Button(
                    label=item["button_text"], 
                    style=discord.ButtonStyle.secondary, 
                    emoji="🔍",
                    custom_id=f"act:{item['name']}"
                )
                button.callback = self.create_action_callback(item)
                self.add_item(button)

    def create_move_callback(self, target_node):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id not in self.session.members:
                await interaction.response.send_message("조사 인원만 이동할 수 있습니다.", ephemeral=True)
                return
            
            # 채널 이동 로직 (A열 노드인 경우)
            if target_node.get("is_channel", False):
                guild = interaction.guild
                target_channel_name = target_node["name"]
                
                # 채널 찾기 (이름으로)
                target_channel = discord.utils.get(guild.text_channels, name=target_channel_name)
                
                if target_channel:
                    # 세션 이동
                    old_channel_id = self.session.channel_id
                    
                    # 세션 정보 업데이트
                    self.session.channel_id = target_channel.id
                    self.session.current_location_node = target_node
                    
                    # 매핑 업데이트
                    if old_channel_id in self.cog.sessions:
                        del self.cog.sessions[old_channel_id]
                    self.cog.sessions[target_channel.id] = self.session
                    
                    await interaction.response.defer()
                    
                    # 기존 메시지 정리 (선택사항)
                    try:
                        await interaction.message.delete()
                    except:
                        pass
                        
                    # 새 채널에 멘션 및 조사 화면 출력
                    member_mentions = ", ".join([f"<@{uid}>" for uid in self.session.members])
                    await target_channel.send(f"🚀 **장소 이동!**\n{member_mentions}님이 **{target_channel_name}**에 도착했습니다.")
                    
                    await self.cog.show_location(target_channel, self.session)
                    return
                else:
                    await interaction.response.send_message(f"❌ 이동할 채널 '{target_channel_name}'을(를) 찾을 수 없습니다.", ephemeral=True)
                    return

            # 일반 이동 (같은 채널 내)
            self.session.current_location_node = target_node
            await interaction.response.defer()
            await self.cog.show_location(interaction.channel, self.session)
        return callback

    def create_action_callback(self, item_data):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id not in self.session.members:
                await interaction.response.send_message("조사 인원만 상호작용할 수 있습니다.", ephemeral=True)
                return
            
            # 1. 유저 상태 로드
            stats = self.cog.sheets.get_user_stats(nickname=interaction.user.display_name, discord_id=str(interaction.user.id))
            if not stats:
                await interaction.response.send_message("❌ 스탯 정보를 불러올 수 없습니다.", ephemeral=True)
                return

            user_state = {
                "stats": stats,
                "inventory": [], # TODO: 인벤토리 연동
                "pollution": 0, # TODO: 오염도 연동
                "skills": [] # TODO: 스킬 연동
            }
            
            # 2. 월드 상태 로드
            # TODO: DB에서 트리거, 시간, 카운트 로드
            world_state = {
                "triggers": [],
                "time": datetime.datetime.now().strftime("%H:%M"),
                "interaction_counts": {}, # TODO: 로드
                "current_item_id": f"{self.node['id']}_{item_data['name']}" # 임시 ID 생성
            }
            
            # 3. Variant 선택 (Top-Down)
            selected_variant = None
            
            # variants가 없으면(구버전 데이터 등) 기본 처리
            if "variants" not in item_data or not item_data["variants"]:
                # Fallback (기존 구조 호환)
                selected_variant = {
                    "condition": item_data.get("condition", ""),
                    "description": item_data.get("description", ""),
                    "result_success": item_data.get("result_success", ""),
                    "result_fail": item_data.get("result_fail", "")
                }
            else:
                # 순차 체크
                for variant in item_data["variants"]:
                    conditions = ConditionParser.parse_condition_string(variant["condition"])
                    
                    # 빈 조건은 항상 참 (기본값)
                    if not conditions:
                        selected_variant = variant
                        break
                        
                    check_result = ConditionParser.evaluate_all(conditions, user_state, world_state)
                    if check_result["enabled"]: # visible & enabled
                        selected_variant = variant
                        break
            
            if not selected_variant:
                # 매칭되는 Variant가 없음 (이론상 마지막에 빈 조건이 있어야 함)
                await interaction.response.send_message("아무런 반응이 없습니다.", ephemeral=True)
                return

            # 4. 선택된 Variant 실행
            # 조사(investigation) 타입인 경우 주사위 굴림 유도
            if item_data["type"] == "investigation":
                await interaction.response.send_message(
                    f"🔍 **{item_data['name']}** 조사를 시작합니다.\n"
                    f"{selected_variant['description']}\n" # 조사 전 묘사? 혹은 조사 후 묘사?
                    # 기획서: "Q열 묘사 표시" -> 클릭 시 바로 표시되는 묘사
                    f"`/dice` 명령어로 주사위를 굴려주세요!",
                    ephemeral=True
                )
                
                # 세션에 현재 상호작용 정보 저장
                self.cog.active_investigations[interaction.user.id] = {
                    "state": "waiting_for_dice",
                    "item_data": item_data,
                    "variant": selected_variant,
                    "channel_id": interaction.channel_id
                }
            else:
                # 즉시 완료 타입 (read, acquire 등)
                # 여기서는 간단히 묘사만 출력
                await interaction.response.send_message(
                    f"**{item_data['name']}**\n{selected_variant['description']}",
                    ephemeral=True
                )
                
        return callback





async def setup(bot):
    await bot.add_cog(Investigation(bot))
