class SynergySystem:
    """스탯 시너지 효과 계산"""
    
    @staticmethod
    def check_synergies(perception: int, intelligence: int, willpower: int) -> list:
        """활성화된 시너지 목록 반환"""
        synergies = []
        
        # 극단 시너지 (80+)
        if perception >= 80 and intelligence <= 20 and willpower <= 20:
            synergies.append({
                'id': 'extreme_observer',
                'name': '극단 관찰자',
                'effect': 'danger_auto_success',
                'description': '위험 감지 자동 성공'
            })
        
        if intelligence >= 80 and perception <= 20 and willpower <= 20:
            synergies.append({
                'id': 'extreme_scholar',
                'name': '극단 학자',
                'effect': 'info_combo_auto_success',
                'description': '정보 조합 자동 성공'
            })
        
        if willpower >= 80 and perception <= 20 and intelligence <= 20:
            synergies.append({
                'id': 'extreme_survivor',
                'name': '극단 생존자',
                'effect': 'fear_immunity',
                'description': '공포 완전 면역'
            })
        
        # 이중 특화 시너지 (50+)
        if perception >= 50 and intelligence >= 50:
            synergies.append({
                'id': 'sharp_analyst',
                'name': '예리한 분석가',
                'effect': 'auto_combo_on_investigate',
                'description': '조사 성공 시 자동 정보 조합 시도'
            })
        
        if perception >= 50 and willpower >= 50:
            synergies.append({
                'id': 'tough_observer',
                'name': '강인한 관찰자',
                'effect': 'auto_dodge_on_danger',
                'description': '위험 감지 성공 시 함정 자동 회피'
            })
        
        if intelligence >= 50 and willpower >= 50:
            synergies.append({
                'id': 'philosopher',
                'name': '철학자',
                'effect': 'think_during_madness',
                'description': '광기 상태에서도 사고화 가능'
            })
        
        # 균형 시너지 (35-45)
        if all(35 <= stat <= 45 for stat in [perception, intelligence, willpower]):
            synergies.append({
                'id': 'perfect_balance',
                'name': '완벽한 균형',
                'effect': 'all_bonus_20',
                'description': '모든 판정 +20%, 모든 페널티 -20%'
            })
        
        return synergies
    
    @staticmethod
    def apply_synergy_bonus(base_target: int, synergies: list, context: str) -> int:
        """시너지 보너스를 적용한 목표값 반환"""
        modified_target = base_target
        
        for synergy in synergies:
            if synergy['effect'] == 'all_bonus_20':
                # 완벽한 균형: 성공률 +20% (목표값 -20)
                modified_target -= 20
            
            elif synergy['effect'] == 'danger_auto_success' and context == 'danger_detection':
                # 극단 관찰자: 위험 감지 자동 성공
                modified_target = 1  # 무조건 성공
        
        return modified_target
