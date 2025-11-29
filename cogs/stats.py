import discord
from discord.ext import commands
from discord import app_commands
from utils.sheets import SheetsManager
from utils.game_logic import GameLogic
import logging

logger = logging.getLogger('cogs.stats')

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sheets = SheetsManager()

    @app_commands.command(name="상태", description="내 캐릭터의 스탯과 상태를 확인합니다.")
    async def status(self, interaction: discord.Interaction):
        """
        사용자의 닉네임을 기반으로 스탯을 조회하여 보여줍니다.
        """
        await interaction.response.defer()
        
        # 닉네임 파싱 및 스탯 조회
        # 메타데이터가 있으면 ID로 먼저 조회 시도
        stats = self.sheets.get_user_stats(nickname=interaction.user.display_name, discord_id=str(interaction.user.id))
        
        if not stats:
            await interaction.followup.send(f"❌ '{interaction.user.display_name}'님의 데이터를 찾을 수 없습니다. 닉네임 형식을 확인하거나 메타데이터 시트에 등록해주세요.", ephemeral=True)
            return

        # 현재 스탯 계산 (정신력 반영)
        sanity_percent = stats['sanity'] / 100.0 if stats['sanity'] > 0 else 0
        current_perception = GameLogic.calculate_current_stat(stats['perception'], sanity_percent)
        current_intelligence = GameLogic.calculate_current_stat(stats['intelligence'], sanity_percent)
        current_willpower = GameLogic.calculate_current_stat(stats['willpower'], sanity_percent)

        # DB에서 허기 및 광기 로드
        db = self.bot.get_cog("Survival").db
        user_state = db.fetch_one("SELECT current_hunger FROM user_state WHERE user_id = ?", (interaction.user.id,))
        current_hunger = user_state[0] if user_state else 0 # 기본값 0? or 100?
        
        madness_list = db.fetch_all("SELECT madness_name FROM user_madness WHERE user_id = ?", (interaction.user.id,))
        madness_names = ", ".join([m[0] for m in madness_list]) if madness_list else "없음"

        # 임베드 생성
        embed = discord.Embed(title=f"📊 {stats['name']}님의 상태", color=0x3498db)
        
        embed.add_field(name="체력 (HP)", value=f"{stats['hp']}", inline=True)
        embed.add_field(name="정신력 (Sanity)", value=f"{stats['sanity']}%", inline=True)
        embed.add_field(name="허기 (Hunger)", value=f"{current_hunger}/50", inline=True)

        embed.add_field(
            name="감각 (Perception)", 
            value=f"**{current_perception}** (기본: {stats['perception']})", 
            inline=True
        )
        embed.add_field(
            name="지성 (Intelligence)", 
            value=f"**{current_intelligence}** (기본: {stats['intelligence']})", 
            inline=True
        )
        embed.add_field(
            name="의지 (Willpower)", 
            value=f"**{current_willpower}** (기본: {stats['willpower']})", 
            inline=True
        )
        
        embed.add_field(name="보유 광기", value=madness_names, inline=False)
        
        # 상태 메시지 추가
        status_msg = []
        if stats['sanity'] <= 0:
            status_msg.append("⚠️ **광기 상태**: 정신력이 바닥났습니다. 환각이 보일 수 있습니다.")
        elif stats['sanity'] < 50:
            status_msg.append("⚠️ **불안**: 정신적으로 불안정합니다. 스탯이 크게 감소했습니다.")
        
        if current_hunger <= 0:
            status_msg.append("⚠️ **굶주림**: 배가 너무 고파 쓰러지기 직전입니다.")
        elif current_hunger <= 10:
            status_msg.append("⚠️ **배고픔**: 배가 많이 고픕니다.")
        
        if status_msg:
            embed.add_field(name="상태 이상", value="\n".join(status_msg), inline=False)

        await interaction.followup.send(embed=embed)

import discord
from discord.ext import commands
from discord import app_commands
from utils.sheets import SheetsManager
from utils.game_logic import GameLogic
import logging

logger = logging.getLogger('cogs.stats')

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sheets = SheetsManager()

    @app_commands.command(name="상태", description="내 캐릭터의 스탯과 상태를 확인합니다.")
    async def status(self, interaction: discord.Interaction):
        """
        사용자의 닉네임을 기반으로 스탯을 조회하여 보여줍니다.
        """
        await interaction.response.defer()
        
        # 닉네임 파싱 및 스탯 조회
        # 메타데이터가 있으면 ID로 먼저 조회 시도
        stats = self.sheets.get_user_stats(nickname=interaction.user.display_name, discord_id=str(interaction.user.id))
        
        if not stats:
            await interaction.followup.send(f"❌ '{interaction.user.display_name}'님의 데이터를 찾을 수 없습니다. 닉네임 형식을 확인하거나 메타데이터 시트에 등록해주세요.", ephemeral=True)
            return

        # 현재 스탯 계산 (정신력 반영)
        sanity_percent = stats['sanity'] / 100.0 if stats['sanity'] > 0 else 0
        current_perception = GameLogic.calculate_current_stat(stats['perception'], sanity_percent)
        current_intelligence = GameLogic.calculate_current_stat(stats['intelligence'], sanity_percent)
        current_willpower = GameLogic.calculate_current_stat(stats['willpower'], sanity_percent)

        # DB에서 허기 및 광기 로드
        db = self.bot.get_cog("Survival").db
        user_state = db.fetch_one("SELECT current_hunger FROM user_state WHERE user_id = ?", (interaction.user.id,))
        current_hunger = user_state[0] if user_state else 0 # 기본값 0? or 100?
        
        madness_list = db.fetch_all("SELECT madness_name FROM user_madness WHERE user_id = ?", (interaction.user.id,))
        madness_names = ", ".join([m[0] for m in madness_list]) if madness_list else "없음"

        # 임베드 생성
        embed = discord.Embed(title=f"📊 {stats['name']}님의 상태", color=0x3498db)
        
        embed.add_field(name="체력 (HP)", value=f"{stats['hp']}", inline=True)
        embed.add_field(name="정신력 (Sanity)", value=f"{stats['sanity']}%", inline=True)
        embed.add_field(name="허기 (Hunger)", value=f"{current_hunger}/50", inline=True)

        embed.add_field(
            name="감각 (Perception)", 
            value=f"**{current_perception}** (기본: {stats['perception']})", 
            inline=True
        )
        embed.add_field(
            name="지성 (Intelligence)", 
            value=f"**{current_intelligence}** (기본: {stats['intelligence']})", 
            inline=True
        )
        embed.add_field(
            name="의지 (Willpower)", 
            value=f"**{current_willpower}** (기본: {stats['willpower']})", 
            inline=True
        )
        
        embed.add_field(name="보유 광기", value=madness_names, inline=False)
        
        # 상태 메시지 추가
        status_msg = []
        if stats['sanity'] <= 0:
            status_msg.append("⚠️ **광기 상태**: 정신력이 바닥났습니다. 환각이 보일 수 있습니다.")
        elif stats['sanity'] < 50:
            status_msg.append("⚠️ **불안**: 정신적으로 불안정합니다. 스탯이 크게 감소했습니다.")
        
        if current_hunger <= 0:
            status_msg.append("⚠️ **굶주림**: 배가 너무 고파 쓰러지기 직전입니다.")
        elif current_hunger <= 10:
            status_msg.append("⚠️ **배고픔**: 배가 많이 고픕니다.")
        
        if status_msg:
            embed.add_field(name="상태 이상", value="\n".join(status_msg), inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="주사위", description="1부터 100까지의 주사위를 굴립니다.")
    async def dice(self, interaction: discord.Interaction, min_val: int = 1, max_val: int = 100):
        result = GameLogic.roll_dice(min_val, max_val)
        
        # ✅ 추가: 활성 조사 세션 확인
        inv_cog = self.bot.get_cog("Investigation")
        if inv_cog and interaction.user.id in inv_cog.active_investigations:
            active_data = inv_cog.active_investigations[interaction.user.id]
            
            # 같은 채널에서 굴린 주사위만 처리
            if active_data["channel_id"] == interaction.channel_id:
                await interaction.response.defer()  # ✅ 여기서 defer
                await inv_cog.process_investigation_dice(interaction, result)
                return
        
        embed = discord.Embed(title="🎲 주사위 굴림", color=0xf1c40f)
        embed.add_field(name="범위", value=f"{min_val} ~ {max_val}", inline=True)
        embed.add_field(name="결과", value=f"**{result}**", inline=True)
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Stats(bot))
