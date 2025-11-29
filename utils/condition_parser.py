import re

class ConditionParser:
    """
    조사 시스템의 복잡한 조건(Column I)을 파싱하고 평가하는 클래스입니다.
    """

    @staticmethod
    def parse_condition_string(condition_string):
        """
        조건 문자열을 파싱하여 구조화된 딕셔너리 리스트로 반환합니다.
        예: "trigger:power_on,item:key [visible]"
        """
        if not condition_string:
            return []

        conditions = []
        # 쉼표로 구분된 각 조건 처리 (단, 대괄호 [] 안의 쉼표는 무시해야 함 - 정규식 필요)
        # 간단하게 쉼표로 나누고, 옵션 파싱은 별도로 진행
        raw_conditions = [c.strip() for c in condition_string.split(',')]
        
        for raw in raw_conditions:
            if not raw: continue
            
            # 옵션 파싱 ([visible], [hidden] 등)
            options = []
            option_match = re.search(r'\[(.*?)\]', raw)
            if option_match:
                options = [o.strip() for o in option_match.group(1).split(':')] # reset:daily 같은 경우 처리
                raw = raw.replace(option_match.group(0), '').strip()
            
            # 타입과 값 파싱 (type:value)
            parts = raw.split(':', 1)
            cond_type = parts[0].strip()
            cond_value = parts[1].strip() if len(parts) > 1 else ""
            
            # 부정 조건 처리 (!trigger:...)
            is_negated = False
            if cond_type.startswith('!'):
                cond_type = cond_type[1:]
                is_negated = True
            
            conditions.append({
                "type": cond_type,
                "value": cond_value,
                "options": options,
                "negated": is_negated,
                "raw": raw # 디버깅용
            })
            
        return conditions

    @staticmethod
    def check_condition(condition, user_state, world_state):
        """
        단일 조건을 평가합니다.
        user_state: {stats, inventory, sanity, hp, ...}
        world_state: {triggers, time, pollution, location, ...}
        """
        cond_type = condition['type']
        value = condition['value']
        options = condition['options']
        negated = condition['negated']
        
        result = False
        
        if cond_type == 'trigger':
            # 트리거 확인
            result = value in world_state.get('triggers', [])
            
        elif cond_type == 'block':
            # 차단 트리거 (있으면 False)
            result = value in world_state.get('triggers', [])
            # block은 존재하면 "접근 불가"이므로, result가 True면 조건 불만족(False)이어야 함.
            # 하지만 여기서는 "조건이 참인가?"만 판단하고, 상위 로직에서 block 처리.
            # 통상적으로 block 조건은 "이 트리거가 없어야 한다"로 해석됨.
            result = not result 
            
        elif cond_type == 'item':
            # 아이템 확인 (OR 조건 지원: item:A|B)
            required_items = [i.strip() for i in value.split('|')]
            user_items = user_state.get('inventory', [])
            # 하나라도 있으면 True
            result = any(item in user_items for item in required_items)
            
        elif cond_type == 'stat':
            # 스탯 확인 (stat:감각:40 또는 stat:의지:30-70)
            stat_name, req_val = value.split(':', 1)
            user_stat = user_state.get('stats', {}).get(stat_name, 0)
            
            if '-' in req_val:
                min_val, max_val = map(int, req_val.split('-'))
                result = min_val <= user_stat <= max_val
            else:
                result = user_stat >= int(req_val)
                
        elif cond_type == 'time':
            # 시간 확인 (time:22:00-06:00)
            # 현재 시간은 world_state['time'] (HH:MM 형식 문자열 가정)
            current_time = world_state.get('time', "00:00")
            start, end = value.split('-')
            
            # 시간 비교 로직 (자정 넘가는 경우 포함)
            if start <= end:
                result = start <= current_time <= end
            else:
                result = start <= current_time or current_time <= end
                
        elif cond_type == 'infection':
            # 오염도 확인 (infection:<30, infection:>50, infection:20-40)
            current_inf = user_state.get('pollution', 0)
            if value.startswith('<'):
                result = current_inf < int(value[1:])
            elif value.startswith('>'):
                result = current_inf > int(value[1:])
            elif '-' in value:
                min_v, max_v = map(int, value.split('-'))
                result = min_v <= current_inf <= max_v
            else:
                result = current_inf == int(value)
                
        elif cond_type == 'location':
            # 위치 확인
            current_loc = world_state.get('location_id', "")
            target_locs = [l.strip() for l in value.split('|')]
            result = any(loc in current_loc for loc in target_locs) # 부분 일치 허용? ID 정확 일치 권장
            
        elif cond_type == 'member':
            # 인원 확인 (member:1-3)
            current_members = len(world_state.get('members', []))
            min_m, max_m = map(int, value.split('-'))
            result = min_m <= current_members <= max_m
            
        elif cond_type == 'count':
            # 횟수 제한 확인 (count:>1, count:0 등)
            # world_state['interaction_counts'] = { 'unique_id': count }
            # unique_id는 현재 평가 중인 아이템의 ID여야 함.
            # world_state에 'current_item_id'가 있다고 가정.
            target_id = world_state.get('current_item_id')
            if not target_id:
                # ID가 없으면 카운트 체크 불가 -> False (안전하게)
                # 혹은 0으로 간주? 0으로 간주하는게 나을듯.
                current_count = 0
            else:
                counts = world_state.get('interaction_counts', {})
                current_count = counts.get(target_id, 0)
            
            if value.startswith('<'):
                result = current_count < int(value[1:])
            elif value.startswith('>'):
                result = current_count > int(value[1:])
            elif '-' in value:
                min_v, max_v = map(int, value.split('-'))
                result = min_v <= current_count <= max_v
            else:
                result = current_count == int(value) 
            
        elif cond_type == 'cost':
            # 비용 확인 (cost:허기:10)
            res_name, amount = value.split(':')
            current_res = user_state.get(res_name, 0) # 허기, 체력, 정신력 등
            result = current_res >= int(amount)
            
        elif cond_type == 'language' or cond_type == 'skill':
            # 언어/스킬 확인
            # user_state['skills'] 리스트 가정
            result = value in user_state.get('skills', [])
            
        elif cond_type == 'forced':
            # 강제 발동은 조건 체크에서는 항상 True (트리거 시점의 문제)
            result = True

        # 부정 조건 처리
        if negated:
            result = not result
            
        return result

    @staticmethod
    def evaluate_all(conditions, user_state, world_state):
        """
        모든 조건을 평가하고 최종 가시성(visible)과 활성화(enabled) 상태를 반환합니다.
        반환: { "visible": bool, "enabled": bool, "reason": str }
        """
        is_visible = True
        is_enabled = True
        reasons = []

        for cond in conditions:
            # block 조건은 최우선 체크 (만족하면 차단됨)
            if cond['type'] == 'block':
                # block 조건이 True(차단 트리거 존재)면 숨김/비활성 처리
                # block 조건의 check_condition은 "트리거가 없으면 True"로 구현함.
                # 따라서 False면 차단된 것.
                if not ConditionParser.check_condition(cond, user_state, world_state):
                    is_visible = False # block은 보통 아예 막힘
                    is_enabled = False
                    reasons.append(f"차단됨: {cond['value']}")
                    break

            # 일반 조건 평가
            passed = ConditionParser.check_condition(cond, user_state, world_state)
            
            # 옵션 확인
            opts = cond['options']
            force_visible = 'visible' in opts
            force_hidden = 'hidden' in opts
            
            if not passed:
                if force_visible:
                    # 조건 불만족 시 숨김
                    is_visible = False
                else:
                    # 조건 불만족 시 비활성화 (보이긴 함)
                    is_enabled = False
                    reasons.append(f"조건 미달: {cond['raw']}")
            
            if force_hidden and passed:
                # hidden 옵션은 조건 만족 시 숨김 (역설적이지만 "찾으면 사라짐" 같은 기믹)
                is_visible = False

        return {
            "visible": is_visible,
            "enabled": is_enabled,
            "reason": ", ".join(reasons)
        }
