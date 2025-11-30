import logging
import sys
import os
import asyncio

# Configure logging
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, AsyncMock

# Mock classes
class MockInteraction:
    def __init__(self, user_id, channel_id):
        self.user = MagicMock()
        self.user.id = user_id
        self.channel_id = channel_id
        self.response = AsyncMock()
        self.followup = AsyncMock()

class MockBot:
    def __init__(self):
        self.cogs = {}
        self.loop = asyncio.get_event_loop()
    
    def get_cog(self, name):
        return self.cogs.get(name)
    
    def add_cog(self, cog):
        self.cogs[cog.__class__.__name__] = cog
        
    def get_user(self, user_id):
        user = MagicMock()
        user.send = AsyncMock()
        return user

# Mock DB
class MockDB:
    def execute_query(self, query, params):
        print(f"DB Exec: {query} | Params: {params}")
    
    def fetch_one(self, query, params):
        if "user_inventory" in query:
            return None # Item not found
        return None

# Mock Sheets
class MockSheets:
    def get_user_stats(self, discord_id):
        return {
            "name": "TestUser",
            "hp": 100,
            "sanity": 100,
            "perception": 60,
            "intelligence": 50,
            "willpower": 50
        }
    
    def get_item_data(self, item_name):
        return {"name": item_name, "type": "item"}
    
    def get_madness_data(self, madness_id=None):
        return [{"madness_id": "madness_1", "name": "Test Madness", "description": "Test", "effect_type": "sanity", "effect_value": -10, "recovery_difficulty": 50}]

async def test_dice_listener():
    print("\n=== Testing Dice Listener & Effects ===")
    
    # Setup
    bot = MockBot()
    
    # Survival Cog (for DB)
    survival_cog = MagicMock()
    survival_cog.db = MockDB()
    survival_cog.trigger_madness_check = AsyncMock()
    bot.cogs["Survival"] = survival_cog
    
    # Investigation Cog
    from cogs.investigation import Investigation
    inv_cog = Investigation(bot)
    inv_cog.sheets = MockSheets()
    
    # Mock Active Investigation
    user_id = 12345
    channel_id = 999
    inv_cog.active_investigations[user_id] = {
        "state": "waiting_for_dice",
        "item_data": {"name": "수상한 상자", "type": "investigation"},
        "variant": {
            "result_success": "상자를 열었다. [item+old_key,clue+secret_note]",
            "result_fail": "상자가 잠겨있다."
        },
        "channel_id": channel_id
    }
    
    # Simulate Dice Roll (Success)
    interaction = MockInteraction(user_id, channel_id)
    dice_result = 50 # Target is ~60 (Perception) -> Success
    
    print("--- Simulating Dice Roll (50) ---")
    await inv_cog.process_investigation_dice(interaction, dice_result)
    
    # Verify
    # Check if DB queries were executed (printed)
    # Check if followup was sent
    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    embed = kwargs['embed']
    print(f"Embed Title: {embed.title}")
    print(f"Embed Desc: {embed.description}")
    
    # Simulate Effect Parsing
    print("\n--- Testing Effect Parsing ---")
    effect_str = "clue+test_clue, item+apple, 체력-10, 정신력-5"
    results = await inv_cog.apply_effects(user_id, effect_str)
    for r in results:
        print(r)
        
    # Check Madness Trigger
    # Since sanity changed by -5, trigger_madness_check should be called
    survival_cog.trigger_madness_check.assert_called_with(user_id)
    print("✅ Madness Check Triggered")

    # Simulate Fear Effect
    print("\n--- Testing Fear Effect ---")
    fear_effect = "공포-20"
    results = await inv_cog.apply_effects(user_id, fear_effect)
    for r in results:
        print(r)
    
    # Verify Fear Damage
    # Should calculate damage based on Willpower and Perception
    # Mock stats: Willpower 50 (default), Perception 60
    # Base 20 -> Willpower reduction -> Perception amplification
    
    print("\n✅ Simulation Complete")

if __name__ == "__main__":
    asyncio.run(test_dice_listener())
