import discord
from discord.ext import commands
from discord import app_commands
from utils.sheets import SheetsManager
from utils.game_logic import GameLogic
import logging
from typing import Literal

logger = logging.getLogger('cogs.stats')

class CluesView(discord.ui.View):
    """단서 목록을 표시하는 View"""
    def __init__(self, clues_data, timeout=180):
        super().__init__(timeout=timeout)
        self.clues_data = clues_data
    
    @discord.ui.button(label="단서 목록 보기", style=discord.ButtonStyle.primary, emoji="🔍")
    async def show_clues(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.clues_data:
            await interaction.response.send_message("보유한 단서가 없습니다.", ephemeral=True)
            return
        
        embed = discord.Embed(title="🔍 보유 단서 목록", color=0xe67e22)
        
        for clue_name, acquired_at in self.clues_data:
            embed.add_field(
                name=clue_name,
                value=f"획득: {acquired_at}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sheets = SheetsManager()

    # Discord 명령어 핸들러
    @app_commands.command(name="현재상태", description="캐릭터의 모든 상태 정보를 확인합니다.")
    async def current_status(self, interaction: discord.Interaction):
        """
        통합된 상태 확인 명령어
        - 스탯 (감각, 지성, 의지)
        - 체력, 정신력, 허기
        - 광기 목록
        - 인벤토리
        - 단서 목록 (버튼으로 확인)
        """
        logger.info(f"[현재상태] 명령어 시작 - 사용자: {interaction.user.display_name} (ID: {interaction.user.id})")
        await interaction.response.defer()
        
        # 스탯 조회
        logger.debug(f"[현재상태] 스탯 조회 시작 - Discord ID: {interaction.user.id}")
        stats = await self.sheets.get_user_stats_async(discord_id=str(interaction.user.id), nickname=interaction.user.display_name)
        
        if not stats:
            logger.warning(f"[현재상태] 스탯 데이터 없음 - 사용자: {interaction.user.display_name} (ID: {interaction.user.id})")
            await interaction.followup.send(
                f"❌ '{interaction.user.display_name}'님의 데이터를 찾을 수 없습니다. "
                f"닉네임 형식을 확인하거나 메타데이터 시트에 등록해주세요.", 
                ephemeral=True
            )
            return
        
        logger.info(f"[현재상태] 스탯 조회 성공 - 이름: {stats['name']}, HP: {stats['hp']}, Sanity: {stats['sanity']}")

        # DB에서 허기 및 광기 로드
        db = self.bot.db_manager
        logger.debug(f"[현재상태] DB에서 user_state 조회 시작 - User ID: {interaction.user.id}")
        user_state = await db.fetch_one("SELECT current_hunger, hunger_zero_days FROM user_state WHERE user_id = ?", (interaction.user.id,))
        
        current_hunger = user_state[0] if user_state else 100
        hunger_zero_days = user_state[1] if user_state else 0
        logger.debug(f"[현재상태] 허기 정보 - current_hunger: {current_hunger}, hunger_zero_days: {hunger_zero_days}")
        
        # 정신력 반영 현재 스탯 계산
        sanity_percent = stats['sanity'] / 100.0 if stats['sanity'] > 0 else 0
        logger.debug(f"[현재상태] 정신력 비율 계산 - sanity_percent: {sanity_percent:.2%}")
        
        # 허기 페널티 적용 스탯 계산
        logger.debug(f"[현재상태] 허기 페널티 계산 전 - Perception: {stats['perception']}, Intelligence: {stats['intelligence']}, Willpower: {stats['willpower']}")
        base_perception = GameLogic.calculate_hunger_penalty(stats['perception'], hunger_zero_days)
        base_intelligence = GameLogic.calculate_hunger_penalty(stats['intelligence'], hunger_zero_days)
        base_willpower = GameLogic.calculate_hunger_penalty(stats['willpower'], hunger_zero_days)
        logger.debug(f"[현재상태] 허기 페널티 적용 후 - Perception: {base_perception}, Intelligence: {base_intelligence}, Willpower: {base_willpower}")
        
        current_perception = GameLogic.calculate_current_stat(base_perception, sanity_percent)
        current_intelligence = GameLogic.calculate_current_stat(base_intelligence, sanity_percent)
        current_willpower = GameLogic.calculate_current_stat(base_willpower, sanity_percent)
        logger.debug(f"[현재상태] 정신력 반영 최종 스탯 - Perception: {current_perception}, Intelligence: {current_intelligence}, Willpower: {current_willpower}")

        # 광기 목록 로드
        logger.debug(f"[현재상태] 광기 목록 조회 시작 - User ID: {interaction.user.id}")
        madness_list = await db.fetch_all("SELECT madness_name FROM user_madness WHERE user_id = ?", (interaction.user.id,))
        madness_names = ", ".join([m[0] for m in madness_list]) if madness_list else "없음"
        logger.debug(f"[현재상태] 광기 목록 ({len(madness_list)}개) - {madness_names}")
        
        # 인벤토리 로드
        logger.debug(f"[현재상태] 인벤토리 조회 시작 - User ID: {interaction.user.id}")
        items = await db.fetch_all("SELECT item_name, count FROM user_inventory WHERE user_id = ?", (interaction.user.id,))
        items_str = ", ".join([f"{i[0]} x{i[1]}" for i in items]) if items else "없음"
        logger.debug(f"[현재상태] 인벤토리 ({len(items)}개 아이템) - {items_str}")

        # 단서 로드 (버튼용)
        logger.debug(f"[현재상태] 단서 목록 조회 시작 - User ID: {interaction.user.id}")
        clues = await db.fetch_all(
            "SELECT clue_name, acquired_at FROM user_clues WHERE user_id = ? ORDER BY acquired_at DESC",
            (interaction.user.id,)
        )
        logger.debug(f"[현재상태] 단서 목록 ({len(clues)}개 단서) 조회 완료")

        # 임베드 생성
        logger.debug(f"[현재상태] Embed 생성 시작")
        embed = discord.Embed(title=f"📊 {stats['name']}님의 상태", color=0x3498db)
        
        # 기본 상태
        embed.add_field(name="❤️ 체력 (HP)", value=f"{stats['hp']}", inline=True)
        embed.add_field(name="🧠 정신력 (Sanity)", value=f"{stats['sanity']}%", inline=True)
        embed.add_field(name="🍞 허기 (Hunger)", value=f"{current_hunger}/50", inline=True)

        # 스탯 페널티 표시 로직
        def format_stat(current, base_original):
            if current < base_original:
                logger.debug(f"[현재상태] 스탯 페널티 표시 - Current: {current}, Original: {base_original}")
                return f"**{current}** (🔻{base_original})"
            return f"**{current}**"

        embed.add_field(
            name="👁️ 감각 (Perception)", 
            value=format_stat(current_perception, stats['perception']), 
            inline=True
        )
        embed.add_field(
            name="🧩 지성 (Intelligence)", 
            value=format_stat(current_intelligence, stats['intelligence']), 
            inline=True
        )
        embed.add_field(
            name="💪 의지 (Willpower)", 
            value=format_stat(current_willpower, stats['willpower']), 
            inline=True
        )
        
        # 광기
        embed.add_field(name="🎭 보유 광기", value=madness_names, inline=False)
        
        # 인벤토리
        embed.add_field(name="🎒 인벤토리", value=items_str, inline=False)
        
        # 허기 관련 정보
        willpower = base_willpower
        decay = 10 + (willpower * 0.04)
        days_left = current_hunger / decay if decay > 0 else 999
        logger.debug(f"[현재상태] 허기 계산 - decay: {decay:.1f}, days_left: {days_left:.1f}")
        embed.add_field(
            name="📉 허기 정보",
            value=f"일일 소모: {decay:.1f} | 예상 지속: {days_left:.1f}일",
            inline=False
        )
        
        # 정신력 회복 정보
        intelligence = base_intelligence
        threshold = 30 + (intelligence * 0.2)
        logger.debug(f"[현재상태] 회복 임계값 계산 - threshold: {int(threshold)}")
        embed.add_field(
            name="🛌 회복 필요 허기",
            value=f"{int(threshold)} 이상 (정신력 회복 가능)",
            inline=False
        )
        
        # 상태 메시지
        logger.debug(f"[현재상태] 상태 이상 체크 시작")
        status_msg = []
        if stats['sanity'] <= 0:
            status_msg.append("⚠️ **광기 상태**: 정신력이 바닥났습니다.")
            logger.warning(f"[현재상태] 광기 상태 감지 - Sanity: {stats['sanity']}")
        elif stats['sanity'] < 50:
            status_msg.append("⚠️ **불안**: 정신적으로 불안정합니다.")
            logger.info(f"[현재상태] 불안 상태 감지 - Sanity: {stats['sanity']}")
        
        if current_hunger <= 0:
            if hunger_zero_days >= 7:
                status_msg.append("💀 **아사**: 굶주림으로 인해 행동불능 상태입니다.")
                logger.error(f"[현재상태] 아사 상태 감지 - hunger_zero_days: {hunger_zero_days}")
            elif hunger_zero_days >= 3:
                status_msg.append(f"⚠️ **굶주림 ({hunger_zero_days}일차)**: 몸이 쇠약해집니다. (스탯 -10%)")
                logger.warning(f"[현재상태] 굶주림 상태 감지 - hunger_zero_days: {hunger_zero_days}")
            else:
                status_msg.append(f"⚠️ **배고픔 ({hunger_zero_days}일차)**: 배가 고파 몸이 무겁습니다. (스탯 -5%)")
                logger.info(f"[현재상태] 배고픔 상태 감지 - hunger_zero_days: {hunger_zero_days}")
        elif current_hunger <= 10:
            status_msg.append("⚠️ **배고픔**: 배가 많이 고픕니다.")
            logger.info(f"[현재상태] 저허기 상태 감지 - current_hunger: {current_hunger}")
        
        if status_msg:
            embed.add_field(name="⚠️ 상태 이상", value="\n".join(status_msg), inline=False)
            logger.info(f"[현재상태] 상태 이상 {len(status_msg)}개 표시")

        # 단서 목록 버튼이 있는 View
        view = CluesView(clues)
        
        logger.info(f"[현재상태] 명령어 완료 - 사용자: {stats['name']}")
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="주사위", description="주사위를 굴립니다. 조사 중이라면 판정에 사용됩니다.")
    @app_commands.describe(
        min_val="최솟값 (기본: 1)",
        max_val="최댓값 (기본: 100)",
        stat="판정할 스탯 (선택사항)"
    )
    @app_commands.choices(stat=[
        app_commands.Choice(name="감각", value="감각"),
        app_commands.Choice(name="지성", value="지성"),
        app_commands.Choice(name="의지", value="의지")
    ])
    async def dice(
        self,
        interaction: discord.Interaction,
        min_val: int = 1,
        max_val: int = 100,
        stat: str = None
    ):
        """주사위 굴림 및 스탯 판정"""
        
        # 1. 주사위 굴림
        result = GameLogic.roll_dice(min_val, max_val)
        
        # 2. 조사 시스템 연동 확인
        inv_cog = self.bot.get_cog("Investigation")
        if inv_cog and interaction.user.id in inv_cog.active_investigations:
            # 조사 판정 대기 중인 경우 해당 로직으로 넘김
            active_data = inv_cog.active_investigations[interaction.user.id]
            if active_data["channel_id"] == interaction.channel_id:
                await interaction.response.defer() # 조사 로직에서 followup 사용
                await inv_cog.process_investigation_dice(interaction, result)
                return

        # 3. 일반 주사위 또는 단순 스탯 판정 (조사 아님)
        if stat is None:
            await interaction.response.send_message(f"🎲 주사위 결과: **{result}** ({min_val}-{max_val})")
            return
        
        # 판정이 있는 경우: 단순 스탯 판정
        await interaction.response.defer()
        
        stats = await self.sheets.get_user_stats_async(discord_id=str(interaction.user.id), nickname=interaction.user.display_name)
        if not stats:
            await interaction.followup.send("❌ 스탯 정보를 불러올 수 없습니다.", ephemeral=True)
            return
        
        stat_map = {"감각": "perception", "지성": "intelligence", "의지": "willpower"}
        base_stat_value = stats.get(stat_map.get(stat), 0)
        
        # 정신력 반영 등 기존 로직 수행
        db = self.bot.db_manager
        user_state = await db.fetch_one("SELECT current_sanity, hunger_zero_days FROM user_state WHERE user_id = ?", (interaction.user.id,))
        sanity_percent = user_state[0] / 100.0 if user_state else 1.0
        hunger_zero_days = user_state[1] if user_state else 0
        
        # 허기 페널티 적용
        base_stat_value = GameLogic.calculate_hunger_penalty(base_stat_value, hunger_zero_days)
        
        current_stat_value = GameLogic.calculate_current_stat(base_stat_value, sanity_percent)
        target_value = GameLogic.calculate_target_value(current_stat_value)
        
        result_type = GameLogic.check_result(result, target_value)
        
        embed = discord.Embed(
            title=f"🎲 {stat} 판정",
            color=0x2ecc71 if "SUCCESS" in result_type else 0xe74c3c
        )
        embed.add_field(name="주사위", value=f"**{result}**", inline=True)
        embed.add_field(name="목표값", value=f"{target_value}", inline=True)
        embed.add_field(name="결과", value=result_type, inline=False)
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="회복", description="식사 또는 휴식으로 허기나 정신력을 회복합니다.")
    @app_commands.describe(
        type="회복 방식",
        item_name="먹을 음식 이름 (식사 선택 시 필수)"
    )
    async def recover(
        self,
        interaction: discord.Interaction,
        type: Literal["식사", "휴식"],
        item_name: str = None
    ):
        """
        통합 회복 명령어
        - 식사: 음식을 먹어 허기 회복
        - 휴식: 휴식을 취해 정신력 회복
        """
        survival_cog = self.bot.get_cog("Survival")
        if not survival_cog:
            await interaction.response.send_message("❌ 시스템 오류가 발생했습니다.", ephemeral=True)
            return
        
        if type == "식사":
            # 아이템 이름 필수 체크
            if not item_name:
                await interaction.response.send_message("❌ 먹을 음식 이름을 입력해주세요.", ephemeral=True)
                return
            
            # Survival Cog의 eat_food 로직 호출
            db = self.bot.db_manager
            
            inventory_item = await db.fetch_one(
                "SELECT count FROM user_inventory WHERE user_id = ? AND item_name = ?",
                (interaction.user.id, item_name)
            )
            
            if not inventory_item or inventory_item[0] < 1:
                await interaction.response.send_message("❌ 해당 아이템을 가지고 있지 않습니다.", ephemeral=True)
                return

            item_data = await self.sheets.get_item_data_async(item_name)
            
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

            state = await survival_cog.get_user_state(interaction.user.id)
            MAX_HUNGER = 50
            
            if state['hunger'] >= MAX_HUNGER:
                await interaction.response.send_message("❌ 배가 부릅니다.", ephemeral=True)
                return
                
            new_hunger = min(MAX_HUNGER, state['hunger'] + recovery)
            
            await db.execute_query(
                """UPDATE user_state 
                   SET current_hunger = ?, hunger_zero_days = 0 
                   WHERE user_id = ?""",
                (new_hunger, interaction.user.id)
            )
            
            await db.execute_query(
                """UPDATE user_inventory 
                   SET count = count - 1 
                   WHERE user_id = ? AND item_name = ?""",
                (interaction.user.id, item_name)
            )
            
            await db.execute_query(
                "DELETE FROM user_inventory WHERE user_id = ? AND count <= 0",
                (interaction.user.id,)
            )
            
            await interaction.response.send_message(
                f"🍞 {item_name}을(를) 먹었습니다. (허기 {int(state['hunger'])} → {int(new_hunger)})"
            )
        
        elif type == "휴식":
            # Survival Cog의 rest 로직 호출
            import datetime
            
            db = self.bot.db_manager
            state = await survival_cog.get_user_state(interaction.user.id)
            
            if state['last_sanity_recovery']:
                last_date = datetime.datetime.strptime(state['last_sanity_recovery'], "%Y-%m-%d %H:%M:%S").date()
                if last_date == datetime.date.today():
                    await interaction.response.send_message("❌ 이미 오늘 휴식을 취했습니다.", ephemeral=True)
                    return
            
            stats = await self.sheets.get_user_stats_async(discord_id=str(interaction.user.id), nickname=interaction.user.display_name)
            if not stats:
                await interaction.response.send_message("❌ 스탯 정보를 불러올 수 없습니다.", ephemeral=True)
                return
            
            # hunger_zero_days 조회
            user_state = await db.fetch_one("SELECT hunger_zero_days FROM user_state WHERE user_id = ?", (interaction.user.id,))
            hunger_zero_days = user_state[0] if user_state else 0
            
            # 페널티 적용된 지성 사용
            effective_intelligence = GameLogic.calculate_hunger_penalty(stats['intelligence'], hunger_zero_days)

            threshold = 30 + (effective_intelligence * 0.2)
            if state['hunger'] < threshold:
                await interaction.response.send_message(
                    f"❌ 배가 너무 고파 휴식을 취할 수 없습니다. (필요 허기: {int(threshold)})", 
                    ephemeral=True
                )
                return

            # 페널티 적용된 의지 사용
            effective_willpower = GameLogic.calculate_hunger_penalty(stats['willpower'], hunger_zero_days)
            recovery = 10 + (effective_willpower / 10)
            new_sanity = min(100, state['sanity'] + recovery)
            
            await db.execute_query(
                "UPDATE user_state SET current_sanity = ?, last_sanity_recovery = CURRENT_TIMESTAMP WHERE user_id = ?",
                (new_sanity, interaction.user.id)
            )
            
            await interaction.response.send_message(
                f"💤 휴식을 취했습니다. (정신력 {int(state['sanity'])} → {int(new_sanity)})"
            )

async def setup(bot):
    await bot.add_cog(Stats(bot))