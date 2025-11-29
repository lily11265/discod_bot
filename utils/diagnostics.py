import random
from utils.game_logic import GameLogic
import logging

logger = logging.getLogger('diagnostics')

class SelfDiagnostics:
    def __init__(self, sheets_manager):
        self.sheets = sheets_manager

    def run_all_tests(self):
        """
        모든 진단 테스트를 실행하고 리포트를 반환합니다.
        """
        report = {
            "logic_stress": self.test_logic_stress(),
            "data_integrity": self.test_data_integrity(),
            "edge_cases": self.test_edge_cases()
        }
        return report

    def test_logic_stress(self, iterations=1000):
        """
        게임 로직 스트레스 테스트
        - 1000번의 주사위 굴림 및 판정 시뮬레이션
        """
        results = {"success": 0, "failure": 0, "critical_success": 0, "critical_failure": 0}
        errors = []

        try:
            for _ in range(iterations):
                stat = random.randint(10, 100)
                target = GameLogic.calculate_target_value(stat)
                dice = GameLogic.roll_dice()
                result = GameLogic.check_result(dice, target)
                
                if result == "SUCCESS": results["success"] += 1
                elif result == "FAILURE": results["failure"] += 1
                elif result == "CRITICAL_SUCCESS": results["critical_success"] += 1
                elif result == "CRITICAL_FAILURE": results["critical_failure"] += 1
                else: errors.append(f"Unknown result: {result}")
                
            return {
                "status": "PASS" if not errors else "FAIL",
                "details": f"{iterations}회 시뮬레이션 완료. 성공률: {round((results['success']+results['critical_success'])/iterations*100, 1)}%",
                "errors": errors
            }
        except Exception as e:
            return {"status": "ERROR", "details": str(e), "errors": [str(e)]}

    def test_data_integrity(self):
        """
        데이터 무결성 검사
        - 조사 데이터의 트리 구조 연결 확인
        """
        data = self.sheets.cached_data.get('investigation', {})
        if not data:
            return {"status": "WARN", "details": "조사 데이터가 비어있습니다.", "errors": []}

        errors = []
        checked_nodes = 0
        
        def check_node(node, path):
            nonlocal checked_nodes
            checked_nodes += 1
            
            # 필수 필드 확인
            if "id" not in node: errors.append(f"Missing ID at {path}")
            if "name" not in node: errors.append(f"Missing Name at {path}")
            
            # 자식 노드 재귀 확인
            if "children" in node:
                for child_name, child_node in node["children"].items():
                    check_node(child_node, f"{path} > {child_name}")

        try:
            for loc_name, loc_node in data.items():
                check_node(loc_node, loc_name)
                
            return {
                "status": "PASS" if not errors else "FAIL",
                "details": f"{checked_nodes}개 노드 검사 완료.",
                "errors": errors[:5] # 처음 5개만 표시
            }
        except Exception as e:
            return {"status": "ERROR", "details": str(e), "errors": [str(e)]}

    def test_edge_cases(self):
        """
        엣지 케이스 테스트
        - 정신력 0일 때 스탯 계산
        - 스탯 10/100일 때 목표값
        """
        errors = []
        
        # 1. 정신력 0 테스트
        stat_sanity_0 = GameLogic.calculate_current_stat(100, 0.0)
        if stat_sanity_0 != 70: # 100 * 0.7
            errors.append(f"Sanity 0% Calc Fail: Expected 70, Got {stat_sanity_0}")

        # 2. 스탯 최소/최대 테스트
        target_min = GameLogic.calculate_target_value(10) # 50 - (-30 * 0.6) = 68
        if target_min != 68:
            errors.append(f"Min Stat Target Fail: Expected 68, Got {target_min}")
            
        target_max = GameLogic.calculate_target_value(100) # 50 - (60 * 0.6) = 14
        if target_max != 14:
            errors.append(f"Max Stat Target Fail: Expected 14, Got {target_max}")

        return {
            "status": "PASS" if not errors else "FAIL",
            "details": "주요 엣지 케이스 검증 완료",
            "errors": errors
        }
