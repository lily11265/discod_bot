import os
import sys
import logging
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sheets import SheetsManager
import config

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('test_init')

def test_sheet_initialization():
    print("\n=== Testing Sheet Initialization ===")
    
    if not config.SPREADSHEET_ID_A or not config.SPREADSHEET_ID_D:
        print("❌ SPREADSHEET_ID_A or SPREADSHEET_ID_D not set in .env")
        return

    sheets = SheetsManager()
    if not sheets.client:
        print("❌ Failed to connect to Google Sheets")
        return

    print("Initializing worksheets...")
    sheets.initialize_worksheets()
    print("✅ Initialization called (Check logs for details)")

if __name__ == "__main__":
    test_sheet_initialization()
