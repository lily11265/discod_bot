import random
import logging

logger = logging.getLogger('utils.game_logic')

class GameLogic:
    @staticmethod
    def calculate_target_value(stat: int) -> int:
        """
        목표값 계산 공식: 50 - (스탯 - 40) * 0.6
        """
        target = int(50 - (stat - 40) * 0.6)
        logger.debug(f"Calculated target value for stat {stat}: {target}")
        return target

    @staticmethod
    def roll_dice(min_val: int = 1, max_val: int = 100) -> int:
        """
        주사위 굴림 (기본 1d100)
        """
        result = random.randint(min_val, max_val)
        logger.debug(f"Rolled dice ({min_val}-{max_val}): {result}")
        return result

    @staticmethod
    def calculate_current_stat(base_stat: int, sanity_percent: float) -> int:
        """
        정신력에 따른 현재 스탯 계산
        공식: 기본_스탯 * (0.7 + 0.3 * 정신력%)
        sanity_percent는 0.0 ~ 1.0 사이의 값 (예: 100% -> 1.0)
        """
        current = int(base_stat * (0.7 + 0.3 * sanity_percent))
        logger.debug(f"Calculated current stat (Base: {base_stat}, Sanity: {sanity_percent:.2f}): {current}")
        return current

    @staticmethod
    def check_result(dice_value: int, target_value: int) -> str:
            """
            명세서 기반 판정 결과 반환
            - M (대성공): 90 ~ 100
            - P (대실패): 1 ~ 9
            - N (성공): 목표값 이상 (그리고 대성공 아님)
            - O (실패): 목표값 미만 (그리고 대실패 아님)
            """
            if 90 <= dice_value <= 100:
                result = "CRITICAL_SUCCESS" # M열
            elif 1 <= dice_value <= 9:
                result = "CRITICAL_FAILURE" # P열
            elif dice_value >= target_value:
                result = "SUCCESS" # N열
            else:
                result = "FAILURE" # O열
            
            logger.debug(f"Check result (Dice: {dice_value}, Target: {target_value}): {result}")
            return result

    @staticmethod
    def calculate_sanity_damage(base_damage: int, current_perception: int) -> int:
        """
        감각에 따른 정신력 피해 증폭
        공식: 기본_피해 * (1 + 현재_감각 * 0.005)
        """
        damage = int(base_damage * (1 + current_perception * 0.005))
        logger.debug(f"Calculated sanity damage (Base: {base_damage}, Perception: {current_perception}): {damage}")
        return damage

    @staticmethod
    def calculate_fear_damage(base_damage: int, current_willpower: int) -> int:
        """
        의지에 따른 공포 피해 감소
        감소율 = 현재_의지 / 3 (%)
        실제_피해 = 기본_피해 * (1 - 공포_피해_감소율 / 100)
        """
        reduction_percent = current_willpower / 3
        damage = int(base_damage * (1 - reduction_percent / 100))
        logger.debug(f"Calculated fear damage (Base: {base_damage}, Willpower: {current_willpower}): {damage} (Reduction: {reduction_percent:.1f}%)")
        return damage

    @staticmethod
    def calculate_thinking_progress(base_progress: int, current_intelligence: int) -> int:
        """
        지성에 따른 사고화 진행도 증가
        공식: 기본_진행도 * (1 + 지성 / 100)
        """
        progress = int(base_progress * (1 + current_intelligence / 100))
        logger.debug(f"Calculated thinking progress (Base: {base_progress}, Intelligence: {current_intelligence}): {progress}")
        return progress

    @staticmethod
    def check_madness_resistance(current_intelligence: int) -> bool:
        """
        광기 저항 판정 (자동)
        목표값 = 50 - (현재_지성 - 40) * 0.6
        """
        target = GameLogic.calculate_target_value(current_intelligence)
        dice = GameLogic.roll_dice()
        result = dice >= target
        logger.debug(f"Madness resistance check (Int: {current_intelligence}, Target: {target}, Dice: {dice}): {result}")
        return result

    @staticmethod
    def check_danger_detection(current_perception: int) -> bool:
        """
        위험 감지 판정 (자동)
        목표값 = 50 - (현재_감각 - 40) * 0.6
        """
        target = GameLogic.calculate_target_value(current_perception)
        dice = GameLogic.roll_dice()
        result = dice >= target
        logger.debug(f"Danger detection check (Per: {current_perception}, Target: {target}, Dice: {dice}): {result}")
        return result

    @staticmethod
    def check_pollution_detection(current_perception: int) -> bool:
        """
        오염 판별 판정 (자동)
        목표값 = 50 - (현재_감각 - 40) * 0.6
        """
        target = GameLogic.calculate_target_value(current_perception)
        dice = GameLogic.roll_dice()
        result = dice >= target
        logger.debug(f"Pollution detection check (Per: {current_perception}, Target: {target}, Dice: {dice}): {result}")
        return result
    
    @staticmethod
    def check_incapacitated_evasion(current_willpower: int) -> bool:
        """
        행동불능 회피 판정
        확률 = 현재_의지 / 4 (%)
        """
        evasion_chance = current_willpower / 4
        dice = GameLogic.roll_dice()
        # 주사위 결과가 회피 확률보다 작거나 같으면 회피 성공 (낮을수록 좋은 판정인 경우 보통 이렇게 구현하지만, 
        # 여기서는 "확률"이므로 100면체 주사위에서 1~확률 값에 해당하면 성공으로 처리)
        result = dice <= evasion_chance
        logger.debug(f"Incapacitated evasion check (Will: {current_willpower}, Chance: {evasion_chance}%, Dice: {dice}): {result}")
        return result

    @staticmethod
    def calculate_hunger_penalty(stat_value: int, hunger_zero_days: int) -> int:
        """
        허기 0 지속 일수에 따른 스탯 페널티 계산
        - 0~2일: -5%
        - 3~6일: -10%
        - 7일 이상: 행동불능 (스탯 영향은 -10% 유지하거나 별도 처리, 여기서는 -10%로 계산)
        """
        penalty_percent = 0
        if hunger_zero_days >= 3:
            penalty_percent = 10
        elif hunger_zero_days >= 0: # 0일차부터 적용 (Case 2)
            penalty_percent = 5
            
        penalty = int(stat_value * (penalty_percent / 100))
        effective_stat = max(0, stat_value - penalty)
        
        logger.debug(f"Calculated hunger penalty (Stat: {stat_value}, Days: {hunger_zero_days}): {effective_stat} (Penalty: {penalty_percent}%)")
        return effective_stat

    @staticmethod
    def check_ritual_result(results: list[str], ritual_type: str) -> str:
        """
        의례 성공 여부 판정
        results: ["SUCCESS", "FAILURE", "CRITICAL_SUCCESS", "CRITICAL_FAILURE", ...]
        ritual_type: "1_person", "2_person", "3_person"
        """
        success_count = results.count("SUCCESS") + results.count("CRITICAL_SUCCESS")
        crit_success_count = results.count("CRITICAL_SUCCESS")
        crit_fail_count = results.count("CRITICAL_FAILURE")
        total = len(results)

        if ritual_type == "1_person":
            # 3개 판정 모두 성공해야 성공
            if success_count == 3:
                if crit_success_count == 3: return "CRITICAL_SUCCESS"
                return "SUCCESS"
            if crit_fail_count > 0: return "CRITICAL_FAILURE"
            return "FAILURE"

        elif ritual_type == "2_person":
            # 성공 조건: 한 명만 대성공~성공이고 다른 한 명은 대실패만 안하면 성공.
            # 둘 다 대성공일시 대성공.
            if total != 2: return "FAILURE"
            
            if crit_success_count == 2:
                return "CRITICAL_SUCCESS"
            
            # 한 명 성공(이상) + 다른 한 명 대실패 아님
            if success_count >= 1 and crit_fail_count == 0:
                return "SUCCESS"
            
            if crit_fail_count > 0:
                return "CRITICAL_FAILURE"
            
            return "FAILURE"

        elif ritual_type == "3_person":
            # 성공 조건: 두 명 이상이 성공일시 성공
            # 대성공 조건: 대성공이 2명 이상일시 대성공
            # 실패 조건: 대실패가 한 명이라도 있으면 실패
            # 대실패 조건: 대실패가 두 명 이상일시 대실패
            # 특수 케이스: 한 명이 대성공이고 다른 두 명이 각각 성공, 실패일 경우 성공으로 판단
            
            # 대실패 우선 체크 (2명 이상 -> 대실패)
            if crit_fail_count >= 2: return "CRITICAL_FAILURE"
            # 대실패 1명 -> 실패
            if crit_fail_count >= 1: return "FAILURE"
            
            # 대성공 체크 (2명 이상 -> 대성공)
            if crit_success_count >= 2: return "CRITICAL_SUCCESS"
            
            # 특수 케이스 (대성공1, 성공1, 실패1) -> 성공
            normal_success = success_count - crit_success_count
            fail_count = total - success_count
            
            if crit_success_count == 1 and normal_success == 1 and fail_count == 1:
                return "SUCCESS"
            
            # 일반 성공 체크 (2명 이상 성공)
            if success_count >= 2: return "SUCCESS"
            
            return "FAILURE"
            
        return "FAILURE"

    @staticmethod
    def resolve_combat_outcome(stat_type: str, result: str) -> dict:
        """
        전투 판정 결과에 따른 효과 반환
        """
        outcome = {
            "hp": 0,
            "sanity": 0,
            "hunger": 0,
            "pollution": 0,
            "info": None,
            "escape": False,
            "group_escape": False,
            "message": ""
        }
        
        if result not in ["SUCCESS", "CRITICAL_SUCCESS"]:
            outcome["message"] = "판정에 실패했습니다. 몬스터에게 압도당합니다."
            return outcome

        # 성공 시 효과
        if stat_type == "perception": # 감각
            outcome["sanity"] = -10
            outcome["hp"] = -5
            outcome["info"] = "monster_info"
            outcome["message"] = "몬스터를 관찰하여 정보를 얻었지만, 정신적 충격과 부상을 입었습니다."
            
        elif stat_type == "intelligence": # 지식
            outcome["pollution"] = 8
            outcome["sanity"] = -10
            outcome["hp"] = -8
            outcome["info"] = "gimmick_info"
            outcome["message"] = "몬스터의 기믹을 파악했지만, 오염되고 심각한 피해를 입었습니다."
            
        elif stat_type == "willpower": # 의지
            outcome["hunger"] = -10
            outcome["escape"] = True
            outcome["message"] = "필사적으로 도망쳤습니다! (허기 감소)"
            
            if result == "CRITICAL_SUCCESS":
                outcome["group_escape"] = True
                outcome["message"] = "놀라운 기지로 동료들을 이끌고 완벽하게 도망쳤습니다! (전원 피해 없음)"
            
        return outcome
