import asyncio
import logging
from utils.sheets import SheetsManager
import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('debug_sheets')

async def main():
    print("Initializing SheetsManager...")
    sm = SheetsManager()
    
    print("\n--- Testing Metadata (Sheet B) ---")
    metadata = await sm.get_metadata_map_async()
    print(f"Metadata Count: {len(metadata)}")
    print(f"Sample Metadata: {list(metadata.items())[:5]}")
    
    print("\n--- Testing Stats (Sheet A) ---")
    stats = await sm.fetch_all_stats_async()
    print(f"Stats Count: {len(stats)}")
    if stats:
        print(f"Sample Stat: {stats[0]}")
        
    print("\n--- Testing Inventory (Sheet A) ---")
    # read_hunger_stats_from_sheet reads Inventory sheet
    inventory_data = await asyncio.to_thread(sm.read_hunger_stats_from_sheet)
    print(f"Inventory Rows Read: {len(inventory_data)}")
    if inventory_data:
        print(f"Sample Inventory Data: {inventory_data[0]}")

    print("\n--- Testing Item Data (Sheet B) ---")
    item = await sm.get_item_data_async("빵") # Assuming "빵" exists
    print(f"Item '빵': {item}")

if __name__ == "__main__":
    asyncio.run(main())
