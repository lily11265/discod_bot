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
import json

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
        self.reservations = [] # 예약된 조사 목록: {'leader_id': int, 'members': [], 'time': datetime, 'category': str, 'channel_id': int}
        self.active_investigations = {} # user_id: interaction_data

    async def category_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """카테고리 자동완성"""
        guild = interaction.guild
        if not guild:
            return []
        
        categories = []
        for category in guild.categories:
            if category.name in ['통신채널', '공지_채널']:
                continue
            if current.lower() in category.name.lower():
                categories.append(app_commands.Choice(name=category.name, value=category.name))
        
        return categories[:25]

    async def session_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """
        사용자가 속한 조사(예약/진행/일시정지) 목록을 자동완성으로 제공합니다.
        Format: "MM월DD일HH시MM분 [지역] 멤버이름..."
        """
        user_id = interaction.user.id
        choices = []

        # 1. 예약된 조사 (reservations)
        for i, res in enumerate(self.reservations):
            if user_id in res['members']:
                time_str = res['time'].strftime("%m월%d일%H시%M분")
                member_names = [self.bot.get_user(uid).display_name for uid in res['members'] if self.bot.get_user(uid)]
                label = f"[예약] {time_str} [{res['category']}] {', '.join(member_names)}"
                if current.lower() in label.lower():
                    # value는 식별을 위해 index와 type을 조합
                    choices.append(app_commands.Choice(name=label, value=f"res:{i}"))

        # 2. 진행 중 / 일시정지된 조사 (sessions)
        for ch_id, session in self.sessions.items():
            if user_id in session.members:
                state_str = "진행" if session.state == "active" else "정지"
                time_str = session.scheduled_time.strftime("%m월%d일%H시%M분")
                member_names = [self.bot.get_user(uid).display_name for uid in session.members if self.bot.get_user(uid)]
                label = f"[{state_str}] {time_str} [{session.location_name}] {', '.join(member_names)}"
                if current.lower() in label.lower():
                    choices.append(app_commands.Choice(name=label, value=f"sess:{ch_id}"))

        return choices[:25]

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

        # 1. 시간 파싱
        try:
            target_time = datetime.datetime.strptime(time_str, "%y.%m.%d.%H.%M")
        except ValueError:
            await interaction.followup.send("❌ 시간 형식이 올바르지 않습니다. `YY.MM.DD.HH.MM` 형식으로 입력해주세요.", ephemeral=True)
            return

        now = datetime.datetime.now()
        if target_time < now:
            await interaction.followup.send("❌ 과거의 시간으로는 예약할 수 없습니다.", ephemeral=True)
            return

        # 2. 멤버 구성
        members = [interaction.user.id]
        if user1: members.append(user1.id)
        if user2: members.append(user2.id)
        members = list(set(members)) # 중복 제거

        if len(members) > 3:
             await interaction.followup.send("❌ 조사는 최대 3명까지만 가능합니다.", ephemeral=True)
             return

        # 3. 카테고리 확인
        guild = interaction.guild
        target_category = discord.utils.get(guild.categories, name=category)
        if not target_category:
            await interaction.followup.send(f"❌ '{category}' 카테고리를 찾을 수 없습니다.", ephemeral=True)
            return
            
        if not target_category.channels:
             await interaction.followup.send(f"❌ '{category}' 카테고리에 채널이 없습니다.", ephemeral=True)
             return
        start_channel = target_category.channels[0]

        # 4. 예약 등록 (메모리 저장)
        reservation = {
            'leader_id': interaction.user.id,
            'members': members,
            'time': target_time,
            'category': category,
            'channel_id': start_channel.id
        }
        self.reservations.append(reservation)

        wait_seconds = (target_time - now).total_seconds()
        
        embed = discord.Embed(title="✅ 조사 예약 완료", color=0x2ecc71)
        embed.add_field(name="일시", value=target_time.strftime("%Y년 %m월 %d일 %H시 %M분"), inline=False)
        embed.add_field(name="지역", value=category, inline=True)
        embed.add_field(name="장소", value=start_channel.mention, inline=True)
        member_mentions = ", ".join([f"<@{uid}>" for uid in members])
        embed.add_field(name="참여 인원", value=member_mentions, inline=False)
        
        await interaction.followup.send(embed=embed)
        
        # 백그라운드 태스크
        self.bot.loop.create_task(self.schedule_investigation(wait_seconds, reservation))

    async def schedule_investigation(self, wait_seconds, reservation):
        """지정된 시간까지 대기 후 조사를 시작합니다."""
        try:
            await asyncio.sleep(wait_seconds)
            
            # 예약 목록에 여전히 존재하는지 확인 (취소되었을 수 있음)
            if reservation not in self.reservations:
                return

            # 예약 목록에서 제거하고 세션 시작
            if reservation in self.reservations:
                self.reservations.remove(reservation)

            channel = self.bot.get_channel(reservation['channel_id'])
            if not channel:
                logger.error(f"Channel {reservation['channel_id']} not found.")
                return

            # 공지 및 시작
            notice_channel = self.bot.get_channel(config.NOTICE_CHANNEL_ID)
            if notice_channel:
                member_mentions = " ".join([f"<@{uid}>" for uid in reservation['members']])
                await notice_channel.send(
                    f"📢 **조사 알림**\n{member_mentions}님, {reservation['category']} 지역 조사가 시작됩니다.\n"
                    f"{channel.mention} 채널로 이동해주세요!"
                )
            
            await self.start_gathering(channel, reservation['members'], reservation['leader_id'], reservation['category'])
            
        except Exception as e:
            logger.error(f"Error in scheduled investigation: {e}")

    @app_commands.command(name="조사종료", description="조사를 취소, 중단하거나 일시정지합니다.")
    @app_commands.describe(
        action="수행할 작업 (취소/일시중지/다시시작)",
        target="대상 조사 선택"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="취소/종료", value="cancel"),
        app_commands.Choice(name="일시중지", value="pause"),
        app_commands.Choice(name="다시시작", value="resume")
    ])
    @app_commands.autocomplete(target=session_autocomplete)
    async def end_investigation(self, interaction: discord.Interaction, action: str, target: str):
        """조사 관리 명령어"""
        await interaction.response.defer()

        # target 값 파싱 (res:index 또는 sess:channel_id)
        if ":" not in target:
            await interaction.followup.send("❌ 올바른 대상을 선택해주세요.", ephemeral=True)
            return
            
        type_, id_val = target.split(":")
        
        # 1. 취소/종료 (Cancel)
        if action == "cancel":
            if type_ == "res": # 예약 취소
                try:
                    idx = int(id_val)
                    if 0 <= idx < len(self.reservations):
                        res = self.reservations.pop(idx)
                        await interaction.followup.send(f"✅ 예약된 조사([{res['category']}])가 취소되었습니다.")
                    else:
                        await interaction.followup.send("❌ 해당 예약을 찾을 수 없습니다.", ephemeral=True)
                except ValueError:
                    await interaction.followup.send("❌ 잘못된 요청입니다.", ephemeral=True)
            
            elif type_ == "sess": # 진행 중 종료
                session_id = int(id_val)
                if session_id in self.sessions:
                    # 세션 종료 처리
                    del self.sessions[session_id]
                    await interaction.followup.send("✅ 진행 중인 조사가 종료되었습니다. 수고하셨습니다!")
                else:
                    await interaction.followup.send("❌ 진행 중인 세션을 찾을 수 없습니다.", ephemeral=True)

        # 2. 일시중지 (Pause)
        elif action == "pause":
            if type_ == "res":
                await interaction.followup.send("❌ 예약된 조사는 일시중지할 수 없습니다. 취소만 가능합니다.", ephemeral=True)
            elif type_ == "sess":
                session_id = int(id_val)
                if session_id in self.sessions:
                    session = self.sessions[session_id]
                    session.state = "paused"
                    # DB 저장 로직이 있다면 여기서 수행 (현재는 메모리 유지)
                    await interaction.followup.send(f"✅ [{session.location_name}] 조사가 일시중지되었습니다. '다시시작'으로 재개할 수 있습니다.")
                else:
                    await interaction.followup.send("❌ 세션을 찾을 수 없습니다.", ephemeral=True)

        # 3. 다시시작 (Resume)
        elif action == "resume":
            if type_ == "sess":
                session_id = int(id_val)
                if session_id in self.sessions:
                    session = self.sessions[session_id]
                    if session.state != "paused":
                        await interaction.followup.send("❌ 해당 조사는 이미 진행 중이거나 종료되었습니다.", ephemeral=True)
                        return
                    
                    session.state = "active"
                    channel = self.bot.get_channel(session.channel_id)
                    await interaction.followup.send("✅ 조사를 재개합니다!")
                    if channel:
                        await self.show_location(channel, session)
                else:
                    await interaction.followup.send("❌ 일시정지된 세션을 찾을 수 없습니다.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 예약된 조사는 '다시시작'할 수 없습니다.", ephemeral=True)

    async def start_gathering(self, channel, members, leader_id, category_name):
        """멤버 소집 단계"""
        embed = discord.Embed(
            title="🕵️ 조사 인원 점호",
            description="조사에 참여하시는 분들은 5분 내에 아래 ✅ 버튼을 눌러주세요.",
            color=0xf1c40f
        )
        view = GatheringView(members, timeout=300)
        await channel.send(embed=embed, view=view)
        
        await view.wait()
        
        if view.all_ready:
            await channel.send("✅ 모든 인원이 모였습니다. 조사를 시작합니다!")
            await self.start_investigation(channel, members, category_name)
        else:
            present_members = list(view.ready_members)
            if not present_members:
                await channel.send("❌ 아무도 오지 않아 조사가 취소되었습니다.")
                return
            await channel.send(f"⚠️ 일부 인원이 도착하지 않았습니다. (현재 {len(present_members)}/{len(members)}명)\n조사를 진행합니다.")
            await self.start_investigation(channel, present_members, category_name)

    async def start_investigation(self, channel, members, category_name):
        """실제 조사 시작"""
        investigation_data = self.sheets.fetch_investigation_data()
        
        if category_name not in investigation_data:
            await channel.send(f"❌ '{category_name}'에 대한 조사 데이터가 없습니다.")
            return

        location_root = investigation_data[category_name]
        
        session = InvestigationSession(members[0], channel.id, members, category_name, datetime.datetime.now())
        session.current_location_node = location_root
        session.state = "active"
        self.sessions[channel.id] = session
        
        await self.show_location(channel, session)

    async def show_location(self, channel, session):
        """현재 위치 정보 및 상호작용 출력"""
        node = session.current_location_node
        
        embed = discord.Embed(
            title=f"📍 {node['name']}",
            description=node.get('description', '...'),
            color=0x3498db
        )
        
        view = InvestigationInteractionView(self, session, node)
        message = await channel.send(embed=embed, view=view)
        view.message = message

        # 위험 감지 (기존 코드 유지)
        for member_id in session.members:
            stats = self.sheets.get_user_stats(discord_id=str(member_id))
            if not stats: continue
            
            db = self.bot.get_cog("Survival").db
            user_state = db.fetch_one("SELECT current_sanity FROM user_state WHERE user_id = ?", (member_id,))
            sanity_percent = user_state[0] / 100.0 if user_state else 1.0
            
            current_perception = GameLogic.calculate_current_stat(stats['perception'], sanity_percent)
            target = GameLogic.calculate_target_value(current_perception)            
            
            if GameLogic.check_result(GameLogic.roll_dice(), target) in ["SUCCESS", "CRITICAL_SUCCESS"]:
                if node.get('is_dangerous', False) or "danger" in node.get('tags', []):
                    user = self.bot.get_user(member_id)
                    if user:
                        try: await user.send(f"⚠️ **위험 감지!**\n{node['name']}은(는) 위험해 보입니다!")
                        except: pass

    async def process_investigation_dice(self, interaction: discord.Interaction, dice_result: int):
        """/dice 명령어로 호출되는 메서드 (명세서 결과 반영)"""
        user_id = interaction.user.id
        
        if user_id not in self.active_investigations:
            return

        active_data = self.active_investigations[user_id]
        if active_data["state"] != "waiting_for_dice":
            return
        if interaction.channel_id != active_data["channel_id"]:
            return

        # 데이터 정리
        del self.active_investigations[user_id]
        item_data = active_data["item_data"]
        variant = active_data["variant"]
        
        # 1. 판정 스탯 결정
        # 조건(I열)에 "stat:감각:40" 등이 있었다면 그 스탯 사용, 없으면 기본값(예: 감각)
        stat_name = "감각" 
        base_target = 50
        
        # 조건 파싱해서 스탯 정보 찾기
        if "condition" in variant and variant["condition"]:
            conds = ConditionParser.parse_condition_string(variant["condition"])
            for c in conds:
                if c['type'] == 'stat':
                    # stat:지성:40 -> 지성
                    parts = c['value'].split(':') # value는 "지성:40" 형태일 수 있음 (parser 구현에 따라 다름)
                    # ConditionParser는 type='stat', value='지성:40' 으로 파싱함
                    if ':' in c['value']:
                        stat_name = c['value'].split(':')[0]
                    break

        # 스탯 매핑
        stat_map = {"감각": "perception", "지성": "intelligence", "의지": "willpower"}
        eng_stat_name = stat_map.get(stat_name, "perception")

        user_stats = self.sheets.get_user_stats(discord_id=str(user_id))
        if user_stats and eng_stat_name in user_stats:
            base_target = user_stats[eng_stat_name]
            
        # 정신력 보정
        db = self.bot.get_cog("Survival").db
        user_state = db.fetch_one("SELECT current_sanity FROM user_state WHERE user_id = ?", (user_id,))
        sanity_percent = user_state[0] / 100.0 if user_state else 1.0
        current_stat = GameLogic.calculate_current_stat(base_target, sanity_percent)
        
        final_target = GameLogic.calculate_target_value(current_stat)
        
        # 2. 결과 판정 (명세서 규칙: M=90~100, P=1~9)
        result_type = GameLogic.check_result(dice_result, final_target)

        # 3. 결과 텍스트 선택 (M, N, O, P 열)
        result_text = ""
        if result_type == "CRITICAL_SUCCESS": # M
            result_text = variant.get("result_crit_success") or variant.get("result_success", "대성공!")
        elif result_type == "SUCCESS":        # N
            result_text = variant.get("result_success", "성공!")
        elif result_type == "FAILURE":        # O
            result_text = variant.get("result_fail", "실패...")
        elif result_type == "CRITICAL_FAILURE": # P
            result_text = variant.get("result_crit_fail") or variant.get("result_fail", "대실패!")

        # 4. 효과 파싱 (예: "문이 열렸다. [item+key,체력-5]")
        # 텍스트 내에 []가 있으면 효과로 간주, 없으면 전체가 텍스트이고 효과는 없음(또는 쉼표로 구분된 전체가 효과일 수도 있음 명세서에 따라)
        # 명세서: "각 칸에는 쉼표로 구분된 여러 효과를 나열... 묘사:텍스트"
        # 따라서 result_text 자체가 효과 문자열임.
        
        # 텍스트 출력용과 시스템 효과용 분리 필요
        # 명세서 예시: "trigger+power_on,체력-5,묘사:힘들게 스위치를 올렸다."
        
        effect_results = await self.apply_effects(user_id, result_text)
        
        # 묘사 텍스트 추출 (apply_effects에서 '묘사:...' 처리 후 반환하거나, 여기서 별도 처리)
        # apply_effects가 처리하고 남은 로그들을 보여줌.
        # 만약 '묘사:' 태그가 없다면, 기본적으로 성공/실패 텍스트는 시스템 메시지로 띄워줌.
        
        display_desc = ""
        # apply_effects 반환값 중 "📜 ..." 로 시작하는 것이 묘사라고 가정하거나
        # apply_effects 내부에서 묘사를 별도로 추출해야 함.
        # 여기서는 apply_effects가 리스트를 반환하므로 이를 합쳐서 보여줌.

        color_map = {
            "CRITICAL_SUCCESS": 0xf1c40f, # Gold
            "SUCCESS": 0x2ecc71,          # Green
            "FAILURE": 0xe74c3c,          # Red
            "CRITICAL_FAILURE": 0x95a5a6  # Grey
        }

        embed = discord.Embed(
            title=f"🎲 조사 결과: {result_type}",
            description=f"(주사위: {dice_result} / 목표: {final_target})\n\n",
            color=color_map.get(result_type, 0x3498db)
        )
        
        if effect_results:
            embed.add_field(name="결과", value="\n".join(effect_results), inline=False)
        else:
            embed.description += result_text # 효과 포맷이 아닐 경우 텍스트 그대로 출력

        await interaction.followup.send(embed=embed)

    async def apply_effects(self, user_id, effect_string):
        """효과 적용 로직 (기존 유지)"""
        if not effect_string: return []
        results = []
        tokens = [t.strip() for t in effect_string.split(',')]
        db = self.bot.get_cog("Survival").db
        
        for token in tokens:
            try:
                if token.startswith("clue+"):
                    clue_id = token.split('+')[1]
                    # TODO: 단서 이름 가져오기
                    db.execute_query("INSERT OR IGNORE INTO user_clues (user_id, clue_id, clue_name) VALUES (?, ?, ?)", (user_id, clue_id, clue_id))
                    results.append(f"🔍 단서 획득: {clue_id}")
                elif token.startswith("item+"):
                    item_name = token.split('+')[1]
                    db.execute_query("INSERT INTO user_inventory (user_id, item_name, count) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET count = count + 1", (user_id, item_name))
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
    def find_parent_node(self, root_node, target_node_id):
        """트리에서 타겟 노드의 부모를 찾습니다."""
        if "children" not in root_node:
            return None
        
        for child_name, child_node in root_node["children"].items():
            if child_node.get("id") == target_node_id:
                return root_node
            
            # 재귀 검색
            parent = self.find_parent_node(child_node, target_node_id)
            if parent:
                return parent
        return None
class GatheringView(discord.ui.View):
    def __init__(self, expected_members, timeout=300):
        super().__init__(timeout=timeout)
        self.expected_members = set(expected_members)
        self.ready_members = set()
        self.all_ready = False

    @discord.ui.button(label="출석 체크", style=discord.ButtonStyle.success, emoji="✅")
    async def check_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.expected_members:
            await interaction.response.send_message("참여 인원이 아닙니다.", ephemeral=True)
            return
        
        if interaction.user.id in self.ready_members:
            await interaction.response.send_message("이미 체크했습니다.", ephemeral=True)
            return

        self.ready_members.add(interaction.user.id)
        await interaction.response.send_message(f"{interaction.user.mention} 출석!", ephemeral=False)
        
        if len(self.ready_members) == len(self.expected_members):
            self.all_ready = True
            self.stop()

class InvestigationInteractionView(discord.ui.View):
    def __init__(self, cog, session, node):
        super().__init__(timeout=900) # 15분 타임아웃
        self.cog = cog
        self.session = session
        self.node = node
        self.message = None
        self.generate_buttons()

    async def on_timeout(self):
        """타임아웃 시 조사 중단"""
        if self.session.channel_id in self.cog.sessions:
            # 세션 제거 (조사 종료)
            del self.cog.sessions[self.session.channel_id]
            
            if self.message:
                try:
                    embed = discord.Embed(title="⌛ 조사 종료", description="15분 동안 활동이 없어 조사가 종료되었습니다.", color=0x95a5a6)
                    await self.message.edit(view=None, embed=embed)
                except:
                    pass

    async def disable_all_buttons(self, interaction: discord.Interaction):
        """모든 버튼 비활성화 및 메시지 업데이트"""
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    def generate_buttons(self):
        # 1. Back 버튼 (이전 지역)
        # 현재 노드가 루트(Category)가 아닌 경우에만 표시
        # parent를 찾기 위해 전체 데이터를 뒤져야 함
        investigation_data = self.cog.sheets.cached_data.get('investigation', {})
        category_root = investigation_data.get(self.session.location_name)
        
        if category_root and self.node.get("id") != category_root.get("id"):
            # 현재 노드가 카테고리 루트가 아님 -> 상위 노드 존재
            # 트리 탐색으로 부모 찾기
            parent = self.cog.find_parent_node(category_root, self.node.get("id"))
            if parent:
                back_btn = discord.ui.Button(label="◀️ 이전 지역", style=discord.ButtonStyle.secondary, row=4)
                back_btn.callback = self.create_move_callback(parent)
                self.add_item(back_btn)

        # 2. 하위 지역 (이동)
        if "children" in self.node:
            for child_name, child_data in self.node["children"].items():
                button = discord.ui.Button(label=child_name, style=discord.ButtonStyle.primary, custom_id=f"move:{child_data['id']}")
                button.callback = self.create_move_callback(child_data)
                self.add_item(button)

        # 3. 상호작용 (아이템)
        if "items" in self.node:
            for item in self.node["items"]:
                # Custom ID 중복 방지를 위해 item name + node id 조합 등 사용 권장되지만
                # 여기서는 SheetsManager에서 중복 처리 로직이 수정되었다고 가정하고 진행
                # 또는 item['name']만 사용하되 리스트 인덱스 추가
                btn_id = f"act:{self.node['id']}:{item['name']}" 
                button = discord.ui.Button(
                    label=item["button_text"], 
                    style=discord.ButtonStyle.secondary, 
                    emoji="🔍",
                    custom_id=btn_id
                )
                button.callback = self.create_action_callback(item)
                self.add_item(button)

    def create_move_callback(self, target_node):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id not in self.session.members:
                await interaction.response.send_message("조사 인원만 이동할 수 있습니다.", ephemeral=True)
                return
            
            # 버튼 비활성화
            await self.disable_all_buttons(interaction)

            # 이동 로직
            self.session.current_location_node = target_node
            await self.cog.show_location(interaction.channel, self.session)
            
        return callback

    def create_action_callback(self, item_data):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id not in self.session.members:
                await interaction.response.send_message("조사 인원만 상호작용할 수 있습니다.", ephemeral=True)
                return
            
            # 버튼 비활성화
            await self.disable_all_buttons(interaction)

            # Variant 선택 로직
            selected_variant = None
            stats = self.cog.sheets.get_user_stats(discord_id=str(interaction.user.id))
            user_state = {"stats": stats, "inventory": []} # 인벤토리 연동 필요
            world_state = {}

            if "variants" in item_data:
                for variant in item_data["variants"]:
                    conditions = ConditionParser.parse_condition_string(variant["condition"])
                    if not conditions:
                        selected_variant = variant
                        break
                    check = ConditionParser.evaluate_all(conditions, user_state, world_state)
                    if check["enabled"]:
                        selected_variant = variant
                        break
            
            if not selected_variant:
                # Fallback
                selected_variant = item_data.get("variants", [{}])[0]

            if item_data["type"] == "investigation":
                # 주사위 대기 상태로 전환
                self.cog.active_investigations[interaction.user.id] = {
                    "state": "waiting_for_dice",
                    "item_data": item_data,
                    "variant": selected_variant,
                    "channel_id": interaction.channel_id
                }
                
                msg = await interaction.channel.send(
                    f"🔍 **{item_data['name']}** 조사를 시작합니다.\n"
                    f"{selected_variant.get('description', '')}\n"
                    f"`/주사위` 명령어를 입력하여 판정을 진행하세요!"
                )
                
                # 조사 후에도 현재 위치 다시 보여주기? 
                # 기획에 따라 다르지만, 보통 결과 보고 후 머무르거나 함.
                # 여기서는 버튼이 비활성화되었으므로, 다시 show_location을 호출해주는 게 좋을 수 있음.
                # 하지만 주사위 결과가 나와야 하므로 주사위 콜백에서 처리하는게 맞음.
            else:
                # 즉시 완료 타입
                await interaction.followup.send(
                    f"**{item_data['name']}**\n{selected_variant.get('description', '')}",
                    ephemeral=True
                )
                # 뷰 리프레시 (버튼 다시 활성화된 새 뷰 출력)
                await self.cog.show_location(interaction.channel, self.session)

        return callback

async def setup(bot):
    await bot.add_cog(Investigation(bot))