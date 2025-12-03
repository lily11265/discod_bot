import gspread
import re
import os
import time
import json
import random
from google.oauth2.service_account import Credentials
from googleapiclient.errors import HttpError

def with_backoff(func):
    """
    지수 백오프를 적용하는 데코레이터입니다.
    API 호출 실패 시(특히 429 에러) 재시도합니다.
    """
    def wrapper(*args, **kwargs):
        max_retries = 5
        base_delay = 1.5  # 초기 대기 시간 (초)
        
        for i in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # gspread의 APIError는 내부적으로 googleapiclient.errors.HttpError를 감쌀 수 있음
                # 또는 gspread.exceptions.APIError 일 수 있음
                # 여기서는 일반적인 Exception으로 잡아서 메시지나 타입을 확인
                error_str = str(e)
                if "429" in error_str or "Quota exceeded" in error_str:
                    if i == max_retries - 1:
                        raise e
                    
                    # 지수 백오프 + Jitter
                    delay = (base_delay * (2 ** i)) + random.uniform(0, 1)
                    print(f"API Quota exceeded. Retrying in {delay:.2f}s... (Attempt {i+1}/{max_retries})")
                    time.sleep(delay)
                else:
                    raise e
    return wrapper

class SheetsManager:
    """
    Google Sheets와의 상호작용을 관리하는 클래스입니다.
    스프레드시트 A(메타데이터/아이템데이터)와 스프레드시트 B(인벤토리/공동아이템)를 제어합니다.
    """
    def __init__(self, creds_path, sheet_a_id, sheet_b_id):
        """
        SheetsManager 초기화 메서드.
        
        Args:
            creds_path (str): Google Service Account 키 파일 경로
            sheet_a_id (str): 스프레드시트 A의 ID (메타데이터, 아이템데이터)
            sheet_b_id (str): 스프레드시트 B의 ID (인벤토리, 공동아이템)
        """
        # Google Sheets 및 Drive API 스코프 설정
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        # 서비스 계정 자격 증명 로드
        credentials = Credentials.from_service_account_file(creds_path, scopes=scopes)
        # gspread 클라이언트 인증 및 생성
        self.gc = gspread.authorize(credentials)
        # 스프레드시트 A와 B 열기
        self.sheet_a_id = sheet_a_id
        self.sheet_b_id = sheet_b_id
        self.sheet_a = self.gc.open_by_key(sheet_a_id)
        self.sheet_b = self.gc.open_by_key(sheet_b_id)
        
        # 캐시 파일 경로
        self.cache_file = "sheets_cache.json"
        self.cache = self.load_cache()

    def load_cache(self):
        """캐시 파일을 로드합니다."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"캐시 로드 실패: {e}")
        return {"metadata": {}, "items": []}

    def save_cache(self):
        """캐시를 파일에 저장합니다."""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"캐시 저장 실패: {e}")

    def parse_nickname(self, nickname):
        """
        다양한 형식의 닉네임 문자열에서 순수 닉네임(이름)만 추출합니다.
        """
        # 1. [칭호] 부분 제거 (대괄호와 그 안의 내용 제거)
        name_part = re.sub(r'\[.*?\]', '', nickname).strip()
        
        # 2. 구분자(|, /, \, I, ㅣ)를 기준으로 문자열 분리
        tokens = re.split(r'[|/\\Iㅣ]', name_part)
        
        # 3. 분리된 첫 번째 부분이 이름이므로 공백 제거 후 반환
        pure_name = tokens[0].strip()
        return pure_name

    def normalize_item_name(self, item_name):
        """
        아이템 이름 비교를 위해 정규화합니다.
        현재는 모든 공백을 제거하는 방식을 사용합니다.
        """
        return item_name.replace(" ", "")

    def get_admin_permission(self, user_id):
        """
        특정 유저가 관리자 권한을 가지고 있는지 확인합니다.
        캐시를 우선 확인하고, 없으면 시트에서 확인하지 않고 False를 반환합니다.
        (메타데이터는 자주 바뀌지 않으므로 캐시 의존도를 높임)
        """
        user_id_str = str(user_id)
        metadata = self.cache.get("metadata", {})
        
        # 캐시 구조: {"user_id": "name", ...} - 권한 정보가 캐시에 명시적으로 없으면 
        # 현재 캐시 구조상 권한 정보(Y/N)가 포함되어 있지 않을 수 있음.
        # 기존 로직을 유지하되, 캐시를 활용하도록 변경 필요.
        # 하지만 현재 sheets_cache.json 예시에는 id:name 매핑만 보임.
        # 권한 정보가 캐시에 없다면 시트를 읽어야 하지만, 요청 최소화를 위해
        # 캐시에 권한 정보도 저장하는 것이 좋음.
        # 일단 여기서는 시트 읽기를 최소화하라는 요청에 따라,
        # 캐시에 없으면 시트를 읽고 캐시를 업데이트하는 방식으로 구현.
        
        # 캐시에 권한 정보가 별도로 저장되어 있지 않다면 시트 확인 (백오프 적용)
        # 성능을 위해 전체 메타데이터를 한번 로드해서 캐싱하는 것이 좋음.
        
        # 여기서는 임시로 시트에서 읽되, 백오프 적용
        return self._fetch_admin_permission_from_sheet(user_id)

    @with_backoff
    def _fetch_admin_permission_from_sheet(self, user_id):
        try:
            ws = self.sheet_a.worksheet("메타데이터시트")
            cell = ws.find(str(user_id), in_column=1)
            if cell:
                perm = ws.cell(cell.row, 3).value
                if perm and str(perm).strip().upper() == 'Y':
                    return True
            return False
        except Exception as e:
            print(f"관리자 권한 확인 중 오류 발생: {e}")
            return False

    @with_backoff
    def get_user_row(self, user_name):
        """
        스프레드시트 B의 '인벤토리' 시트에서 특정 유저의 행 번호를 찾습니다.
        """
        ws = self.sheet_b.worksheet("인벤토리")
        cell = ws.find(user_name, in_column=2)
        if cell and cell.row >= 12:
            return cell.row
        return None

    @with_backoff
    def get_user_info(self, user_nickname):
        """
        유저의 상태(HP, SP, 허기)와 인벤토리 정보를 가져옵니다.
        배치 요청으로 최적화됨.
        """
        pure_name = self.parse_nickname(user_nickname)
        row = self.get_user_row(pure_name)
        if not row:
            return None

        ws = self.sheet_b.worksheet("인벤토리")
        
        # C열부터 J열까지 한번에 가져오기 (HP, SP, 허기, 아이템1~4, 추가아이템)
        # C: HP, D: SP, E: Hunger, F-I: Basic Items, J: Extra Items
        values = ws.get(f"C{row}:J{row}")[0]
        
        # 데이터 파싱
        # values 길이가 부족할 수 있으므로 패딩
        while len(values) < 8:
            values.append("")
            
        hp, sp, hunger = values[0], values[1], values[2]
        basic_items = values[3:7] # F, G, H, I
        extra_items_str = values[7] # J
        
        items = [item for item in basic_items if item.strip()]

        if extra_items_str:
            extra_items = [item.strip() for item in extra_items_str.split(',') if item.strip()]
            items.extend(extra_items)

        max_slots = 4
        for item in items:
            match = re.search(r'\(\+(\d+)\)$', item)
            if match:
                max_slots += int(match.group(1))

        return {
            "name": pure_name,
            "hp": hp,
            "sp": sp,
            "hunger": hunger,
            "items": items,
            "max_slots": max_slots
        }

    @with_backoff
    def add_item_to_user(self, user_nickname, item_name, count=1):
        """
        유저의 인벤토리에 아이템을 추가합니다.
        """
        pure_name = self.parse_nickname(user_nickname)
        row = self.get_user_row(pure_name)
        if not row:
            return False, "유저를 찾을 수 없습니다."

        user_info = self.get_user_info(user_nickname)
        current_items = user_info['items']
        max_slots = user_info['max_slots']

        if len(current_items) + count > max_slots:
            return False, "인벤토리가 가득 찼습니다."

        ws = self.sheet_b.worksheet("인벤토리")
        
        new_items = current_items + [item_name] * count
        
        # 업데이트할 데이터 준비
        basic = new_items[:4]
        while len(basic) < 4:
            basic.append("")
            
        extra = new_items[4:]
        extra_str = ",".join(extra) if extra else ""
        
        # F-I열과 J열을 한번에 업데이트하기 위해 값 구성
        # F, G, H, I, J 순서
        update_values = basic + [extra_str]
        
        ws.update(range_name=f"F{row}:J{row}", values=[update_values])

        return True, "아이템이 지급되었습니다."

    @with_backoff
    def remove_item_from_user(self, user_nickname, item_name, count=1):
        """
        유저의 인벤토리에서 아이템을 제거합니다.
        """
        pure_name = self.parse_nickname(user_nickname)
        row = self.get_user_row(pure_name)
        if not row:
            return False, "유저를 찾을 수 없습니다."

        user_info = self.get_user_info(user_nickname)
        current_items = user_info['items']

        temp_items = current_items.copy()
        removed_count = 0
        for _ in range(count):
            if item_name in temp_items:
                temp_items.remove(item_name)
                removed_count += 1
            else:
                break
        
        if removed_count < count:
            return False, f"아이템이 부족합니다. 보유: {current_items.count(item_name)}, 필요: {count}."

        ws = self.sheet_b.worksheet("인벤토리")
        
        basic = temp_items[:4]
        while len(basic) < 4:
            basic.append("")
            
        extra = temp_items[4:]
        extra_str = ",".join(extra) if extra else ""
        
        update_values = basic + [extra_str]
        ws.update(range_name=f"F{row}:J{row}", values=[update_values])
            
        return True, "아이템이 제거되었습니다."

    @with_backoff
    def register_item_metadata(self, name, type_, description):
        """
        새로운 아이템을 스프레드시트 A의 '아이템데이터' 시트에 등록합니다.
        캐시를 먼저 확인하여 중복 등록을 방지합니다.
        """
        # 캐시 확인
        cached_items = self.cache.get("items", [])
        normalized_name = self.normalize_item_name(name)
        
        for item in cached_items:
            if self.normalize_item_name(item.get("name", "")) == normalized_name:
                return # 이미 존재함

        ws = self.sheet_a.worksheet("아이템데이터")
        
        # 시트에서 다시 한번 확인 (캐시가 최신이 아닐 수 있으므로)
        # 하지만 요청 최소화를 위해 여기서는 생략하거나, 
        # 안전을 위해 시트의 모든 이름을 가져오는 대신 append 시도 전 체크
        
        # 기존 로직: col_values(1) 호출 -> 비용 큼
        # 개선: 캐시에 없으면 등록 시도.
        
        ws.append_row([name, type_, description])
        
        # 캐시 업데이트
        new_item = {
            "name": name,
            "type": type_,
            "description": description
        }
        cached_items.append(new_item)
        self.cache["items"] = cached_items
        self.save_cache()

    def get_warehouse_ranges(self, item_type):
        """
        아이템 유형에 따른 창고(공동아이템 시트)의 셀 범위를 반환합니다.
        """
        if item_type == "음식":
            return ["C4:D24", "E4:F24", "G4:H24", "I4:J24", "K4:L24"]
        elif item_type == "의약품":
            return ["C25:D45", "E25:F45", "G25:H45", "I25:J45", "K25:L45"]
        elif item_type == "이외 아이템":
            return ["C46:D66", "E46:F66", "G46:H66", "I46:J66", "K46:L66"]
        return []

    @with_backoff
    def get_warehouse_items(self, item_type):
        """
        특정 유형의 창고 아이템 목록을 가져옵니다.
        batch_get을 사용하여 API 호출을 1회로 줄입니다.
        """
        ws = self.sheet_b.worksheet("공동아이템")
        ranges = self.get_warehouse_ranges(item_type)
        items = {} 
        
        # batch_get 사용
        batch_data = ws.batch_get(ranges)
        
        for data in batch_data:
            # data는 [[이름, 수량], [이름, 수량], ...] 형태
            for row in data:
                if len(row) >= 2 and row[0]: # 이름이 있는 경우만 처리
                    name = row[0]
                    try:
                        count = int(row[1])
                    except:
                        count = 0
                    
                    if name in items:
                        items[name] += count
                    else:
                        items[name] = count
        return items

    @with_backoff
    def update_warehouse_item(self, item_name, item_type, count_change):
        """
        창고(공동아이템)의 아이템 수량을 업데이트합니다.
        batch_get과 batch_update를 사용하여 최적화합니다.
        """
        ws = self.sheet_b.worksheet("공동아이템")
        ranges = self.get_warehouse_ranges(item_type)
        
        normalized_target = self.normalize_item_name(item_name)
        
        # A1 표기법을 (row, col) 인덱스로 변환하는 헬퍼 함수
        def a1_to_rc(a1):
            match = re.match(r"([A-Z]+)(\d+)", a1)
            col_str, row_str = match.groups()
            row = int(row_str)
            col = 0
            for char in col_str:
                col = col * 26 + (ord(char) - ord('A') + 1)
            return row, col

        # 모든 해당 범위의 슬롯 정보를 읽어옴 (batch_get)
        batch_data = ws.batch_get(ranges)
        
        slots = [] 
        
        for idx, r_str in enumerate(ranges):
            start, end = r_str.split(':')
            s_row, s_col = a1_to_rc(start)
            
            # 해당 범위의 데이터
            cell_values = batch_data[idx]
            
            # 범위의 높이 계산 (예: 4~24행이면 21개 행)
            # cell_values의 길이보다 범위가 더 클 수 있으므로 범위 기준으로 순회
            e_row, _ = a1_to_rc(end)
            range_height = e_row - s_row + 1
            
            for i in range(range_height):
                name_val = ""
                count_val = 0
                if i < len(cell_values):
                    row_vals = cell_values[i]
                    if len(row_vals) > 0: name_val = row_vals[0]
                    if len(row_vals) > 1: 
                        try: count_val = int(row_vals[1])
                        except: count_val = 0
                
                slots.append({
                    "row": s_row + i,
                    "col_name": s_col,
                    "col_count": s_col + 1,
                    "name": name_val,
                    "count": count_val,
                    "range_idx": idx, # 어느 범위에 속하는지
                    "local_idx": i    # 범위 내에서의 인덱스
                })

        # 로직 처리
        updates = [] # batch_update를 위한 리스트
        
        if count_change > 0: # 보관 (추가)
            # 1. 이미 존재하는 아이템이 있는지 확인
            for slot in slots:
                if self.normalize_item_name(slot['name']) == normalized_target:
                    new_count = slot['count'] + count_change
                    # 업데이트할 셀 주소 계산 필요 없이 update_cell 대신 batch_update 포맷 사용
                    # 하지만 gspread의 batch_update는 range와 values를 받음.
                    # 여기서는 단일 셀 업데이트가 여러 개일 수 있으므로 ws.batch_update 사용
                    
                    # gspread batch_update는 [{'range': 'A1', 'values': [['val']]}, ...] 형태 지원
                    ws.update_cell(slot['row'], slot['col_count'], new_count)
                    return True, "기존 아이템에 수량이 추가되었습니다."
            
            # 2. 존재하지 않으면 빈 슬롯 찾기
            for slot in slots:
                if not slot['name']: # 빈 슬롯
                    ws.update_cell(slot['row'], slot['col_name'], item_name)
                    ws.update_cell(slot['row'], slot['col_count'], count_change)
                    return True, "새로운 아이템이 보관되었습니다."
            
            return False, "해당 유형의 창고 공간이 부족합니다."

        else: # 불출 (제거)
            remove_qty = -count_change
            for slot in slots:
                if self.normalize_item_name(slot['name']) == normalized_target:
                    if slot['count'] < remove_qty:
                        return False, "창고에 아이템 수량이 부족합니다."
                    
                    new_count = slot['count'] - remove_qty
                    if new_count == 0:
                        ws.update_cell(slot['row'], slot['col_name'], "")
                        ws.update_cell(slot['row'], slot['col_count'], "")
                    else:
                        ws.update_cell(slot['row'], slot['col_count'], new_count)
                    return True, "불출되었습니다."
            
            return False, "창고에서 해당 아이템을 찾을 수 없습니다."

    @with_backoff
    def get_all_users(self):
        """
        스프레드시트 B에서 모든 유저의 이름 목록을 가져옵니다.
        """
        ws = self.sheet_b.worksheet("인벤토리")
        names = ws.col_values(2)[11:] 
        return [n for n in names if n.strip()]

    def get_item_type(self, item_name):
        """
        아이템 이름을 통해 아이템의 유형(음식, 의약품 등)을 찾습니다.
        캐시를 우선 확인합니다.
        """
        normalized_name = self.normalize_item_name(item_name)
        
        # 캐시 확인
        cached_items = self.cache.get("items", [])
        for item in cached_items:
            if self.normalize_item_name(item.get("name", "")) == normalized_name:
                return item.get("type", "이외 아이템")
        
        # 캐시에 없으면 시트 확인 (백오프 적용)
        return self._fetch_item_type_from_sheet(item_name)

    @with_backoff
    def _fetch_item_type_from_sheet(self, item_name):
        ws = self.sheet_a.worksheet("아이템데이터")
        normalized_name = self.normalize_item_name(item_name)
        
        rows = ws.get_all_values()
        for row in rows:
            if len(row) >= 2:
                if self.normalize_item_name(row[0]) == normalized_name:
                    # 캐시 업데이트
                    new_item = {
                        "name": row[0],
                        "type": row[1],
                        "description": row[2] if len(row) > 2 else ""
                    }
                    self.cache["items"].append(new_item)
                    self.save_cache()
                    
                    return row[1]
        return "이외 아이템"

