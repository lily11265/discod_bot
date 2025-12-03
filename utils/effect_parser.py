import re

class EffectParser:
    """
    조사 상호작용 결과(Effect)를 파싱하고 실행하는 클래스입니다.
    """

    @staticmethod
    def parse_effects(effect_string):
        """
        효과 문자열을 파싱하여 구조화된 리스트로 반환합니다.
        예: "trigger+power_on,체력-5,묘사:찰칵! 전원이 켜졌다."
        """
        if not effect_string:
            return [], ""

        effects = []
        description = ""

        # 1. 묘사(description) 분리
        # "묘사:" 키워드가 있으면 그 뒤는 모두 묘사 텍스트로 간주 (쉼표 포함 가능성 때문)
        if "묘사:" in effect_string:
            parts = effect_string.split("묘사:", 1)
            pre_desc = parts[0]
            description = parts[1].strip()
            
            # 앞부분(효과) 파싱
            tokens = [t.strip() for t in pre_desc.split(',')]
        else:
            # 묘사가 없는 경우 전체를 효과로 파싱
            tokens = [t.strip() for t in effect_string.split(',')]

        for token in tokens:
            if not token: continue

            # 효과 타입 파싱
            if token.startswith("clue+"):
                effects.append({"type": "clue_add", "value": token.split("+")[1].strip()})
            elif token.startswith("trigger+"):
                effects.append({"type": "trigger_add", "value": token.split("+")[1].strip()})
            elif token.startswith("trigger-"):
                effects.append({"type": "trigger_remove", "value": token.split("-")[1].strip()})
            elif token.startswith("item+"):
                effects.append({"type": "item_add", "value": token.split("+")[1].strip()})
            elif token.startswith("item-"):
                effects.append({"type": "item_remove", "value": token.split("-")[1].strip()})
            elif token.startswith("block+"):
                effects.append({"type": "block_add", "value": token.split("+")[1].strip()})
            elif token.startswith("spawn+"):
                effects.append({"type": "spawn", "value": token.split("+")[1].strip()})
            elif token.startswith("위치이동+"):
                effects.append({"type": "move", "value": token.split("+")[1].strip()})
            elif token.startswith("시간+"):
                effects.append({"type": "time_pass", "value": int(token.split("+")[1].strip())})
            
            # 스탯 증감 (체력+10, 체력-10, 체력-값 등)
            # 정규식으로 파싱: (스탯이름)(+|-)(값)
            stat_match = re.match(r"^(체력|정신력|허기|오염도|오염)([\+\-])(\d+)$", token)
            if stat_match:
                stat_name = stat_match.group(1)
                op = stat_match.group(2)
                val = int(stat_match.group(3))
                if op == '-': val = -val
                
                # 오염 -> 오염도 통일
                if stat_name == "오염": stat_name = "오염도"
                
                effects.append({"type": "stat_change", "stat": stat_name, "value": val})

        return effects, description
