import discord
from discord import app_commands
from discord.ext import commands
from utils.sheets import SheetsManager
import logging

logger = logging.getLogger('cogs.inventory')

class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sheets = SheetsManager()

    # 5. 확인 (Check Status)
    @app_commands.command(name="확인", description="내 상태와 인벤토리를 확인합니다.")
    async def check_status(self, interaction: discord.Interaction):
        """
        유저 자신의 상태(HP, SP, 허기)와 인벤토리 아이템을 확인하는 커맨드입니다.
        """
        await interaction.response.defer(ephemeral=True)
        
        user_nickname = interaction.user.display_name
        user_data = self.sheets.get_user_info(user_nickname)
        
        if not user_data:
            await interaction.followup.send("데이터베이스에서 유저 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        embed = discord.Embed(title=f"{user_data['name']}님의 상태", color=discord.Color.blue())
        embed.add_field(name="체력", value=user_data['hp'], inline=True)
        embed.add_field(name="정신력", value=user_data['sp'], inline=True)
        embed.add_field(name="허기", value=user_data['hunger'], inline=True)
        
        items_str = ", ".join(user_data['items']) if user_data['items'] else "없음"
        embed.add_field(name="인벤토리", value=items_str, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    # 4. 지급 (Give - Admin Only)
    @app_commands.command(name="지급", description="[관리자 전용] 유저에게 아이템을 지급합니다.")
    @app_commands.describe(
        user="지급할 유저",
        type="아이템 유형",
        name="아이템 이름",
        description="아이템 설명 (선택)"
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="음식", value="음식"),
        app_commands.Choice(name="의약품", value="의약품"),
        app_commands.Choice(name="이외 아이템", value="이외 아이템")
    ])
    async def give_item(self, interaction: discord.Interaction, user: str, type: str, name: str, description: str = ""):
        """
        관리자가 유저에게 아이템을 생성하여 지급하는 커맨드입니다.
        """
        await interaction.response.defer(ephemeral=True)
        
        # 관리자 권한 확인
        if not self.sheets.get_admin_permission(interaction.user.id):
            await interaction.followup.send("권한이 없습니다.", ephemeral=True)
            return

        # 1. 아이템 메타데이터 등록
        self.sheets.register_item_metadata(name, type, description)
        
        # 2. 유저 인벤토리에 아이템 추가
        success, msg = self.sheets.add_item_to_user(user, name, 1)
        
        if success:
            await interaction.followup.send(f"{user}님에게 {name}을(를) 지급했습니다.", ephemeral=True)
        else:
            await interaction.followup.send(f"지급 실패: {msg}", ephemeral=True)

    @give_item.autocomplete('user')
    async def user_autocomplete(self, interaction: discord.Interaction, current: str):
        users = self.sheets.get_all_users()
        return [
            app_commands.Choice(name=user, value=user)
            for user in users if current.lower() in user.lower()
        ][:25]

    # 2.1.9.2 보관 (Store)
    @app_commands.command(name="보관", description="인벤토리의 아이템을 창고에 보관합니다.")
    async def store_item(self, interaction: discord.Interaction, item: str):
        """
        유저 인벤토리의 아이템을 공동 창고로 이동시키는 커맨드입니다.
        """
        await interaction.response.defer(ephemeral=True)
        
        user_nickname = interaction.user.display_name
        
        # 1. 유저 인벤토리에서 제거
        success, msg = self.sheets.remove_item_from_user(user_nickname, item, 1)
        if not success:
            await interaction.followup.send(f"보관 실패: {msg}", ephemeral=True)
            return
            
        # 2. 아이템 유형 확인
        item_type = self.sheets.get_item_type(item)
        
        # 3. 창고에 추가
        w_success, w_msg = self.sheets.update_warehouse_item(item, item_type, 1)
        
        if w_success:
            await interaction.followup.send(f"{item}을(를) 창고에 보관했습니다.", ephemeral=True)
        else:
            # 창고 추가 실패 시 유저에게 아이템 복구 시도
            self.sheets.add_item_to_user(user_nickname, item, 1)
            await interaction.followup.send(f"창고 보관 실패 (인벤토리로 복구됨): {w_msg}", ephemeral=True)

    @store_item.autocomplete('item')
    async def store_item_autocomplete(self, interaction: discord.Interaction, current: str):
        user_nickname = interaction.user.display_name
        user_data = self.sheets.get_user_info(user_nickname)
        if not user_data:
            return []
        
        items = user_data['items']
        unique_items = list(set(items))
        return [
            app_commands.Choice(name=item, value=item)
            for item in unique_items if current.lower() in item.lower()
        ][:25]

    # 2.1.9.1 불출 (Withdraw)
    @app_commands.command(name="불출", description="창고에서 아이템을 가져옵니다.")
    @app_commands.describe(
        type="아이템 유형",
        item="아이템 선택",
        count="수량"
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="음식", value="음식"),
        app_commands.Choice(name="의약품", value="의약품"),
        app_commands.Choice(name="이외 아이템", value="이외 아이템")
    ])
    async def withdraw_item(self, interaction: discord.Interaction, type: str, item: str, count: int):
        """
        창고에서 아이템을 꺼내 유저 인벤토리로 가져오는 커맨드입니다.
        """
        await interaction.response.defer(ephemeral=True)
        
        if count <= 0:
            await interaction.followup.send("수량은 1개 이상이어야 합니다.", ephemeral=True)
            return

        user_nickname = interaction.user.display_name
        
        # 1. 유저 인벤토리 공간 확인
        user_data = self.sheets.get_user_info(user_nickname)
        if not user_data:
            await interaction.followup.send("유저 정보를 찾을 수 없습니다.", ephemeral=True)
            return
            
        if len(user_data['items']) + count > user_data['max_slots']:
            await interaction.followup.send("인벤토리가 꽉 찼거나 공간이 부족합니다.", ephemeral=True)
            return

        # 2. 창고에서 아이템 제거
        w_success, w_msg = self.sheets.update_warehouse_item(item, type, -count)
        if not w_success:
            await interaction.followup.send(f"불출 실패: {w_msg}", ephemeral=True)
            return

        # 3. 유저 인벤토리에 추가
        u_success, u_msg = self.sheets.add_item_to_user(user_nickname, item, count)
        
        if u_success:
            await interaction.followup.send(f"{item} {count}개를 불출했습니다.", ephemeral=True)
        else:
            # 유저 추가 실패 시 창고로 복구
            self.sheets.update_warehouse_item(item, type, count)
            await interaction.followup.send(f"불출 처리 중 오류 발생 (창고 복구됨): {u_msg}", ephemeral=True)

    @withdraw_item.autocomplete('item')
    async def withdraw_item_autocomplete(self, interaction: discord.Interaction, current: str):
        type_value = interaction.namespace.type
        if not type_value:
            return []
            
        items_map = self.sheets.get_warehouse_items(type_value)
        
        choices = []
        for name, count in items_map.items():
            if current.lower() in name.lower():
                display_name = f"{name}: {count}개"
                choices.append(app_commands.Choice(name=display_name, value=name))
        
        return choices[:25]

    # 3. 거래 (Trade)
    @app_commands.command(name="거래", description="다른 유저 또는 관리자에게 아이템을 전달합니다.")
    @app_commands.describe(
        target_user="받을 유저",
        item="보낼 아이템"
    )
    async def trade_item(self, interaction: discord.Interaction, target_user: str, item: str):
        """
        자신의 아이템을 다른 유저에게 전달하는 커맨드입니다.
        """
        await interaction.response.defer(ephemeral=True)
        
        sender_nickname = interaction.user.display_name
        
        # 1. 보내는 사람 인벤토리에서 제거
        s_success, s_msg = self.sheets.remove_item_from_user(sender_nickname, item, 1)
        if not s_success:
            await interaction.followup.send(f"거래 실패: {s_msg}", ephemeral=True)
            return
            
        # 2. 받는 사람 인벤토리에 추가
        t_success, t_msg = self.sheets.add_item_to_user(target_user, item, 1)
        
        if t_success:
            await interaction.followup.send(f"{target_user}님에게 {item}을(를) 보냈습니다.", ephemeral=True)
        else:
            # 받는 사람 인벤토리 부족 등으로 실패 시 보낸 사람에게 복구
            self.sheets.add_item_to_user(sender_nickname, item, 1)
            await interaction.followup.send(f"거래 실패 (상대방 인벤토리 부족 등): {t_msg}", ephemeral=True)

    @trade_item.autocomplete('target_user')
    async def trade_target_autocomplete(self, interaction: discord.Interaction, current: str):
        users = self.sheets.get_all_users()
        return [
            app_commands.Choice(name=user, value=user)
            for user in users if current.lower() in user.lower()
        ][:25]

    @trade_item.autocomplete('item')
    async def trade_item_autocomplete(self, interaction: discord.Interaction, current: str):
        user_nickname = interaction.user.display_name
        user_data = self.sheets.get_user_info(user_nickname)
        if not user_data:
            return []
        unique_items = list(set(user_data['items']))
        return [
            app_commands.Choice(name=item, value=item)
            for item in unique_items if current.lower() in item.lower()
        ][:25]

async def setup(bot):
    await bot.add_cog(Inventory(bot))
