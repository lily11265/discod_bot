import os
import sys
import logging
import sqlite3

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import DatabaseManager

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_database_creation():
    print("\n=== Testing Database Creation ===")
    db_path = "test_game_data.db"
    
    if os.path.exists(db_path):
        os.remove(db_path)
        
    db = DatabaseManager(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    
    expected_tables = [
        'user_state', 'user_inventory', 'user_clues', 'user_madness', 
        'user_thoughts', 'world_triggers', 'world_state', 
        'investigation_counts', 'investigation_sessions', 
        'removed_items', 'blocked_locations'
    ]
    
    missing_tables = [t for t in expected_tables if t not in tables]
    
    if missing_tables:
        print(f"❌ Missing tables: {missing_tables}")
    else:
        print("✅ All tables created successfully.")
        
    conn.close()
    
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)

if __name__ == "__main__":
    test_database_creation()
