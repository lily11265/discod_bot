# Discord Trading & Warehouse Bot

This bot manages a trading and warehouse system using Google Sheets.

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Environment**:
    - Rename `.env` (or create one) and fill in the following:
        - `DISCORD_TOKEN`: Your Discord Bot Token.
        - `SPREADSHEET_A_ID`: The ID of Spreadsheet A (Metadata & Item Data).
        - `SPREADSHEET_B_ID`: The ID of Spreadsheet B (Inventory & Shared Items).
        - `GOOGLE_CREDENTIALS_PATH`: Path to your Google Service Account JSON file (e.g., `service_account.json`).

3.  **Google Sheets Setup**:
    - Ensure the Service Account email has **Editor** access to both Spreadsheets.
    - Ensure the Sheet names match exactly:
        - Spreadsheet A: "메타데이터시트", "아이템데이터"
        - Spreadsheet B: "인벤토리", "공동아이템"

4.  **Run the Bot**:
    ```bash
    python bot.py
    ```

## Commands

- `/확인`: Check your status (HP, SP, Hunger, Inventory).
- `/보관 [item]`: Store an item in the shared warehouse.
- `/불출 [type] [item] [count]`: Withdraw an item from the warehouse.
- `/거래 [user] [item]`: Trade an item to another user.
- `/지급 [user] [type] [name] [desc]`: (Admin Only) Give an item to a user.

## Troubleshooting

- **"User not found"**: Ensure your Discord nickname matches the format in the "Inventory" sheet (e.g., `[Effect] Name | HP | SP`). The bot extracts the name part.
- **"Permission denied"**: Check if the bot has access to the Google Sheets.
