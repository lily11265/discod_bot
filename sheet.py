import unittest
import asyncio
import logging
import sys
import os
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

# 로그 설정을 파일로 리다이렉트하기 위한 준비
TEST_RESULT_FILE = "test_results.txt"

# --- 모의 객체 (Mocks) 설정 ---

class MockUser:
    def __init__(self, user_id, name="TestUser"):
        self.id = user_id
        self.display_name = name
        self.mention = f"<@{user_id}>"
    
    async def send(self, content=None, embed=None):
        pass 
    
    async def edit(self, nick=None):
        pass

class MockGuild:
    def __init__(self):
        self.members = {}
        self.categories = []
        self.channels = []
    
    def get_member(self, user_id):
        return self.members.get(user_id)
        
    def get_channel(self, channel_id):
        for ch in self.channels:
            if ch.id == channel_id: return ch
        return None

class MockChannel:
    def __init__(self, channel_id, name="general"):
        self.id = channel_id
        self.name = name
        self.mention = f"<#{channel_id}>"
        
    async def send(self, content=None, embed=None, view=None):
        return MagicMock() # Return a mock message

class MockInteraction:
    def __init__(self, user_id, channel_id=123):
        self.user = MockUser(user_id)
        self.guild = MockGuild()
        self.channel_id = channel_id
        self.channel = MockChannel(channel_id)
        self.guild.channels.append(self.channel)
        
        self.response = MagicMock()
        self.followup = MagicMock()
        self.namespace = MagicMock()

class MockBot:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.guilds = [MockGuild()]
        self.cogs = {}
        self.loop = asyncio.get_event_loop()
        self.investigation_data = {}
    
    def get_cog(self, name):
        return self.cogs.get(name)
    
    def get_user(self, user_id):
        return MockUser(user_id)
    
    def get_guild(self, guild_id):
        return self.guilds[0]
        
    def get_channel(self, channel_id):
        return self.guilds[0].get_channel(channel_id)
    
    async def wait_until_ready(self):
        return True

# --- 가짜 시트 매니저 (데이터 제공용) ---
class FakeSheetsManager:
    def __init__(self):
        # "조사시스템_작성가이드.xlsx"의 내용을 반영한 모의 데이터
        self.cached_data = {
            'stats': [
                {'name': 'TestUser', 'hp': 100, 'sanity': 80, 'perception': 50, 'intelligence': 50, 'willpower': 50},
                {'name': 'HighSenseUser', 'hp': 100, 'sanity': 80, 'perception': 80, 'intelligence': 50, 'willpower': 50}, # 감각 높음
                {'name': 'StarvingUser', 'hp': 50, 'sanity': 40, 'perception': 30, 'intelligence': 30, 'willpower': 30}
            ],
            'items': [
                {'name': 'Bread', 'type': '음식', 'hunger_recovery': 10, 'description': '맛있는 빵'},
                {'name': 'Potion', 'type': '의약품', 'hp_recovery': 20, 'description': '체력 회복약'},
                {'name': 'Flashlight', 'type': '기타', 'description': '손전등'},
                {'name': 'Key', 'type': '기타', 'description': '열쇠'},
                
                # [Sheet 6. 조건체크순서] '책상' 예시 구현
                # 우선순위 테스트를 위해 variants 순서가 중요함 (가이드는 위에서부터 체크한다고 명시)
                {'name': 'Desk', 'type': 'investigation', 'variants': [
                    {'condition': 'count:>1,stat:감각:60', 'description': '[1순위] 세 번째로 살펴보니 숨겨진 서랍이 보인다!', 'result_success': '성공'},
                    {'condition': 'count:>0,stat:감각:60', 'description': '[2순위] 자세히 보니 책상 밑에서 혈흔이 보인다.', 'result_success': '성공'},
                    {'condition': 'count:>0', 'description': '[3순위] 이미 조사한 책상이다.', 'result_success': '성공'},
                    {'condition': 'stat:감각:60', 'description': '[4순위] 미세한 흠집과 혈흔의 패턴이 보인다.', 'result_success': '성공'},
                    {'condition': 'stat:감각:40', 'description': '[5순위] 서랍이 반쯤 열려있다.', 'result_success': '성공'},
                    {'condition': '', 'description': '[6순위] 낡은 나무 책상이다.', 'result_success': '성공'} # 기본
                ]},

                # [Sheet 5. 실전예시-회관] '전원스위치' 예시 구현 (복합 결과 테스트)
                {'name': 'Switch', 'type': 'investigation', 'variants': [
                    # 조건: 전원 켜짐 -> 끄기
                    {'condition': 'trigger:power_on', 'description': '전원을 끈다.', 
                     'result_success': 'trigger-power_on,묘사:전원을 껐다. 어두워졌다.'},
                    
                    # 조건: 전원 꺼짐 -> 켜기 (대실패 시 페널티)
                    {'condition': '', 'description': '스위치를 올린다.', 
                     'result_success': 'trigger+power_on,묘사:끼익... 전원이 켜졌다.',
                     'result_fail': '체력-5,묘사:손을 다쳤다.',
                     'result_crit_fail': '체력-10,정신력-5,묘사:스위치가 터졌다!'}
                ]},

                # [Sheet 2. 조건작성법] 심화 조건 테스트용
                {'name': 'LockedDoor', 'type': 'investigation', 'variants': [
                    {'condition': 'block:door_jammed', 'description': '문이 꽉 끼어있다.', 'result_success': '실패'},
                    {'condition': 'item:Key|Lockpick', 'description': '도구로 문을 연다.', 'result_success': '성공'}, # OR 조건
                    {'condition': '', 'description': '잠겨있다.', 'result_success': '실패'}
                ]}
            ],
            # 조사 지역 데이터 구조
            'investigation': {
                'VillageHall': {
                    'id': 'VillageHall', 'name': 'VillageHall', 'type': 'category', 'children': {
                        'Office': {
                            'id': 'VillageHall_Office', 'name': 'Office', 'type': 'location', 'description': '사무실이다.',
                            'items': [
                                {'name': 'Desk', 'button_text': '책상 조사', 'type': 'investigation'},
                                {'name': 'Switch', 'button_text': '스위치 조작', 'type': 'investigation'},
                                {'name': 'LockedDoor', 'button_text': '문 열기', 'type': 'investigation'}
                            ], 'children': {}
                        }
                    }
                }
            },
            'metadata': {'1001': 'TestUser', '1002': 'StarvingUser', '1004': 'HighSenseUser'}
        }
    
    def get_user_stats(self, discord_id=None, nickname=None):
        name = self.cached_data['metadata'].get(str(discord_id))
        if name:
            for stat in self.cached_data['stats']:
                if stat['name'] == name:
                    return stat.copy()
        return None

    async def get_user_stats_async(self, discord_id=None, nickname=None):
        return self.get_user_stats(discord_id, nickname)
        
    async def get_item_data_async(self, item_name):
        for item in self.cached_data['items']:
            if item['name'] == item_name:
                return item
        return None
    
    def fetch_investigation_data(self):
        return self.cached_data['investigation']

    def parse_nickname(self, nickname):
        return nickname.split('/')[0].strip()

    async def sync_sheet_inventory_to_db_async(self, db): return {}
    async def sync_db_inventory_to_sheet_async(self, db): pass
    def update_warehouse_item(self, item, type, count): return True, "Success"
    async def get_metadata_map_async(self): return self.cached_data['metadata']

# --- 테스트 케이스 ---

class RPGSystemTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 1. DB 초기화 (메모리 DB)
        from utils.database import DatabaseManager
        self.db = DatabaseManager(":memory:")
        await self.db.initialize()
        
        # 2. 봇 및 Cogs 초기화
        self.bot = MockBot(self.db)
        
        # 3. SheetsManager 패치
        self.sheets_patcher = patch('utils.sheets.SheetsManager', side_effect=FakeSheetsManager)
        self.MockSheetsClass = self.sheets_patcher.start()
        
        # 4. Cogs 로드
        from cogs.survival import Survival
        from cogs.inventory import Inventory
        from cogs.investigation import Investigation
        
        patch('discord.ext.tasks.Loop.start', new=MagicMock()).start()
        
        self.survival = Survival(self.bot)
        self.inventory = Inventory(self.bot)
        self.investigation = Investigation(self.bot)
        
        self.bot.cogs['Survival'] = self.survival
        self.bot.cogs['Inventory'] = self.inventory
        self.bot.cogs['Investigation'] = self.investigation

        # 5. 테스트 유저 데이터 삽입
        # TestUser (1001): 모든 스탯 50
        await self.db.execute_query("INSERT INTO user_state (user_id, current_hp, current_sanity, current_hunger) VALUES (?, ?, ?, ?)", (1001, 100, 80, 50))
        # HighSenseUser (1004): 감각 80
        await self.db.execute_query("INSERT INTO user_state (user_id, current_hp, current_sanity, current_hunger) VALUES (?, ?, ?, ?)", (1004, 100, 80, 50))

    async def asyncTearDown(self):
        await self.db.close()
        self.sheets_patcher.stop()

    async def test_01_game_logic_formulas(self):
        """[게임로직] 스탯 계산 및 목표값 공식 검증"""
        from utils.game_logic import GameLogic
        print("\n--- [Test 01] Game Logic Formulas ---")
        target = GameLogic.calculate_target_value(50)
        self.assertEqual(target, 44, f"Target for 50 should be 44, got {target}")
        current = GameLogic.calculate_current_stat(100, 0.5)
        self.assertEqual(current, 85, f"Current stat for base 100 at 50% sanity should be 85, got {current}")
        penalty_stat = GameLogic.calculate_hunger_penalty(100, 1)
        self.assertEqual(penalty_stat, 95, "Hunger penalty day 1 should be -5%")

    async def test_08_investigation_priority(self):
        """[조사] Sheet 6. 조건 체크 순서 및 우선순위 검증 (책상 시나리오)"""
        from utils.condition_parser import ConditionParser
        print("\n--- [Test 08] Investigation Priority Check (Desk Scenario) ---")
        
        # 1. 감각 높은 유저 (HighSenseUser, 1004)
        user_id = 1004
        user_state = {'stats': {'감각': 80}}
        world_state = {'interaction_counts': {'Desk': 0}} # 첫 조사
        
        # 'Desk' 아이템 데이터 가져오기
        item_data = await self.bot.get_cog("Investigation").sheets.get_item_data_async('Desk')
        
        # 우선순위 로직 시뮬레이션 (Investigation.create_interaction_callback 내부 로직)
        selected_variant = None
        for variant in item_data['variants']:
            # Mocking world_state for 'count' check
            # ConditionParser.evaluate_all needs to handle 'count' correctly.
            # We assume world_state has 'interaction_counts' and 'current_item_id' set appropriately or passed explicitly.
            # In ConditionParser.check_condition code (uploaded), it uses world_state.get('interaction_counts', {})
            # So we need to ensure world_state is passed correctly.
            
            # Temporary setup for ConditionParser check
            world_state['current_item_id'] = 'Desk'
            
            # Parse conditions
            conditions = ConditionParser.parse_condition_string(variant['condition'])
            check = ConditionParser.evaluate_all(conditions, user_state, world_state)
            
            if check['visible'] and check['enabled']:
                selected_variant = variant
                break
        
        # 첫 조사(0회) + 감각 80 -> [4순위] "미세한 흠집..." (조건: stat:감각:60)
        # 상위 1, 2순위는 count 조건 불만족, 3순위 count 불만족.
        print(f"HighSense First Check: {selected_variant['description']}")
        self.assertIn("미세한 흠집", selected_variant['description'])

        # 2. 재조사 (2회차) + 감각 80
        world_state['interaction_counts']['Desk'] = 2 
        
        selected_variant_2 = None
        for variant in item_data['variants']:
            world_state['current_item_id'] = 'Desk'
            conditions = ConditionParser.parse_condition_string(variant['condition'])
            check = ConditionParser.evaluate_all(conditions, user_state, world_state)
            if check['visible'] and check['enabled']:
                selected_variant_2 = variant
                break
        
        # 재조사(2회) + 감각 80 -> [1순위] "숨겨진 서랍..." (조건: count:>1, stat:감각:60)
        print(f"HighSense Re-check: {selected_variant_2['description']}")
        self.assertIn("숨겨진 서랍", selected_variant_2['description'])

        # 3. 일반 유저 (TestUser, 1001) - 감각 50
        user_id_normal = 1001
        user_state_normal = {'stats': {'감각': 50}}
        world_state['interaction_counts']['Desk'] = 0
        
        selected_variant_3 = None
        for variant in item_data['variants']:
            world_state['current_item_id'] = 'Desk'
            conditions = ConditionParser.parse_condition_string(variant['condition'])
            check = ConditionParser.evaluate_all(conditions, user_state_normal, world_state)
            if check['visible'] and check['enabled']:
                selected_variant_3 = variant
                break
        
        # 첫 조사 + 감각 50 -> [5순위] "서랍이 반쯤..." (조건: stat:감각:40)
        # 1~4순위 모두 불만족.
        print(f"Normal User Check: {selected_variant_3['description']}")
        self.assertIn("서랍이 반쯤", selected_variant_3['description'])

    async def test_09_investigation_complex_results(self):
        """[조사] Sheet 4 & 5. 복합 결과 적용 및 파싱 (전원스위치 시나리오)"""
        print("\n--- [Test 09] Complex Result Parsing & Application ---")
        
        user_id = 1001
        item_data = await self.bot.get_cog("Investigation").sheets.get_item_data_async('Switch')
        
        # 시나리오: 전원 켜기 실패 (대실패) -> 체력, 정신력 감소 및 묘사 확인
        # variants[1] : 조건 없음 (켜기 시도)
        target_variant = item_data['variants'][1]
        
        self.investigation.active_investigations[user_id] = {
            "state": "waiting_for_dice",
            "item_data": item_data,
            "variant": target_variant,
            "channel_id": 123
        }
        
        interaction = MockInteraction(user_id, channel_id=123)
        
        # 대실패 주사위 (5) -> result_crit_fail: "체력-10,정신력-5,묘사:스위치가 터졌다!"
        await self.investigation.process_investigation_dice(interaction, dice_result=5)
        
        # DB 확인: 체력 10 감소, 정신력 5 감소
        state = await self.db.fetch_one("SELECT current_hp, current_sanity FROM user_state WHERE user_id = ?", (user_id,))
        print(f"Result State: HP {state[0]}, Sanity {state[1]}")
        
        self.assertEqual(state[0], 90, "HP should be 90 (100 - 10)")
        self.assertEqual(state[1], 75, "Sanity should be 75 (80 - 5)")

        # 시나리오: 전원 켜기 성공
        # 성공 시: "trigger+power_on,묘사:끼익... 전원이 켜졌다."
        await self.investigation.process_investigation_dice(interaction, dice_result=95)
        
        # 트리거 확인
        trigger = await self.db.fetch_one("SELECT active FROM world_triggers WHERE trigger_id = ?", ('power_on',))
        self.assertIsNotNone(trigger, "Trigger 'power_on' should be active")
        self.assertEqual(trigger[0], 1)

    async def test_10_advanced_conditions(self):
        """[조사] Sheet 2. 심화 조건 (OR 조건, Block 조건) 검증"""
        from utils.condition_parser import ConditionParser
        print("\n--- [Test 10] Advanced Conditions (Item OR, Block) ---")
        
        # 1. OR 조건 (item:Key|Lockpick)
        # 유저가 'Key'만 가지고 있음
        user_state_key = {'inventory': ['Key']}
        world_state = {'triggers': []}
        
        cond_or = {'type': 'item', 'value': 'Key|Lockpick', 'options': [], 'negated': False}
        result = ConditionParser.check_condition(cond_or, user_state_key, world_state)
        print(f"OR Condition Check (Has Key): {result}")
        self.assertTrue(result, "Should be True if user has one of the items")
        
        # 2. Block 조건 (block:door_jammed)
        # door_jammed 트리거가 있음 -> 조건 만족 여부 확인
        # ConditionParser.check_condition 로직 상:
        # block 타입은 '트리거가 존재하면' True를 반환하지만, 
        # evaluate_all 에서 "True면 차단(숨김/비활성)" 처리하거나,
        # check_condition 내부에서 "존재하면 False(불만족)"으로 처리하는지 확인 필요.
        # 업로드된 condition_parser.py 코드를 보면:
        # result = value in world_state.get('triggers', [])
        # result = not result (트리거가 있으면 result는 False가 됨)
        # 즉, "조건을 만족했는가?" = "트리거가 없는가?"
        
        world_state_blocked = {'triggers': ['door_jammed']}
        cond_block = {'type': 'block', 'value': 'door_jammed', 'options': [], 'negated': False}
        
        result_blocked = ConditionParser.check_condition(cond_block, {}, world_state_blocked)
        print(f"Block Condition Check (Trigger exists): {result_blocked}")
        self.assertFalse(result_blocked, "Should be False (Blocked) if trigger exists")
        
        world_state_clear = {'triggers': []}
        result_clear = ConditionParser.check_condition(cond_block, {}, world_state_clear)
        print(f"Block Condition Check (Trigger missing): {result_clear}")
        self.assertTrue(result_clear, "Should be True (Pass) if trigger is missing")

if __name__ == '__main__':
    with open(TEST_RESULT_FILE, "w", encoding="utf-8") as f:
        runner = unittest.TextTestRunner(stream=f, verbosity=2)
        suite = unittest.TestLoader().loadTestsFromTestCase(RPGSystemTest)
        result = runner.run(suite)
        
    print(f"테스트 완료. 결과가 {TEST_RESULT_FILE}에 저장되었습니다.")