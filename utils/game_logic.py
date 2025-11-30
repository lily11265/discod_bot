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
        판정 결과 반환
        - 1-9: 대실패
        - 10-목표값 미만: 실패
        - 목표값-89: 성공
        - 90-100: 대성공
        """
        result = "FAILURE"
        if dice_value < 10:
            result = "CRITICAL_FAILURE" # 대실패
        elif dice_value >= 90:
            result = "CRITICAL_SUCCESS" # 대성공
        elif dice_value >= target_value:
            result = "SUCCESS" # 성공
        
        logger.debug(f"Check result (Dice: {dice_value}, Target: {target_value}): {result}")
        return result

    @staticmethod
    def calculate_sanity_damage(base_damage: int, current_perception: int) -> int:
        """
        감각에 따른 정신력 피해 증폭
        공식: 기본_피해 * (1 + 현재_감각 * 0.003)
        """
        damage = int(base_damage * (1 + current_perception * 0.003))
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
