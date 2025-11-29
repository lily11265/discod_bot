import sqlite3
import logging
import datetime
import json
import os

logger = logging.getLogger('utils.database')

class DatabaseManager:
    def __init__(self, db_path="game_data.db"):
        self.db_path = db_path
        self.initialize_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def initialize_db(self):
        """데이터베이스 테이블 초기화"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 1. 유저 상태 (user_state)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_state (
            user_id INTEGER PRIMARY KEY,
            current_hp INTEGER DEFAULT 100,
            current_sanity INTEGER DEFAULT 100,
            current_hunger INTEGER DEFAULT 100,
            infection INTEGER DEFAULT 0,
            last_hunger_update TIMESTAMP,
            last_sanity_recovery TIMESTAMP,
            hunger_zero_days INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 2. 인벤토리 (user_inventory)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id TEXT,
            item_name TEXT,
            count INTEGER DEFAULT 1,
            acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, item_id)
        )
        ''')

        # 3. 단서 (user_clues)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_clues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            clue_id TEXT,
            clue_name TEXT,
            acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, clue_id)
        )
        ''')

        # 4. 광기 (user_madness)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_madness (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            madness_id TEXT,
            madness_name TEXT,
            acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            recovery_attempted_at TIMESTAMP
        )
        ''')

        # 5. 사고 (user_thoughts)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_thoughts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            thought_id TEXT,
            thought_name TEXT,
            status TEXT, -- thinking, completed, equipped
            progress INTEGER DEFAULT 0,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
        ''')

        # 6. 월드 트리거 (world_triggers)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS world_triggers (
            trigger_id TEXT PRIMARY KEY,
            active BOOLEAN DEFAULT 0,
            activated_by INTEGER,
            activated_at TIMESTAMP
        )
        ''')

        # 7. 월드 상태 (world_state)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS world_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 8. 차단 지역 (blocked_locations)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocked_locations (
            location_id TEXT PRIMARY KEY,
            blocked_by TEXT,
            blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 9. 조사 카운트 (investigation_counts)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS investigation_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_unique_id TEXT,
            count INTEGER DEFAULT 0,
            last_investigated TIMESTAMP,
            reset_type TEXT, -- daily, never
            UNIQUE(user_id, item_unique_id)
        )
        ''')

        # 10. 조사 세션 (investigation_sessions)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS investigation_sessions (
            session_id TEXT PRIMARY KEY, -- Channel ID
            leader_id INTEGER,
            members TEXT, -- JSON Array
            location_id TEXT,
            state TEXT, -- scheduled, gathering, active, paused
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP
        )
        ''')

        # 11. 제거된 아이템 (removed_items)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS removed_items (
            location_id TEXT,
            item_id TEXT,
            removed_by INTEGER,
            removed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(location_id, item_id)
        )
        ''')

        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")

    def execute_query(self, query, params=()):
        """쿼리 실행 (INSERT, UPDATE, DELETE)"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            raise
        finally:
            conn.close()

    def fetch_one(self, query, params=()):
        """단일 결과 조회"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()
        finally:
            conn.close()

    def fetch_all(self, query, params=()):
        """다중 결과 조회"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            conn.close()
