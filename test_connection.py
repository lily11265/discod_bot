import os
from dotenv import load_dotenv
from sheets_manager import SheetsManager

load_dotenv()

def test_connection():
    creds = os.getenv('GOOGLE_CREDENTIALS_PATH')
    sheet_a = os.getenv('SPREADSHEET_A_ID')
    sheet_b = os.getenv('SPREADSHEET_B_ID')

    if not creds or not os.path.exists(creds):
        print("Error: GOOGLE_CREDENTIALS_PATH not found or file missing.")
        return

    print("Attempting to connect to Google Sheets...")
    try:
        sm = SheetsManager(creds, sheet_a, sheet_b)
        print("Successfully connected to Google API.")
        
        print(f"Accessing Spreadsheet A ({sheet_a})...")
        ws_a = sm.sheet_a.worksheet("메타데이터시트")
        print(f"Spreadsheet A '메타데이터시트' accessed. Title: {sm.sheet_a.title}")

        print(f"Accessing Spreadsheet B ({sheet_b})...")
        ws_b = sm.sheet_b.worksheet("인벤토리")
        print(f"Spreadsheet B '인벤토리' accessed. Title: {sm.sheet_b.title}")

        print("\nConnection Test Passed!")
        
    except Exception as e:
        print(f"\nConnection Test Failed: {e}")

if __name__ == "__main__":
    test_connection()
