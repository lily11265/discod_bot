import gspread
import re
import os
from google.oauth2.service_account import Credentials

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
        self.sheet_a = self.gc.open_by_key(sheet_a_id)
        self.sheet_b = self.gc.open_by_key(sheet_b_id)

    def parse_nickname(self, nickname):
        """
        다양한 형식의 닉네임 문자열에서 순수 닉네임(이름)만 추출합니다.
        
        지원하는 형식 예시:
        - [칭호] 이름 | HP | SP
        - 이름 | HP | SP
        - 이름 / HP / SP
        - 이름 \ HP \ SP
        - 이름 I HP I SP
        - 이름 ㅣ HP ㅣ SP
        
        Args:
            nickname (str): 파싱할 전체 닉네임 문자열
            
        Returns:
            str: 추출된 순수 이름
        """
        # 1. [칭호] 부분 제거 (대괄호와 그 안의 내용 제거)
        name_part = re.sub(r'\[.*?\]', '', nickname).strip()
        
        # 2. 구분자(|, /, \, I, ㅣ)를 기준으로 문자열 분리
        # 정규표현식을 사용하여 다양한 구분자를 한 번에 처리
        tokens = re.split(r'[|/\\Iㅣ]', name_part)
        
        # 3. 분리된 첫 번째 부분이 이름이므로 공백 제거 후 반환
        pure_name = tokens[0].strip()
        return pure_name

    def normalize_item_name(self, item_name):
        """
        아이템 이름 비교를 위해 정규화합니다.
        현재는 모든 공백을 제거하는 방식을 사용합니다.
        
        Args:
            item_name (str): 정규화할 아이템 이름
            
        Returns:
            str: 공백이 제거된 아이템 이름
        """
        return item_name.replace(" ", "")

    def get_admin_permission(self, user_id):
        """
        특정 유저가 관리자 권한을 가지고 있는지 확인합니다.
        스프레드시트 A의 '메타데이터시트'를 참조합니다.
        
        규칙: C열에 'Y'가 적혀 있으면 해당 행의 유저는 관리자입니다.
        
        Args:
            user_id (int/str): 확인할 유저의 Discord ID
            
        Returns:
            bool: 관리자 권한이 있으면 True, 없으면 False
        """
        try:
            ws = self.sheet_a.worksheet("메타데이터시트")
            # 가정: A열에 ID, B열에 이름, C열에 권한(Y/N)이 있음
            # A열(1번 컬럼)에서 user_id를 검색
            cell = ws.find(str(user_id), in_column=1)
            if cell:
                # ID를 찾으면 해당 행의 C열(3번 컬럼) 값을 확인
                perm = ws.cell(cell.row, 3).value
                # 대소문자 구분 없이 Y 확인, 공백 제거
                if perm and str(perm).strip().upper() == 'Y':
                    return True
            return False
        except Exception as e:
            print(f"관리자 권한 확인 중 오류 발생: {e}")
            return False

    def get_user_row(self, user_name):
        """
        스프레드시트 B의 '인벤토리' 시트에서 특정 유저의 행 번호를 찾습니다.
        
        Args:
            user_name (str): 찾을 유저의 이름 (순수 이름)
            
        Returns:
            int or None: 유저가 있는 행 번호. 찾지 못하면 None 반환.
        """
        ws = self.sheet_b.worksheet("인벤토리")
        # 유저 이름은 B열(2번 컬럼)에 있으며, 12행부터 시작한다고 가정
        cell = ws.find(user_name, in_column=2)
        if cell and cell.row >= 12:
            return cell.row
        return None

    def get_user_info(self, user_nickname):
        """
        유저의 상태(HP, SP, 허기)와 인벤토리 정보를 가져옵니다.
        
        Args:
            user_nickname (str): 유저의 닉네임 (파싱 전 형태 가능)
            
        Returns:
            dict or None: 유저 정보 딕셔너리. 유저를 찾을 수 없으면 None.
                - name: 순수 이름
                - hp, sp, hunger: 상태 스탯
                - items: 보유 아이템 리스트
                - max_slots: 최대 인벤토리 슬롯 수
        """
        pure_name = self.parse_nickname(user_nickname)
        row = self.get_user_row(pure_name)
        if not row:
            return None

        ws = self.sheet_b.worksheet("인벤토리")
        
        # 상태 정보 가져오기 (C, D, E열: HP, SP, 허기)
        stats = ws.get(f"C{row}:E{row}")[0]
        hp, sp, hunger = stats[0], stats[1], stats[2]

        # 기본 아이템 가져오기 (F, G, H, I열: 기본 4칸)
        basic_items = ws.get(f"F{row}:I{row}")[0]
        # 빈 문자열은 제외하고 리스트 생성
        items = [item for item in basic_items if item.strip()]

        # 추가 아이템 가져오기 (J열: 콤마로 구분된 문자열)
        extra_items_str = ws.cell(row, 10).value
        if extra_items_str:
            extra_items = [item.strip() for item in extra_items_str.split(',') if item.strip()]
            items.extend(extra_items)

        # 최대 슬롯 수 계산
        # 기본 4칸 + 가방 아이템 등에 의한 추가 슬롯
        # 아이템 이름 뒤에 (+숫자) 형태가 있으면 슬롯 추가로 인식
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

    def add_item_to_user(self, user_nickname, item_name, count=1):
        """
        유저의 인벤토리에 아이템을 추가합니다.
        
        Args:
            user_nickname (str): 유저 닉네임
            item_name (str): 추가할 아이템 이름
            count (int): 추가할 수량 (기본 1)
            
        Returns:
            (bool, str): 성공 여부와 메시지 튜플
        """
        pure_name = self.parse_nickname(user_nickname)
        row = self.get_user_row(pure_name)
        if not row:
            return False, "유저를 찾을 수 없습니다."

        user_info = self.get_user_info(user_nickname)
        current_items = user_info['items']
        max_slots = user_info['max_slots']

        # 인벤토리 공간 확인
        if len(current_items) + count > max_slots:
            return False, "인벤토리가 가득 찼습니다."

        ws = self.sheet_b.worksheet("인벤토리")
        
        # 새로운 아이템 리스트 생성
        new_items = current_items + [item_name] * count
        
        # 기존 데이터 초기화 (F-I열 및 J열)
        ws.batch_clear([f"F{row}:I{row}", f"J{row}"])

        # 기본 슬롯(F-I)에 아이템 채우기 (최대 4개)
        basic = new_items[:4]
        if basic:
            # 4개 미만일 경우 빈 문자열로 채움
            while len(basic) < 4:
                basic.append("")
            ws.update(range_name=f"F{row}:I{row}", values=[basic])

        # 추가 슬롯(J)에 나머지 아이템 채우기 (콤마로 구분)
        extra = new_items[4:]
        if extra:
            ws.update_cell(row, 10, ",".join(extra))

        return True, "아이템이 지급되었습니다."

    def remove_item_from_user(self, user_nickname, item_name, count=1):
        """
        유저의 인벤토리에서 아이템을 제거합니다.
        
        Args:
            user_nickname (str): 유저 닉네임
            item_name (str): 제거할 아이템 이름
            count (int): 제거할 수량
            
        Returns:
            (bool, str): 성공 여부와 메시지 튜플
        """
        pure_name = self.parse_nickname(user_nickname)
        row = self.get_user_row(pure_name)
        if not row:
            return False, "유저를 찾을 수 없습니다."

        user_info = self.get_user_info(user_nickname)
        current_items = user_info['items']

        # 아이템 보유 여부 확인 및 제거 시뮬레이션
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

        # 시트 업데이트
        ws = self.sheet_b.worksheet("인벤토리")
        ws.batch_clear([f"F{row}:I{row}", f"J{row}"])

        # 기본 슬롯 업데이트
        basic = temp_items[:4]
        while len(basic) < 4:
            basic.append("")
        ws.update(range_name=f"F{row}:I{row}", values=[basic])

        # 추가 슬롯 업데이트
        extra = temp_items[4:]
        if extra:
            ws.update_cell(row, 10, ",".join(extra))
            
        return True, "아이템이 제거되었습니다."

    def register_item_metadata(self, name, type_, description):
        """
        새로운 아이템을 스프레드시트 A의 '아이템데이터' 시트에 등록합니다.
        이미 존재하는 아이템(이름 기준)이면 등록하지 않습니다.
        
        Args:
            name (str): 아이템 이름
            type_ (str): 아이템 유형 (음식, 의약품 등)
            description (str): 아이템 설명
        """
        ws = self.sheet_a.worksheet("아이템데이터")
        # 이름 정규화 (공백 제거)
        normalized_name = self.normalize_item_name(name)
        
        # A열의 모든 이름을 가져와 중복 확인
        existing_names = ws.col_values(1)
        for ex_name in existing_names:
            if self.normalize_item_name(ex_name) == normalized_name:
                return # 이미 존재함
        
        # 새로운 행 추가
        ws.append_row([name, type_, description])

    def get_warehouse_ranges(self, item_type):
        """
        아이템 유형에 따른 창고(공동아이템 시트)의 셀 범위를 반환합니다.
        
        Args:
            item_type (str): 아이템 유형 (음식, 의약품, 이외 아이템)
            
        Returns:
            list: 해당 유형이 저장되는 셀 범위 리스트 (예: ["C4:D24", ...])
        """
        if item_type == "음식":
            return ["C4:D24", "E4:F24", "G4:H24", "I4:J24", "K4:L24"]
        elif item_type == "의약품":
            return ["C25:D45", "E25:F45", "G25:H45", "I25:J45", "K25:L45"]
        elif item_type == "이외 아이템":
            return ["C46:D66", "E46:F66", "G46:H66", "I46:J66", "K46:L66"]
        return []

    def get_warehouse_items(self, item_type):
        """
        특정 유형의 창고 아이템 목록을 가져옵니다.
        
        Args:
            item_type (str): 아이템 유형
            
        Returns:
            dict: {아이템이름: 수량} 형태의 딕셔너리
        """
        ws = self.sheet_b.worksheet("공동아이템")
        ranges = self.get_warehouse_ranges(item_type)
        items = {} 
        
        # 지정된 모든 범위를 순회하며 아이템 집계
        for r in ranges:
            data = ws.get(r)
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

    def update_warehouse_item(self, item_name, item_type, count_change):
        """
        창고(공동아이템)의 아이템 수량을 업데이트합니다.
        
        Args:
            item_name (str): 아이템 이름
            item_type (str): 아이템 유형
            count_change (int): 변경할 수량 (양수: 보관/추가, 음수: 불출/제거)
            
        Returns:
            (bool, str): 성공 여부와 메시지 튜플
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

        # 모든 해당 범위의 슬롯 정보를 읽어옴
        slots = [] # {row, col_name, col_count, name, count} 정보를 담을 리스트
        
        for r_str in ranges:
            start, end = r_str.split(':')
            s_row, s_col = a1_to_rc(start)
            e_row, e_col = a1_to_rc(end)
            
            # 범위 데이터 읽기
            cell_values = ws.get(r_str)
            
            for i in range(e_row - s_row + 1):
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
                    "count": count_val
                })

        # 로직 처리
        if count_change > 0: # 보관 (추가)
            # 1. 이미 존재하는 아이템이 있는지 확인
            for slot in slots:
                if self.normalize_item_name(slot['name']) == normalized_target:
                    # 존재하면 수량 증가
                    new_count = slot['count'] + count_change
                    ws.update_cell(slot['row'], slot['col_count'], new_count)
                    return True, "기존 아이템에 수량이 추가되었습니다."
            
            # 2. 존재하지 않으면 빈 슬롯 찾기
            for slot in slots:
                if not slot['name']: # 빈 슬롯
                    ws.update_cell(slot['row'], slot['col_name'], item_name)
                    ws.update_cell(slot['row'], slot['col_count'], count_change)
                    return True, "새로운 아이템이 보관되었습니다."
            
            return False, "해당 유형의 창고 공간이 부족합니다."

        else: # 불출 (제거, count_change는 음수)
            remove_qty = -count_change
            # 아이템 찾기
            for slot in slots:
                if self.normalize_item_name(slot['name']) == normalized_target:
                    if slot['count'] < remove_qty:
                        return False, "창고에 아이템 수량이 부족합니다."
                    
                    new_count = slot['count'] - remove_qty
                    if new_count == 0:
                        # 수량이 0이 되면 슬롯 비우기
                        ws.update_cell(slot['row'], slot['col_name'], "")
                        ws.update_cell(slot['row'], slot['col_count'], "")
                    else:
                        ws.update_cell(slot['row'], slot['col_count'], new_count)
                    return True, "불출되었습니다."
            
            return False, "창고에서 해당 아이템을 찾을 수 없습니다."

    def get_all_users(self):
        """
        스프레드시트 B에서 모든 유저의 이름 목록을 가져옵니다.
        
        Returns:
            list: 유저 이름 리스트
        """
        ws = self.sheet_b.worksheet("인벤토리")
        # 이름은 B12부터 시작 (B열)
        names = ws.col_values(2)[11:] # 0-indexed이므로 11은 12행
        return [n for n in names if n.strip()]

    def get_item_type(self, item_name):
        """
        아이템 이름을 통해 아이템의 유형(음식, 의약품 등)을 찾습니다.
        스프레드시트 A의 '아이템데이터'를 참조합니다.
        
        Args:
            item_name (str): 아이템 이름
            
        Returns:
            str: 아이템 유형. 찾지 못하면 '이외 아이템' 반환.
        """
        ws = self.sheet_a.worksheet("아이템데이터")
        normalized_name = self.normalize_item_name(item_name)
        
        # 모든 데이터를 가져와서 검색 (행 단위 순회)
        rows = ws.get_all_values()
        for row in rows:
            if len(row) >= 2:
                if self.normalize_item_name(row[0]) == normalized_name:
                    return row[1] # 유형은 B열(2번 컬럼)에 있음
        return "이외 아이템" # 기본값
