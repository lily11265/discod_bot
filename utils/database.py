import aiosqlite
import logging
import datetime
import json
import os

logger = logging.getLogger('utils.database')

class DatabaseManager:
    def __init__(self, db_path="game_data.db"):
        self.db_path = db_path
        self.pool = None

    async def initialize(self):
        """봇 시작 시 호출: DB 연결 생성 및 테이블 초기화"""
        try:
            self.pool = await aiosqlite.connect(self.db_path)
            # Row Factory 설정 (딕셔너리처럼 접근 가능하게 하려면 aiosqlite.Row 사용 가능하나, 기존 코드 호환성을 위해 기본 튜플 유지)
            # self.pool.row_factory = aiosqlite.Row 
            await self.create_tables()
            logger.info("DB Connection established.")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    async def close(self):
        """봇 종료 시 호출"""
        if self.pool:
            await self.pool.close()
            logger.info("DB Connection closed.")

    async def create_tables(self):
        """데이터베이스 테이블 초기화"""
        # 1. 유저 상태 (user_state)
        await self.execute_query('''
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
        await self.execute_query('''
        CREATE TABLE IF NOT EXISTS user_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id TEXT,
            item_name TEXT,
            count INTEGER DEFAULT 1,
            acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, item_name)
        )
        ''') # UNIQUE 제약조건 수정: item_id -> item_name (기존 코드 로직 반영)

        # 3. 단서 (user_clues)
        await self.execute_query('''
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
        await self.execute_query('''
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
        await self.execute_query('''
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
        await self.execute_query('''
        CREATE TABLE IF NOT EXISTS world_triggers (
            trigger_id TEXT PRIMARY KEY,
            active BOOLEAN DEFAULT 0,
            activated_by INTEGER,
            activated_at TIMESTAMP
        )
        ''')

        # 7. 월드 상태 (world_state)
        await self.execute_query('''
        CREATE TABLE IF NOT EXISTS world_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 8. 차단 지역 (blocked_locations)
        await self.execute_query('''
        CREATE TABLE IF NOT EXISTS blocked_locations (
            location_id TEXT PRIMARY KEY,
            blocked_by TEXT,
            blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 9. 조사 카운트 (investigation_counts)
        await self.execute_query('''
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
        await self.execute_query('''
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
        await self.execute_query('''
        CREATE TABLE IF NOT EXISTS removed_items (
            location_id TEXT,
            item_id TEXT,
            removed_by INTEGER,
            removed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(location_id, item_id)
        )
        ''')

        # 12. 창고 (warehouse)
        await self.execute_query('''
        CREATE TABLE IF NOT EXISTS warehouse (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT,
            item_type TEXT,
            count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(item_name)
        )
        ''')
        
        logger.info("Database tables initialized.")

    async def execute_query(self, query, params=()):
        """비동기 쿼리 실행 (INSERT, UPDATE, DELETE)"""
        if not self.pool:
            raise Exception("Database not initialized. Call initialize() first.")
            
        async with self.pool.cursor() as cursor:
            await cursor.execute(query, params)
            await self.pool.commit()
            return cursor.lastrowid

    async def executemany(self, query, params_list):
        """비동기 대량 쿼리 실행 (Batch Processing)"""
        if not self.pool:
            raise Exception("Database not initialized.")
            
        async with self.pool.cursor() as cursor:
            await cursor.executemany(query, params_list)
            await self.pool.commit()

    async def fetch_one(self, query, params=()):
        """비동기 단일 결과 조회"""
        if not self.pool:
            raise Exception("Database not initialized.")
            
        async with self.pool.execute(query, params) as cursor:
            return await cursor.fetchone()

    async def fetch_all(self, query, params=()):
        """비동기 다중 결과 조회"""
        if not self.pool:
            raise Exception("Database not initialized.")
            
        async with self.pool.execute(query, params) as cursor:
            return await cursor.fetchall()
