import discord
from discord.ext import commands
from discord import app_commands
from utils.game_logic import GameLogic
from utils.sheets import SheetsManager
from utils.condition_parser import ConditionParser
from utils.effect_parser import EffectParser
import logging
import asyncio
import datetime
import config
import json
import random

logger = logging.getLogger('cogs.investigation')

class InvestigationSession:
    def __init__(self, leader_id, channel_id, members, location_name, scheduled_time):
        self.leader_id = leader_id
        self.channel_id = channel_id
        self.members = members # [user_id, ...]
        self.location_name = location_name # Category Name
        self.scheduled_time = scheduled_time
        self.current_location_node = None
        self.state = "active" # active, paused
        self.interaction_counts = {} # item_id -> count
        self.active_interactions = {} # user_id -> interaction_state
        self.triggers = set() # Active triggers for this session
        self.pending_rolls = {} # user_id -> {item, variant, target_stat, channel_id}

    def add_pending_roll(self, user_id, item, variant, target_stat):
        self.pending_rolls[user_id] = {
            "item": item,
            "variant": variant,
            "target_stat": target_stat,
            "timestamp": datetime.datetime.now()
        }

    def get_pending_roll(self, user_id):
        return self.pending_rolls.get(user_id)

    def remove_pending_roll(self, user_id):
        if user_id in self.pending_rolls:
            del self.pending_rolls[user_id]

class GatheringView(discord.ui.View):
    def __init__(self, cog, channel, members, leader_id, category_name, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.channel = channel
        self.expected_members = set(members)
        self.leader_id = leader_id
        self.category_name = category_name
        self.ready_members = set()
        self.all_ready = False
        self.message = None

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
            await self.cog.start_investigation(self.channel, list(self.expected_members), self.category_name)

    async def on_timeout(self):
        if self.all_ready: return
        if not self.ready_members:
            await self.channel.send("❌ 아무도 오지 않아 조사가 취소되었습니다.")
            return

        if self.leader_id not in self.ready_members:
             await self.channel.send("❌ 리더가 도착하지 않아 조사가 취소되었습니다.")
             return

        view = GatheringTimeoutView(self.cog, self.channel, self.ready_members, self.category_name, self.leader_id)
        await self.channel.send(
            f"⚠️ 일부 인원이 도착하지 않았습니다. (현재 {len(self.ready_members)}/{len(self.expected_members)}명)\n어떻게 하시겠습니까?", 
            view=view
        )

class GatheringTimeoutView(discord.ui.View):
    def __init__(self, cog, channel, current_members, category_name, leader_id):
        super().__init__(timeout=60)
        self.cog = cog
        self.channel = channel
        self.current_members = list(current_members)
        self.category_name = category_name
        self.leader_id = leader_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.leader_id

    @discord.ui.button(label="현재 인원으로 진행", style=discord.ButtonStyle.primary)
    async def proceed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("현재 인원으로 조사를 시작합니다.")
        await self.cog.start_investigation(self.channel, self.current_members, self.category_name)
        self.stop()

    @discord.ui.button(label="조사 포기", style=discord.ButtonStyle.danger)
    async def abort(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("조사를 포기했습니다.")
        self.stop()

    @discord.ui.button(label="추가 영입 (명령어 사용)", style=discord.ButtonStyle.secondary)
    async def recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("`/조사 영입 @유저` 명령어를 사용하여 멤버를 추가한 후 다시 진행해주세요. (구현 예정)")
        self.stop()

class InvestigationInteractionView(discord.ui.View):
    def __init__(self, cog, session, node):
        super().__init__(timeout=900)
        self.cog = cog
        self.session = session
        self.node = node
        self.message = None
        self.generate_buttons()

    async def on_timeout(self):
        if self.session.channel_id in self.cog.sessions:
            del self.cog.sessions[self.session.channel_id]
            if self.message:
                try:
                    embed = discord.Embed(title="⌛ 조사 종료", description="활동이 없어 조사가 종료되었습니다.", color=0x95a5a6)
                    await self.message.edit(view=None, embed=embed)
                except: pass

    def generate_buttons(self):
        world_state = self.cog.get_world_state(self.session)
        investigation_data = self.cog.sheets.cached_data.get('investigation', {})
        category_root = investigation_data.get(self.session.location_name)
        
        if category_root and self.node.get("id") != category_root.get("id"):
            parent = self.cog.find_parent_node(category_root, self.node.get("id"))
            if parent:
                back_btn = discord.ui.Button(label="◀️ 돌아가기", style=discord.ButtonStyle.secondary, row=4)
                back_btn.callback = self.create_move_callback(parent)
                self.add_item(back_btn)

        if "children" in self.node:
            for child_name, child_data in self.node["children"].items():
                # 하위 지역 진입 조건 확인 (block 등)
                if "condition" in child_data and child_data["condition"]:
                    conds = ConditionParser.parse_condition_string(child_data["condition"])
                    leader_id = self.session.members[0]
                    leader_state = self.cog.get_user_state(leader_id)
                    check = ConditionParser.evaluate_all(conds, leader_state, world_state)
                    
                    if not check["visible"]:
                        continue # 버튼 숨김
                
                button = discord.ui.Button(label=child_name, style=discord.ButtonStyle.primary, custom_id=f"move:{child_data['id']}")
                button.callback = self.create_move_callback(child_data)
                self.add_item(button)

        if "items" in self.node:
            for idx, item in enumerate(self.node["items"]):
                visible = False
                enabled = False
                
                leader_id = self.session.members[0]
                leader_state = self.cog.get_user_state(leader_id)
                
                for variant in item["variants"]:
                    conds = ConditionParser.parse_condition_string(variant["condition"])
                    check = ConditionParser.evaluate_all(conds, leader_state, world_state)
                    if check["visible"]:
                        visible = True
                        if check["enabled"]:
                            enabled = True
                            break
                
                if not visible: continue
                
                label = item["button_text"]
                if not enabled: label = f"🔒 {label}"
                
                btn_id = f"act:{self.node['id']}:{item['name']}:{idx}" 
                button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, emoji="🔍", custom_id=btn_id, disabled=not enabled)
                button.callback = self.create_interaction_callback(item)
                self.add_item(button)

    def disable_all_items(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button) or isinstance(item, discord.ui.Select):
                item.disabled = True

    def create_move_callback(self, target_node):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id not in self.session.members:
                await interaction.response.send_message("조사 참여자가 아닙니다.", ephemeral=True)
                return
            
            # A열 장소(최상위)이고 하위 장소가 없는 경우 -> 채널 이동
            if target_node.get("is_channel", False) and not target_node.get("children"):
                # 해당 이름의 채널 찾기
                guild = interaction.guild
                target_channel = discord.utils.get(guild.channels, name=target_node["name"])
                if target_channel:
                    await interaction.response.send_message(f"🏃 {target_channel.mention}으로 이동합니다!", ephemeral=True)
                    # 이동한 채널에서 조사 UI 출력
                    self.session.current_location_node = target_node
                    self.session.channel_id = target_channel.id # 세션 채널 ID 업데이트?
                    # 주의: 세션 키가 channel_id라면, 세션을 옮겨야 함.
                    # 하지만 간단히 봇이 그 채널에 메시지를 보내게 함.
                    await self.cog.show_location(target_channel, self.session)
                    return
                else:
                    await interaction.response.send_message(f"❌ 이동할 채널({target_node['name']})을 찾을 수 없습니다.", ephemeral=True)
                    return

            self.session.current_location_node = target_node
            await interaction.response.defer()
            await self.cog.show_location(interaction.channel, self.session)
        return callback

    def create_interaction_callback(self, item):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id not in self.session.members:
                await interaction.response.send_message("조사 참여자가 아닙니다.", ephemeral=True)
                return

            # 버튼 비활성화
            self.disable_all_items()
            await interaction.response.edit_message(view=self)

            user_state = self.cog.get_user_state(interaction.user.id)
            world_state = self.cog.get_world_state(self.session)
            world_state['current_item_id'] = f"{self.node['id']}_{item['name']}"
            
            selected_variant = None
            for variant in item["variants"]:
                conds = ConditionParser.parse_condition_string(variant["condition"])
                check = ConditionParser.evaluate_all(conds, user_state, world_state)
                if check["enabled"]:
                    selected_variant = variant
                    break
            
            if not selected_variant:
                await interaction.followup.send("조건을 만족하지 않아 상호작용할 수 없습니다.", ephemeral=True)
                return

            conds = ConditionParser.parse_condition_string(selected_variant["condition"])
            
            # 비용/소모 처리
            consumed_items = []
            for c in conds:
                if c['type'] == 'item' and 'consume' in c['options']:
                    req_items = [i.strip() for i in c['value'].split('|')]
                    user_inv = user_state.get('inventory', [])
                    for req in req_items:
                        if req in user_inv:
                            consumed_items.append(req)
                            break
            
            costs = []
            for c in conds:
                if c['type'] == 'cost':
                    res_name_kor, amount = c['value'].split(':')
                    res_name = ConditionParser.RESOURCE_MAP.get(res_name_kor, res_name_kor)
                    costs.append((res_name, int(amount)))

            db = self.cog.survival_db
            if consumed_items:
                for it in consumed_items:
                    await db.execute_query("UPDATE user_inventory SET count = count - 1 WHERE user_id = ? AND item_name = ?", (interaction.user.id, it))
                    await db.execute_query("DELETE FROM user_inventory WHERE user_id = ? AND item_name = ? AND count <= 0", (interaction.user.id, it))
            
            if costs:
                for res, amt in costs:
                    col_map = {"hp": "current_hp", "sanity": "current_sanity", "hunger": "current_hunger"}
                    col = col_map.get(res)
                    if col:
                        await db.execute_query(f"UPDATE user_state SET {col} = {col} - ? WHERE user_id = ?", (amt, interaction.user.id))

            i_type = item["type"]
            
            if i_type in ["investigation", "acquire", "use", "read"]:
                stat_map = {"investigation": "perception", "acquire": "perception", "use": "perception", "read": "intelligence"}
                default_stat = stat_map.get(i_type, "perception")
                target_stat = default_stat
                for c in conds:
                    if c['type'] == 'stat':
                        val_parts = c['value'].split(':')
                        if len(val_parts) >= 1:
                            k_stat = val_parts[0]
                            target_stat = ConditionParser.STAT_MAP.get(k_stat, k_stat)
                            break
                
                # 대기 상태로 전환
                self.session.add_pending_roll(interaction.user.id, item, selected_variant, target_stat)
                await interaction.followup.send(f"🎲 **{item['name']}** 판정 대기 중...\n`/주사위`를 입력하여 판정을 진행하세요. (목표: {target_stat})")

            elif i_type == "ritual":
                await self.cog.start_ritual(interaction, item, selected_variant, self.session)

            elif i_type == "combat":
                await self.cog.start_combat(interaction, item, selected_variant)

            else:
                # 판정 없는 상호작용
                res_key = "result_success"
                result_text = selected_variant.get("result_success", "")
                if not result_text: result_text = selected_variant.get("description", "")
                
                effect_res, description = await self.cog.apply_effects(interaction.user.id, result_text, self.session)
                
                final_desc = result_text
                if description: final_desc = f"{result_text}\n\n{description}"
                
                embed = discord.Embed(title=f"🔍 {item['name']}", description=final_desc, color=0x95a5a6)
                if effect_res:
                    embed.add_field(name="효과", value="\n".join(effect_res), inline=False)
                
                await interaction.followup.send(embed=embed)
                await self.cog.show_location(interaction.channel, self.session)

        return callback

class RitualChoiceView(discord.ui.View):
    def __init__(self, cog, session, item, variant):
        super().__init__(timeout=300)
        self.cog = cog
        self.session = session
        self.item = item
        self.variant = variant
        self.forfeit_stat = None

    @discord.ui.button(label="감각 포기 (체력 -15)", style=discord.ButtonStyle.danger)
    async def forfeit_perception(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_forfeit(interaction, "perception", "hp", 15)

    @discord.ui.button(label="지식 포기 (정신력 -15)", style=discord.ButtonStyle.danger)
    async def forfeit_intelligence(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_forfeit(interaction, "intelligence", "sanity", 15)

    @discord.ui.button(label="의지 포기 (허기 -20)", style=discord.ButtonStyle.danger)
    async def forfeit_willpower(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_forfeit(interaction, "willpower", "hunger", 20)

    async def process_forfeit(self, interaction: discord.Interaction, stat, cost_type, cost_val):
        self.forfeit_stat = stat
        user_id = interaction.user.id
        db = self.cog.survival_db
        
        col_map = {"hp": "current_hp", "sanity": "current_sanity", "hunger": "current_hunger"}
        col = col_map.get(cost_type)
        if col:
            await db.execute_query(f"UPDATE user_state SET {col} = {col} - ? WHERE user_id = ?", (cost_val, user_id))
            
        await interaction.response.send_message(f"⚠️ {cost_type} {cost_val} 감소! {stat} 판정을 제외하고 의례를 진행합니다.")
        self.stop()
        await self.cog.process_ritual_roll(interaction.channel, self.session, self.item, self.variant, self.forfeit_stat)

class CombatView(discord.ui.View):
    def __init__(self, cog, session, item, variant):
        super().__init__(timeout=300)
        self.cog = cog
        self.session = session
        self.item = item
        self.variant = variant
        self.actions = {} # user_id -> stat_type

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.session.members:
            await interaction.response.send_message("전투 참여자가 아닙니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="관찰 (감각)", style=discord.ButtonStyle.primary, emoji="👁️")
    async def observe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_action(interaction, "perception")

    @discord.ui.button(label="분석 (지식)", style=discord.ButtonStyle.primary, emoji="🧠")
    async def analyze(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_action(interaction, "intelligence")

    @discord.ui.button(label="도주 (의지)", style=discord.ButtonStyle.danger, emoji="🏃")
    async def escape(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_action(interaction, "willpower")

    async def register_action(self, interaction: discord.Interaction, stat_type):
        self.actions[interaction.user.id] = stat_type
        await interaction.response.send_message(f"행동 선택 완료: {stat_type}", ephemeral=True)
        
        if len(self.actions) == len(self.session.members):
            self.stop()
            await self.cog.resolve_combat_round(interaction.channel, self.session, self.item, self.variant, self.actions)

class Investigation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sheets = SheetsManager()
        self.sessions = {} 
        self.reservations = []
        self.active_investigations = {}
        self.db = None 

    @property
    def survival_db(self):
        if not self.db:
            cog = self.bot.get_cog("Survival")
            if cog: self.db = cog.db
        return self.db

    def get_user_state(self, user_id):
        stats = self.sheets.get_user_stats(discord_id=str(user_id)) or {}
        return {
            "stats": stats,
            "inventory": [], 
            "hp": 100, "sanity": 100, "hunger": 100, "pollution": 0, 
            "skills": []
        }

    def get_world_state(self, session):
        return {
            "triggers": list(session.triggers), 
            "time": datetime.datetime.now().strftime("%H:%M"),
            "location_id": session.current_location_node['id'] if session.current_location_node else "",
            "members": session.members,
            "interaction_counts": session.interaction_counts,
            "current_item_id": ""
        }
    
    def find_parent_node(self, root_node, target_node_id):
        if "children" not in root_node: return None
        for child_name, child_node in root_node["children"].items():
            if child_node.get("id") == target_node_id: return root_node
            parent = self.find_parent_node(child_node, target_node_id)
            if parent: return parent
        return None

    async def category_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        guild = interaction.guild
        if not guild: return []
        categories = []
        for category in guild.categories:
            if category.name in ['통신채널', '공지_채널']: continue
            if current.lower() in category.name.lower():
                categories.append(app_commands.Choice(name=category.name, value=category.name))
        return categories[:25]

    @app_commands.command(name="조사신청", description="조사를 예약합니다.")
    @app_commands.describe(time_str="YY.MM.DD.HH.MM", category="지역", user1="동료1", user2="동료2")
    @app_commands.autocomplete(category=category_autocomplete)
    async def investigation_request(self, interaction: discord.Interaction, time_str: str, category: str, user1: discord.User = None, user2: discord.User = None):
        await interaction.response.defer()
        try:
            target_time = datetime.datetime.strptime(time_str, "%y.%m.%d.%H.%M")
        except ValueError:
            await interaction.followup.send("❌ 시간 형식 오류: `YY.MM.DD.HH.MM` (예: 25.11.29.13.06)", ephemeral=True)
            return

        if target_time < datetime.datetime.now():
            await interaction.followup.send("❌ 과거 시간 예약 불가", ephemeral=True)
            return

        members = [interaction.user.id]
        if user1: members.append(user1.id)
        if user2: members.append(user2.id)
        members = list(set(members))

        guild = interaction.guild
        target_category = discord.utils.get(guild.categories, name=category)
        if not target_category or not target_category.channels:
            await interaction.followup.send(f"❌ '{category}' 카테고리 또는 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        reservation = {
            'leader_id': interaction.user.id,
            'members': members,
            'time': target_time,
            'category': category,
            'channel_id': target_category.channels[0].id
        }
        self.reservations.append(reservation)
        
        member_names = [self.bot.get_user(uid).display_name for uid in members if self.bot.get_user(uid)]
        
        embed = discord.Embed(title="✅ 조사 예약 완료", color=0x2ecc71)
        embed.add_field(name="일시", value=target_time.strftime("%Y-%m-%d %H:%M"), inline=False)
        embed.add_field(name="지역", value=category, inline=True)
        embed.add_field(name="멤버", value=", ".join(member_names), inline=False)
        await interaction.followup.send(embed=embed)

        self.bot.loop.create_task(self.schedule_investigation(target_time, reservation))

    async def schedule_investigation(self, target_time, reservation):
        notify_time = target_time - datetime.timedelta(minutes=5)
        wait_sec = (notify_time - datetime.datetime.now()).total_seconds()
        if wait_sec > 0: await asyncio.sleep(wait_sec)
        
        if reservation not in self.reservations: return

        channel = self.bot.get_channel(reservation['channel_id'])
        notice_channel = self.bot.get_channel(config.NOTICE_CHANNEL_ID)
        
        if notice_channel:
            mentions = " ".join([f"<@{uid}>" for uid in reservation['members']])
            # 알림 메시지 수정
            await notice_channel.send(f"📢 **조사 알림**\n{mentions}님, {reservation['category']} 조사가 곧 시작됩니다. 신청한 카테고리의 맨 위 채널({channel.mention})로 와주세요!")

        wait_start = (target_time - datetime.datetime.now()).total_seconds()
        if wait_start > 0: await asyncio.sleep(wait_start)
            
        if reservation not in self.reservations: return
        self.reservations.remove(reservation)
        
        await self.start_gathering(channel, reservation['members'], reservation['leader_id'], reservation['category'])

    async def start_gathering(self, channel, members, leader_id, category_name):
        embed = discord.Embed(title="🕵️ 조사 인원 점호", description="5분 내에 ✅를 눌러주세요.", color=0xf1c40f)
        view = GatheringView(self, channel, members, leader_id, category_name)
        await channel.send(embed=embed, view=view)

    async def start_investigation(self, channel, members, category_name):
        data = self.sheets.fetch_investigation_data()
        if category_name not in data:
            await channel.send(f"❌ '{category_name}' 데이터가 없습니다.")
            return

        root = data[category_name]
        session = InvestigationSession(members[0], channel.id, members, category_name, datetime.datetime.now())
        session.current_location_node = root
        self.sessions[channel.id] = session
        
        await self.show_location(channel, session)

    async def show_location(self, channel, session):
        node = session.current_location_node
        embed = discord.Embed(title=f"📍 {node['name']}", description=node.get('description', ''), color=0x3498db)
        view = InvestigationInteractionView(self, session, node)
        msg = await channel.send(embed=embed, view=view)
        view.message = msg

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        # 사용자가 /주사위 명령어를 입력했을 때 감지 (슬래시 커맨드는 on_interaction이지만, 
        # 사용자가 텍스트로 /주사위 입력하는 경우도 고려)
        # 하지만 슬래시 커맨드는 여기서 잡히지 않음.
        # 만약 Basic Cog에서 주사위 결과를 출력한다면, 그 출력 메시지를 잡을 수도 있음.
        # 여기서는 일단 패스하고, process_dice_roll을 외부에서 호출해주길 기대하거나
        # 사용자가 텍스트로 !주사위 등을 쳤을 때를 대비.
        pass

    async def process_dice_roll(self, interaction: discord.Interaction, dice_value: int):
        """외부(Basic Cog 등)에서 주사위 굴림 발생 시 호출"""
        session = self.sessions.get(interaction.channel_id)
        if not session: return False 

        pending = session.get_pending_roll(interaction.user.id)
        if not pending: return False 

        item = pending['item']
        variant = pending['variant']
        target_stat = pending['target_stat']
        
        session.remove_pending_roll(interaction.user.id)

        await self.resolve_investigation_roll(interaction, item, variant, target_stat, dice_value)
        return True

    async def resolve_investigation_roll(self, interaction, item, variant, stat_name, dice_value):
        user_id = interaction.user.id
        stats = self.sheets.get_user_stats(discord_id=str(user_id))
        if not stats:
            await interaction.followup.send("스탯 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        target_val = stats.get(stat_name, 50)
        dice = dice_value
        
        target = GameLogic.calculate_target_value(target_val)
        result_type = GameLogic.check_result(dice, target)
        
        res_key = {"CRITICAL_SUCCESS": "result_crit_success", "SUCCESS": "result_success", "FAILURE": "result_fail", "CRITICAL_FAILURE": "result_crit_fail"}
        result_text = variant.get(res_key[result_type], "")
        
        effect_res, description = await self.apply_effects(user_id, result_text, self.sessions[interaction.channel_id])
        
        final_desc = result_text
        if description:
             final_desc = f"{result_text}\n\n{description}"
        
        embed = discord.Embed(title=f"🎲 {item['name']} - {result_type}", description=f"{final_desc}\n(주사위: {dice} / 목표: {target})", color=0x2ecc71 if "SUCCESS" in result_type else 0xe74c3c)
        if effect_res:
            embed.add_field(name="효과", value="\n".join(effect_res), inline=False)
            
        await interaction.followup.send(embed=embed)
        
        item_id = f"{self.sessions[interaction.channel_id].current_location_node['id']}_{item['name']}"
        self.sessions[interaction.channel_id].interaction_counts[item_id] = self.sessions[interaction.channel_id].interaction_counts.get(item_id, 0) + 1
        
        await self.show_location(interaction.channel, self.sessions[interaction.channel_id])

    async def start_ritual(self, interaction, item, variant, session):
        members = session.members
        count = len(members)
        
        if count == 1:
            await self.process_ritual_roll(interaction.channel, session, item, variant, None)
        elif count == 2:
            embed = discord.Embed(title="🕯️ 2인 의례", description="포기할 스탯을 선택해주세요.", color=0x9b59b6)
            view = RitualChoiceView(self, session, item, variant)
            await interaction.response.send_message(embed=embed, view=view)
        elif count >= 3:
            await self.process_ritual_roll(interaction.channel, session, item, variant, None)

    async def process_ritual_roll(self, channel, session, item, variant, forfeit_stat):
        members = session.members
        count = len(members)
        results = []
        detail_text = ""
        
        stats_to_roll = ["perception", "intelligence", "willpower"]
        if forfeit_stat:
            stats_to_roll.remove(forfeit_stat)
            
        if count == 1:
            user_id = members[0]
            stats = self.sheets.get_user_stats(discord_id=str(user_id))
            for stat in stats_to_roll:
                val = stats.get(stat, 50)
                dice = GameLogic.roll_dice()
                target = GameLogic.calculate_target_value(val)
                res = GameLogic.check_result(dice, target)
                results.append(res)
                detail_text += f"- {stat}: {res} ({dice}/{target})\n"
            final_res = GameLogic.check_ritual_result(results, "1_person")
            
        elif count == 2:
            detail_text = f"2인 의례 ({forfeit_stat} 포기)\n"
            for i, stat in enumerate(stats_to_roll):
                user_id = members[i % 2]
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                val = stats.get(stat, 50)
                dice = GameLogic.roll_dice()
                target = GameLogic.calculate_target_value(val)
                res = GameLogic.check_result(dice, target)
                results.append(res)
                detail_text += f"- <@{user_id}> ({stat}): {res} ({dice}/{target})\n"
            final_res = GameLogic.check_ritual_result(results, "2_person")
            
        else:
            detail_text = "3인 의례\n"
            for i, stat in enumerate(stats_to_roll):
                user_id = members[i % 3]
                stats = self.sheets.get_user_stats(discord_id=str(user_id))
                val = stats.get(stat, 50)
                dice = GameLogic.roll_dice()
                target = GameLogic.calculate_target_value(val)
                res = GameLogic.check_result(dice, target)
                results.append(res)
                detail_text += f"- <@{user_id}> ({stat}): {res} ({dice}/{target})\n"
            final_res = GameLogic.check_ritual_result(results, "3_person")

        res_key = {"CRITICAL_SUCCESS": "result_crit_success", "SUCCESS": "result_success", "FAILURE": "result_fail", "CRITICAL_FAILURE": "result_crit_fail"}
        result_text = variant.get(res_key[final_res], "")
        effect_res, description = await self.apply_effects(members[0], result_text, session)
        
        final_desc = result_text
        if description:
             final_desc = f"{result_text}\n\n{description}"

        embed = discord.Embed(title=f"🕯️ 의례 결과: {final_res}", description=f"{final_desc}\n\n{detail_text}", color=0x9b59b6)
        if effect_res: embed.add_field(name="효과", value="\n".join(effect_res), inline=False)
        await channel.send(embed=embed)

    async def start_combat(self, interaction, item, variant):
        embed = discord.Embed(title="⚔️ 몬스터 조우!", description=f"{item['name']}와(과) 마주쳤습니다!\n모든 멤버는 행동을 선택해주세요.", color=0x992d22)
        view = CombatView(self, self.sessions[interaction.channel_id], item, variant)
        await interaction.response.send_message(embed=embed, view=view)

    async def resolve_combat_round(self, channel, session, item, variant, actions):
        results_text = []
        group_escape = False
        
        round_outcomes = []
        for user_id, stat_type in actions.items():
            stats = self.sheets.get_user_stats(discord_id=str(user_id))
            val = stats.get(stat_type, 50)
            dice = GameLogic.roll_dice()
            target = GameLogic.calculate_target_value(val)
            res = GameLogic.check_result(dice, target)
            
            outcome = GameLogic.resolve_combat_outcome(stat_type, res)
            round_outcomes.append((user_id, stat_type, res, outcome))
            
            if outcome["group_escape"]:
                group_escape = True

        db = self.survival_db
        
        if group_escape:
            await channel.send("🏃‍♂️ **대성공!** 동료의 활약으로 모두 무사히 도망쳤습니다!")
            await self.show_location(channel, session)
            return

        for user_id, stat_type, res, outcome in round_outcomes:
            user_res_text = f"<@{user_id}> ({stat_type}): {res}\n"
            
            if outcome["escape"]:
                user_res_text += "💨 도주 성공 (피해 없음)\n"
            else:
                if outcome["hp"] != 0:
                    await db.execute_query("UPDATE user_state SET current_hp = current_hp + ? WHERE user_id = ?", (outcome["hp"], user_id))
                    user_res_text += f"체력 {outcome['hp']:+}\n"
                if outcome["sanity"] != 0:
                    await db.execute_query("UPDATE user_state SET current_sanity = current_sanity + ? WHERE user_id = ?", (outcome["sanity"], user_id))
                    user_res_text += f"정신력 {outcome['sanity']:+}\n"
                if outcome["hunger"] != 0:
                    await db.execute_query("UPDATE user_state SET current_hunger = current_hunger + ? WHERE user_id = ?", (outcome["hunger"], user_id))
                    user_res_text += f"허기 {outcome['hunger']:+}\n"
                if outcome["pollution"] != 0:
                    await db.execute_query("UPDATE user_state SET current_pollution = current_pollution + ? WHERE user_id = ?", (outcome["pollution"], user_id))
                    user_res_text += f"오염 {outcome['pollution']:+}\n"
            
            if outcome["info"]:
                user_res_text += f"💡 정보: {outcome['info']}\n"
                
            results_text.append(user_res_text)

        embed = discord.Embed(title="⚔️ 전투 결과", description="\n".join(results_text), color=0xe74c3c)
        await channel.send(embed=embed)
        
        await self.show_location(channel, session)

    async def apply_effects(self, user_id, text, session=None):
        effects, description = EffectParser.parse_effects(text)
        results = []
        db = self.survival_db
        if not db: return ["DB 연결 실패"], description

        for effect in effects:
            etype = effect['type']
            val = effect['value']
            
            if etype == "stat_change":
                stat = effect['stat']
                col_map = {"hp": "current_hp", "sanity": "current_sanity", "hunger": "current_hunger", "pollution": "current_pollution", "오염도": "current_pollution"}
                col = col_map.get(stat)
                if col:
                    await db.execute_query(f"UPDATE user_state SET {col} = {col} + ? WHERE user_id = ?", (val, user_id))
                    results.append(f"{stat} {val:+}")
                    
            elif etype == "trigger_add":
                if session:
                    if not hasattr(session, 'triggers'): session.triggers = set()
                    session.triggers.add(val)
                results.append(f"트리거 획득: {val}")
                
            elif etype == "trigger_remove":
                if session and hasattr(session, 'triggers'):
                    session.triggers.discard(val)
                results.append(f"트리거 제거: {val}")

            elif etype == "item_add":
                await db.execute_query("INSERT INTO user_inventory (user_id, item_name, count) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET count = count + 1", (user_id, val))
                results.append(f"아이템 획득: {val}")
                
            elif etype == "item_remove":
                await db.execute_query("UPDATE user_inventory SET count = count - 1 WHERE user_id = ? AND item_name = ?", (user_id, val))
                await db.execute_query("DELETE FROM user_inventory WHERE user_id = ? AND item_name = ? AND count <= 0", (user_id, val))
                results.append(f"아이템 소모: {val}")
                
            elif etype == "clue_add":
                 clue_data = self.sheets.get_clue_data(val)
                 if clue_data:
                     clue_name = clue_data['name']
                     clue_desc = clue_data['description']
                     results.append(f"단서 획득: {clue_name}\n단서 설명: {clue_desc}")
                     await db.execute_query("INSERT INTO user_clues (user_id, clue_id, clue_name) VALUES (?, ?, ?)", (user_id, val, clue_name))
                 else:
                     results.append(f"단서 획득: {val} (데이터 없음)")
                     await db.execute_query("INSERT INTO user_clues (user_id, clue_id, clue_name) VALUES (?, ?, ?)", (user_id, val, val))
                 
            elif etype == "block_add":
                 if session:
                    if not hasattr(session, 'triggers'): session.triggers = set()
                    session.triggers.add(val)
                 results.append(f"차단됨: {val}")

            elif etype == "spawn":
                 results.append(f"이벤트 발생: {val}")
                 
            elif etype == "move":
                 results.append(f"이동: {val}")

            elif etype == "time_pass":
                 results.append(f"시간 경과: {val}시간")

        return results, description

async def setup(bot):
    await bot.add_cog(Investigation(bot))