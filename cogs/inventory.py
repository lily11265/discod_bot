import discord
from discord import app_commands
from discord.ext import commands
from utils.sheets import SheetsManager
import logging
import asyncio
from typing import Literal

from discord.ext import tasks

logger = logging.getLogger('cogs.inventory')

class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sheets = SheetsManager()
        self.db = self.bot.db_manager
        self.inventory_sync_task.start()

    def cog_unload(self):
        self.inventory_sync_task.cancel()

    async def cog_load(self):
        # 봇 시작 시 시트 -> DB 동기화
        logger.info("Starting initial inventory sync (Sheet -> DB)...")
        await self.sheets.sync_sheet_inventory_to_db_async(self.db)

    @tasks.loop(minutes=1.0)
    async def inventory_sync_task(self):
        """1분마다 DB 인벤토리를 시트로 동기화"""
        logger.debug("Running periodic inventory sync (DB -> Sheet)...")
        await self.sheets.sync_db_inventory_to_sheet_async(self.db)

    @inventory_sync_task.before_loop
    async def before_inventory_sync(self):
        await self.bot.wait_until_ready()

    # 1. 창고 (Warehouse)
    @app_commands.command(name="창고", description="창고에 아이템을 보관하거나 불출합니다.")
    @app_commands.describe(
        action="수행할 작업 (보관/불출)",
        item="아이템 이름",
        count="수량 (기본: 1)"
    )
    async def warehouse(self, interaction: discord.Interaction, action: Literal["보관", "불출"], item: str, count: int = 1):
        """
        창고 관리 커맨드
        - 보관: 인벤토리 -> 창고
        - 불출: 창고 -> 인벤토리
        """
        await interaction.response.defer(ephemeral=True)
        
        if count <= 0:
            await interaction.followup.send("수량은 1개 이상이어야 합니다.", ephemeral=True)
            return

        user_id = interaction.user.id
        
        # 아이템 데이터 확인 (유형 파악용)
        item_data = await self.sheets.get_item_data_async(item)
        item_type = item_data['type'] if item_data else "이외 아이템"

        if action == "보관":
            # 1. 유저 인벤토리 확인
            user_item = await self.db.fetch_one("SELECT count FROM user_inventory WHERE user_id = ? AND item_name = ?", (user_id, item))
            if not user_item or user_item[0] < count:
                await interaction.followup.send("인벤토리에 아이템이 부족합니다.", ephemeral=True)
                return
            
            # 2. 시트 업데이트 (창고 추가)
            # update_warehouse_item은 동기 함수이므로 to_thread 사용
            success, msg = await asyncio.to_thread(self.sheets.update_warehouse_item, item, item_type, count)
            
            if not success:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
                return

            # 3. DB 업데이트 (유저 인벤토리 차감)
            await self.db.execute_query("UPDATE user_inventory SET count = count - ? WHERE user_id = ? AND item_name = ?", (count, user_id, item))
            await self.db.execute_query("DELETE FROM user_inventory WHERE user_id = ? AND count <= 0", (user_id,))
            
            # 4. DB 창고 테이블 업데이트 (싱크용)
            await self.db.execute_query(
                "INSERT INTO warehouse (item_name, item_type, count) VALUES (?, ?, ?) ON CONFLICT(item_name) DO UPDATE SET count = count + ?",
                (item, item_type, count, count)
            )
            
            await interaction.followup.send(f"✅ {item} {count}개를 창고에 보관했습니다.", ephemeral=True)

        elif action == "불출":
            # 1. 시트 업데이트 (창고 제거)
            # update_warehouse_item에 음수 count를 전달하여 불출 처리
            success, msg = await asyncio.to_thread(self.sheets.update_warehouse_item, item, item_type, -count)
            
            if not success:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
                return

            # 2. DB 업데이트 (유저 인벤토리 추가)
            await self.db.execute_query(
                "INSERT INTO user_inventory (user_id, item_name, count) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET count = count + ?",
                (user_id, item, count, count)
            )
            
            # 3. DB 창고 테이블 업데이트 (싱크용)
            await self.db.execute_query("UPDATE warehouse SET count = count - ? WHERE item_name = ?", (count, item))
            await self.db.execute_query("DELETE FROM warehouse WHERE count <= 0", ())
            
            await interaction.followup.send(f"✅ {item} {count}개를 창고에서 불출했습니다.", ephemeral=True)

    # 2. 거래 (Trade)
    @app_commands.command(name="거래", description="다른 유저에게 아이템을 주거나 (관리자) 생성하여 지급합니다.")
    @app_commands.describe(
        target_user="받을 유저",
        item="아이템 이름",
        count="수량 (기본: 1)"
    )
    async def trade(self, interaction: discord.Interaction, target_user: discord.User, item: str, count: int = 1):
        """
        아이템 거래/지급 커맨드
        - 일반 유저: 자신의 인벤토리에서 차감하여 상대에게 지급
        - 관리자: 아이템 데이터에 존재하면 생성하여 지급 (인벤토리 차감 X)
        """
        await interaction.response.defer(ephemeral=True)
        
        if count <= 0:
            await interaction.followup.send("수량은 1개 이상이어야 합니다.", ephemeral=True)
            return

        sender_id = interaction.user.id
        receiver_id = target_user.id
        
        # 관리자 여부 확인
        is_admin = await asyncio.to_thread(self.sheets.get_admin_permission, sender_id)
        
        if is_admin:
            # 관리자: 아이템 생성 지급
            # 1. 아이템 데이터 존재 확인
            item_data = await self.sheets.get_item_data_async(item)
            if not item_data:
                await interaction.followup.send(f"❌ '{item}'은(는) 존재하지 않는 아이템입니다. 아이템 데이터 시트를 확인해주세요.", ephemeral=True)
                return
            
            # 2. 지급 처리 (DB 추가)
            await self.db.execute_query(
                "INSERT INTO user_inventory (user_id, item_name, count) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET count = count + ?",
                (receiver_id, item, count, count)
            )
            
            await interaction.followup.send(f"✅ [관리자] {target_user.display_name}님에게 {item} {count}개를 지급했습니다.", ephemeral=True)
            
        else:
            # 일반 유저: 거래
            # 1. 보내는 사람 인벤토리 확인
            sender_item = await self.db.fetch_one("SELECT count FROM user_inventory WHERE user_id = ? AND item_name = ?", (sender_id, item))
            if not sender_item or sender_item[0] < count:
                await interaction.followup.send("❌ 인벤토리에 아이템이 부족합니다.", ephemeral=True)
                return
            
            # 2. 트랜잭션 처리
            # 보내는 사람 차감
            await self.db.execute_query("UPDATE user_inventory SET count = count - ? WHERE user_id = ? AND item_name = ?", (count, sender_id, item))
            await self.db.execute_query("DELETE FROM user_inventory WHERE user_id = ? AND count <= 0", (sender_id,))
            
            # 받는 사람 추가
            await self.db.execute_query(
                "INSERT INTO user_inventory (user_id, item_name, count) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET count = count + ?",
                (receiver_id, item, count, count)
            )
            
            await interaction.followup.send(f"✅ {target_user.display_name}님에게 {item} {count}개를 보냈습니다.", ephemeral=True)

    # Autocompletes
    @warehouse.autocomplete('item')
    async def warehouse_item_autocomplete(self, interaction: discord.Interaction, current: str):
        action = interaction.namespace.action
        if action == "보관":
            # 인벤토리 아이템 자동완성
            user_id = interaction.user.id
            items = await self.db.fetch_all("SELECT item_name FROM user_inventory WHERE user_id = ?", (user_id,))
            return [
                app_commands.Choice(name=i[0], value=i[0])
                for i in items if current.lower() in i[0].lower()
            ][:25]
        else:
            # 창고 아이템 자동완성 (DB 기준)
            items = await self.db.fetch_all("SELECT item_name, count FROM warehouse")
            return [
                app_commands.Choice(name=f"{i[0]} ({i[1]}개)", value=i[0])
                for i in items if current.lower() in i[0].lower()
            ][:25]

    @trade.autocomplete('item')
    async def trade_item_autocomplete(self, interaction: discord.Interaction, current: str):
        is_admin = await asyncio.to_thread(self.sheets.get_admin_permission, interaction.user.id)
        
        if is_admin:
            # 관리자는 모든 아이템 (캐시된 아이템 데이터 기준)
            cached_items = self.sheets.cached_data.get('items', [])
            return [
                app_commands.Choice(name=i['name'], value=i['name'])
                for i in cached_items if current.lower() in i['name'].lower()
            ][:25]
        else:
            # 일반 유저는 본인 인벤토리
            user_id = interaction.user.id
            items = await self.db.fetch_all("SELECT item_name FROM user_inventory WHERE user_id = ?", (user_id,))
            return [
                app_commands.Choice(name=i[0], value=i[0])
                for i in items if current.lower() in i[0].lower()
            ][:25]

async def setup(bot):
    await bot.add_cog(Inventory(bot))
