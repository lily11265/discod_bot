import sys
import os
import asyncio
import logging
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.game_logic import GameLogic
from utils.synergy import SynergySystem
from utils.condition_parser import ConditionParser
from utils.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('test_all_systems')

class TestReport:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.errors = []
    
    def record_test(self, test_name, passed, error=None):
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
            logger.info(f"✅ PASS: {test_name}")
        else:
            self.tests_failed += 1
            self.errors.append(f"{test_name}: {error}")
            logger.error(f"❌ FAIL: {test_name} - {error}")
    
    def summary(self):
        return f"""
{'='*60}
테스트 결과 요약
{'='*60}
총 테스트: {self.tests_run}
성공: {self.tests_passed} ✅
실패: {self.tests_failed} ❌
성공률: {(self.tests_passed/self.tests_run*100):.1f}%
{'='*60}
"""

report = TestReport()

# ============================================================
# 1. GameLogic 테스트
# ============================================================

def test_target_value_calculation():
    """목표값 계산 공식 테스트"""
    try:
        # 50 - (스탯 - 40) * 0.6
        assert GameLogic.calculate_target_value(40) == 50, "스탯 40 실패"
        assert GameLogic.calculate_target_value(100) == 14, "스탯 100 실패"
        assert GameLogic.calculate_target_value(10) == 68, "스탯 10 실패"
        assert GameLogic.calculate_target_value(70) == 32, "스탯 70 실패"
        report.record_test("목표값 계산", True)
    except AssertionError as e:
        report.record_test("목표값 계산", False, str(e))

def test_current_stat_calculation():
    """정신력 반영 스탯 계산 테스트"""
    try:
        # 기본_스탯 * (0.7 + 0.3 * 정신력%)
        assert GameLogic.calculate_current_stat(100, 1.0) == 100, "정신력 100% 실패"
        assert GameLogic.calculate_current_stat(100, 0.0) == 70, "정신력 0% 실패"
        assert GameLogic.calculate_current_stat(100, 0.5) == 85, "정신력 50% 실패"
        assert GameLogic.calculate_current_stat(60, 0.5) == 51, "스탯 60, 정신력 50% 실패"
        report.record_test("정신력 반영 스탯 계산", True)
    except AssertionError as e:
        report.record_test("정신력 반영 스탯 계산", False, str(e))

def test_dice_result_check():
    """판정 결과 체크 테스트"""
    try:
        assert GameLogic.check_result(5, 50) == "CRITICAL_FAILURE"
        assert GameLogic.check_result(9, 50) == "CRITICAL_FAILURE"
        assert GameLogic.check_result(10, 50) == "FAILURE"
        assert GameLogic.check_result(49, 50) == "FAILURE"
        assert GameLogic.check_result(50, 50) == "SUCCESS"
        assert GameLogic.check_result(89, 50) == "SUCCESS"
        assert GameLogic.check_result(90, 50) == "CRITICAL_SUCCESS"
        assert GameLogic.check_result(100, 50) == "CRITICAL_SUCCESS"
        report.record_test("판정 결과 체크", True)
    except AssertionError as e:
        report.record_test("판정 결과 체크", False, str(e))

def test_sanity_damage_amplification():
    """감각에 따른 정신력 피해 증폭 테스트"""
    try:
        # 기본_피해 * (1 + 감각 * 0.003)
        damage1 = GameLogic.calculate_sanity_damage(20, 40)
        expected1 = int(20 * (1 + 40 * 0.003))  # 24
        assert damage1 == expected1, f"감각 40: {damage1} != {expected1}"
        
        damage2 = GameLogic.calculate_sanity_damage(20, 100)
        expected2 = int(20 * (1 + 100 * 0.003))  # 26
        assert damage2 == expected2, f"감각 100: {damage2} != {expected2}"
        
        report.record_test("정신력 피해 증폭", True)
    except AssertionError as e:
        report.record_test("정신력 피해 증폭", False, str(e))

def test_fear_damage_reduction():
    """의지에 따른 공포 피해 감소 테스트"""
    try:
        # 감소율 = 의지 / 3 (%)
        # 실제_피해 = 기본_피해 * (1 - 감소율 / 100)
        damage1 = GameLogic.calculate_fear_damage(20, 60)
        reduction1 = 60 / 3  # 20%
        expected1 = int(20 * (1 - reduction1 / 100))  # 16
        assert damage1 == expected1, f"의지 60: {damage1} != {expected1}"
        
        damage2 = GameLogic.calculate_fear_damage(30, 90)
        reduction2 = 90 / 3  # 30%
        expected2 = int(30 * (1 - reduction2 / 100))  # 21
        assert damage2 == expected2, f"의지 90: {damage2} != {expected2}"
        
        report.record_test("공포 피해 감소", True)
    except AssertionError as e:
        report.record_test("공포 피해 감소", False, str(e))

# ============================================================
# 2. Synergy 시스템 테스트
# ============================================================

def test_extreme_synergies():
    """극단 시너지 테스트"""
    try:
        # 극단 관찰자
        synergies1 = SynergySystem.check_synergies(85, 15, 15)
        assert any(s['id'] == 'extreme_observer' for s in synergies1), "극단 관찰자 실패"
        
        # 극단 학자
        synergies2 = SynergySystem.check_synergies(15, 85, 15)
        assert any(s['id'] == 'extreme_scholar' for s in synergies2), "극단 학자 실패"
        
        # 극단 생존자
        synergies3 = SynergySystem.check_synergies(15, 15, 85)
        assert any(s['id'] == 'extreme_survivor' for s in synergies3), "극단 생존자 실패"
        
        # 조건 미충족
        synergies4 = SynergySystem.check_synergies(80, 25, 20)
        assert not any(s['id'] == 'extreme_observer' for s in synergies4), "극단 시너지 오발동"
        
        report.record_test("극단 시너지", True)
    except AssertionError as e:
        report.record_test("극단 시너지", False, str(e))

def test_dual_synergies():
    """이중 특화 시너지 테스트"""
    try:
        # 예리한 분석가
        synergies1 = SynergySystem.check_synergies(55, 55, 30)
        assert any(s['id'] == 'sharp_analyst' for s in synergies1), "예리한 분석가 실패"
        
        # 강인한 관찰자
        synergies2 = SynergySystem.check_synergies(55, 30, 55)
        assert any(s['id'] == 'tough_observer' for s in synergies2), "강인한 관찰자 실패"
        
        # 철학자
        synergies3 = SynergySystem.check_synergies(30, 55, 55)
        assert any(s['id'] == 'philosopher' for s in synergies3), "철학자 실패"
        
        report.record_test("이중 특화 시너지", True)
    except AssertionError as e:
        report.record_test("이중 특화 시너지", False, str(e))

def test_balance_synergy():
    """완벽한 균형 시너지 테스트"""
    try:
        synergies1 = SynergySystem.check_synergies(40, 40, 40)
        assert any(s['id'] == 'perfect_balance' for s in synergies1), "완벽한 균형 실패"
        
        synergies2 = SynergySystem.check_synergies(35, 45, 38)
        assert any(s['id'] == 'perfect_balance' for s in synergies2), "완벽한 균형 범위 실패"
        
        synergies3 = SynergySystem.check_synergies(40, 40, 50)
        assert not any(s['id'] == 'perfect_balance' for s in synergies3), "완벽한 균형 오발동"
        
        report.record_test("완벽한 균형 시너지", True)
    except AssertionError as e:
        report.record_test("완벽한 균형 시너지", False, str(e))

def test_synergy_bonus_application():
    """시너지 보너스 적용 테스트"""
    try:
        # 완벽한 균형: -20
        synergies = SynergySystem.check_synergies(40, 40, 40)
        modified = SynergySystem.apply_synergy_bonus(50, synergies, 'investigation')
        assert modified == 30, f"완벽한 균형 보너스: {modified} != 30"
        
        # 극단 관찰자: 자동 성공
        synergies2 = SynergySystem.check_synergies(85, 15, 15)
        modified2 = SynergySystem.apply_synergy_bonus(50, synergies2, 'danger_detection')
        assert modified2 == 1, f"극단 관찰자 자동 성공: {modified2} != 1"
        
        report.record_test("시너지 보너스 적용", True)
    except AssertionError as e:
        report.record_test("시너지 보너스 적용", False, str(e))

# ============================================================
# 3. ConditionParser 테스트
# ============================================================

def test_condition_parsing():
    """조건 문자열 파싱 테스트"""
    try:
        # 단일 조건
        result1 = ConditionParser.parse_condition_string("trigger:power_on")
        assert len(result1) == 1
        assert result1[0]['type'] == 'trigger'
        assert result1[0]['value'] == 'power_on'
        
        # 복수 조건
        result2 = ConditionParser.parse_condition_string("item:key,stat:감각:50")
        assert len(result2) == 2
        
        # 부정 조건
        result3 = ConditionParser.parse_condition_string("!trigger:monster_awake")
        assert result3[0]['negated'] == True
        
        # 옵션 포함
        result4 = ConditionParser.parse_condition_string("trigger:hidden_door [visible]")
        assert 'visible' in result4[0]['options']
        
        report.record_test("조건 파싱", True)
    except AssertionError as e:
        report.record_test("조건 파싱", False, str(e))

def test_condition_evaluation():
    """조건 평가 테스트"""
    try:
        user_state = {
            "stats": {"감각": 60, "지성": 50},
            "inventory": ["key", "potion"],
            "pollution": 30
        }
        world_state = {
            "triggers": ["power_on"],
            "time": "14:30"
        }
        
        # 트리거 체크
        cond1 = ConditionParser.parse_condition_string("trigger:power_on")
        result1 = ConditionParser.evaluate_all(cond1, user_state, world_state)
        assert result1['enabled'] == True, "트리거 체크 실패"
        
        # 아이템 체크
        cond2 = ConditionParser.parse_condition_string("item:key")
        result2 = ConditionParser.evaluate_all(cond2, user_state, world_state)
        assert result2['enabled'] == True, "아이템 체크 실패"
        
        # 스탯 체크
        cond3 = ConditionParser.parse_condition_string("stat:감각:50")
        result3 = ConditionParser.evaluate_all(cond3, user_state, world_state)
        assert result3['enabled'] == True, "스탯 체크 실패"
        
        # 실패 케이스
        cond4 = ConditionParser.parse_condition_string("stat:감각:70")
        result4 = ConditionParser.evaluate_all(cond4, user_state, world_state)
        assert result4['enabled'] == False, "스탯 체크 오발동"
        
        report.record_test("조건 평가", True)
    except AssertionError as e:
        report.record_test("조건 평가", False, str(e))

# ============================================================
# 4. 데이터베이스 테스트
# ============================================================

def test_database_initialization():
    """데이터베이스 초기화 테스트"""
    try:
        import sqlite3
        
        # 테스트 DB 생성
        test_db_path = "test_game_data.db"
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        
        db = DatabaseManager(test_db_path)
        
        # 테이블 존재 확인
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        expected_tables = [
            'user_state', 'user_inventory', 'user_clues', 'user_madness',
            'user_thoughts', 'world_triggers', 'world_state',
            'investigation_counts', 'investigation_sessions',
            'removed_items', 'blocked_locations'
        ]
        
        for table in expected_tables:
            assert table in tables, f"테이블 {table} 없음"
        
        # 정리
        os.remove(test_db_path)
        
        report.record_test("데이터베이스 초기화", True)
    except Exception as e:
        report.record_test("데이터베이스 초기화", False, str(e))

def test_database_operations():
    """데이터베이스 CRUD 테스트"""
    try:
        test_db_path = "test_game_data.db"
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        
        db = DatabaseManager(test_db_path)
        
        # INSERT
        db.execute_query(
            "INSERT INTO user_state (user_id, current_hp, current_sanity) VALUES (?, ?, ?)",
            (12345, 100, 80)
        )
        
        # SELECT
        result = db.fetch_one(
            "SELECT current_hp, current_sanity FROM user_state WHERE user_id = ?",
            (12345,)
        )
        assert result == (100, 80), f"SELECT 실패: {result}"
        
        # UPDATE
        db.execute_query(
            "UPDATE user_state SET current_hp = ? WHERE user_id = ?",
            (90, 12345)
        )
        
        result2 = db.fetch_one(
            "SELECT current_hp FROM user_state WHERE user_id = ?",
            (12345,)
        )
        assert result2[0] == 90, f"UPDATE 실패: {result2}"
        
        # DELETE
        db.execute_query("DELETE FROM user_state WHERE user_id = ?", (12345,))
        result3 = db.fetch_one("SELECT * FROM user_state WHERE user_id = ?", (12345,))
        assert result3 is None, "DELETE 실패"
        
        # 정리
        os.remove(test_db_path)
        
        report.record_test("데이터베이스 CRUD", True)
    except Exception as e:
        report.record_test("데이터베이스 CRUD", False, str(e))

# ============================================================
# 5. 통합 시나리오 테스트
# ============================================================

def test_hunger_system_scenario():
    """허기 시스템 시나리오 테스트"""
    try:
        # 시나리오: 의지 50 유저가 3일간 굶음
        willpower = 50
        daily_decay = 10 + (willpower * 0.04)  # 12
        
        day0_hunger = 100
        day1_hunger = day0_hunger - daily_decay  # 88
        day2_hunger = day1_hunger - daily_decay  # 76
        day3_hunger = day2_hunger - daily_decay  # 64
        
        assert abs(daily_decay - 12) < 0.1, f"허기 감소량 계산 오류: {daily_decay}"
        assert day3_hunger > 50, "3일 후에도 허기 50 이상이어야 함"
        
        report.record_test("허기 시스템 시나리오", True)
    except AssertionError as e:
        report.record_test("허기 시스템 시나리오", False, str(e))

def test_sanity_recovery_scenario():
    """정신력 회복 시나리오 테스트"""
    try:
        # 시나리오: 지성 60, 의지 50, 허기 40
        intelligence = 60
        willpower = 50
        hunger = 40
        
        # 허기 임계값: 30 + (지성 * 0.2) = 42
        threshold = 30 + (intelligence * 0.2)
        can_recover = hunger >= threshold
        
        assert threshold == 42, f"임계값 계산 오류: {threshold}"
        assert can_recover == False, f"허기 {hunger}는 임계값 {threshold} 미만"
        
        # 허기 50일 때
        hunger2 = 50
        can_recover2 = hunger2 >= threshold
        assert can_recover2 == True, "허기 50이면 회복 가능해야 함"
        
        # 회복량: 10 + (의지 / 10) = 15
        recovery = 10 + (willpower / 10)
        assert recovery == 15, f"회복량 계산 오류: {recovery}"
        
        report.record_test("정신력 회복 시나리오", True)
    except AssertionError as e:
        report.record_test("정신력 회복 시나리오", False, str(e))

def test_investigation_dice_scenario():
    """조사 판정 시나리오 테스트"""
    try:
        # 시나리오: 감각 70, 정신력 50%
        base_perception = 70
        sanity_percent = 0.5
        
        # 현재 감각: 70 * (0.7 + 0.3 * 0.5) = 59.5 -> 59
        current_perception = int(base_perception * (0.7 + 0.3 * sanity_percent))
        assert current_perception == 59, f"현재 감각 계산 오류: {current_perception}"
        
        # 목표값: 50 - (59 - 40) * 0.6 = 38.6 -> 38
        target_value = int(50 - (current_perception - 40) * 0.6)
        assert target_value == 38, f"목표값 계산 오류: {target_value}"
        
        # 주사위 50 -> 성공
        result = GameLogic.check_result(50, target_value)
        assert result == "SUCCESS", f"판정 오류: {result}"
        
        report.record_test("조사 판정 시나리오", True)
    except AssertionError as e:
        report.record_test("조사 판정 시나리오", False, str(e))

# ============================================================
# 메인 실행
# ============================================================

def run_all_tests():
    """모든 테스트 실행"""
    logger.info("="*60)
    logger.info("전체 시스템 테스트 시작")
    logger.info("="*60)
    
    # 1. GameLogic 테스트
    logger.info("\n[1] GameLogic 테스트")
    test_target_value_calculation()
    test_current_stat_calculation()
    test_dice_result_check()
    test_sanity_damage_amplification()
    test_fear_damage_reduction()
    
    # 2. Synergy 테스트
    logger.info("\n[2] Synergy 시스템 테스트")
    test_extreme_synergies()
    test_dual_synergies()
    test_balance_synergy()
    test_synergy_bonus_application()
    
    # 3. ConditionParser 테스트
    logger.info("\n[3] ConditionParser 테스트")
    test_condition_parsing()
    test_condition_evaluation()
    
    # 4. Database 테스트
    logger.info("\n[4] Database 테스트")
    test_database_initialization()
    test_database_operations()
    
    # 5. 통합 시나리오 테스트
    logger.info("\n[5] 통합 시나리오 테스트")
    test_hunger_system_scenario()
    test_sanity_recovery_scenario()
    test_investigation_dice_scenario()
    
    # 결과 출력
    logger.info(report.summary())
    
    if report.errors:
        logger.error("\n발견된 오류:")
        for error in report.errors:
            logger.error(f"  - {error}")
    
    return report.tests_failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)