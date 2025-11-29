import re
import gspread
from google.oauth2.service_account import Credentials
import config
import logging

import json
import os
import datetime

logger = logging.getLogger('sheets_manager')

CACHE_FILE = 'sheets_cache.json'

class SheetsManager:
    def __init__(self):
        self.scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        self.cached_data = {}
        self.load_cache()
        
        try:
            self.credentials = Credentials.from_service_account_file(
                config.GOOGLE_SERVICE_ACCOUNT_FILE, 
                scopes=self.scopes
            )
            self.client = gspread.authorize(self.credentials)
            logger.info("Connected to Google Sheets API")
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            self.client = None

    def load_cache(self):
        """JSON 캐시 파일에서 데이터를 로드합니다."""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    self.cached_data = json.load(f)
                logger.info(f"Loaded data from cache: {CACHE_FILE}")
            except Exception as e:
                logger.error(f"Failed to load cache: {e}")
        else:
            logger.info("No cache file found.")

    def save_cache(self):
        """현재 데이터를 JSON 캐시 파일로 저장합니다."""
        try:
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.cached_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved data to cache: {CACHE_FILE}")
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    def get_metadata_map(self):
        """
        메타데이터 시트에서 User Name <-> Discord ID 매핑을 가져옵니다.
        A열: User Name
        B열: Discord ID
        """
        if self.client:
            try:
                sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("메타데이터시트")
                rows = sheet.get_all_values()
                metadata = {}
                for row in rows[1:]: # 헤더 스킵
                    if len(row) >= 2:
                        name = row[0].strip()
                        discord_id = row[1].strip()
                        if name and discord_id:
                            metadata[discord_id] = name
                
                self.cached_data['metadata'] = metadata
                return metadata
            except Exception as e:
                logger.error(f"Error fetching metadata: {e}")
        
        return self.cached_data.get('metadata', {})

    def parse_nickname(self, nickname: str) -> str:
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

    def get_user_stats(self, nickname: str = None, discord_id: str = None):
        """
        구글 스프레드시트 A의 "캐릭터 스탯 정리표"에서 유저 스탯을 가져옵니다.
        우선순위:
        1. Discord ID로 메타데이터 매핑 확인 -> 이름 획득
        2. 이름으로 스탯 시트 검색
        
        캐시된 데이터가 있으면 캐시를 우선 사용합니다.
        """
        # 1. Discord ID로 이름 찾기
        pure_name = None
        metadata = self.cached_data.get('metadata', {})
        
        if discord_id and str(discord_id) in metadata:
            pure_name = metadata[str(discord_id)]
        elif nickname:
            pure_name = self.parse_nickname(nickname)
            
        if not pure_name:
            return None

        # 2. 캐시에서 스탯 찾기
        if 'stats' in self.cached_data:
            for stat in self.cached_data['stats']:
                if stat['name'] == pure_name:
                    return stat

        # 3. 캐시에 없으면 API 호출 (백업)
        if not self.client:
            return None

        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A).worksheet("캐릭터 스탯 정리표")
            data = sheet.get_all_values()
            
            # 헤더 제외하고 검색
            for row in data[1:]:
                if len(row) > 1 and row[1].strip() == pure_name:
                    stat_data = {
                        "name": pure_name,
                        "hp": int(row[4]) if len(row) > 4 and row[4].isdigit() else 0,
                        "sanity": int(row[5]) if len(row) > 5 and row[5].isdigit() else 0,
                        "perception": int(row[6]) if len(row) > 6 and row[6].isdigit() else 0,
                        "intelligence": int(row[7]) if len(row) > 7 and row[7].isdigit() else 0,
                        "willpower": int(row[8]) if len(row) > 8 and row[8].isdigit() else 0
                    }
                    return stat_data
            return None
        except Exception as e:
            logger.error(f"Error fetching user stats for {pure_name}: {e}")
            return None

    def fetch_all_stats(self):
        """모든 캐릭터 스탯을 가져와서 캐시에 저장합니다."""
        if not self.client:
            return []
            
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A).worksheet("캐릭터 스탯 정리표")
            data = sheet.get_all_values()
            stats_list = []
            
            for row in data[1:]:
                if len(row) > 1 and row[1].strip():
                    stats_list.append({
                        "name": row[1].strip(),
                        "hp": int(row[4]) if len(row) > 4 and row[4].isdigit() else 0,
                        "sanity": int(row[5]) if len(row) > 5 and row[5].isdigit() else 0,
                        "perception": int(row[6]) if len(row) > 6 and row[6].isdigit() else 0,
                        "intelligence": int(row[7]) if len(row) > 7 and row[7].isdigit() else 0,
                        "willpower": int(row[8]) if len(row) > 8 and row[8].isdigit() else 0
                    })
            
            self.cached_data['stats'] = stats_list
            return stats_list
        except Exception as e:
            logger.error(f"Error fetching all stats: {e}")
            return []

    def get_investigation_data(self):
        """
        구글 스프레드시트 B의 조사 시트 데이터를 가져와서 계층 구조로 파싱합니다.
        캐시가 있으면 캐시를 반환합니다.
        """
        if 'investigation' in self.cached_data and self.cached_data['investigation']:
            return self.cached_data['investigation']
            
        return self.fetch_investigation_data()

    def fetch_investigation_data(self):
        """API를 통해 조사 데이터를 가져오고 파싱하여 캐시에 저장합니다."""
        if not self.client:
            return {}

        try:
            spreadsheet = self.client.open_by_key(config.SPREADSHEET_ID_C)
            worksheets = spreadsheet.worksheets()
            
            # 트리 구조 초기화
            world_map = {}
            
            for sheet in worksheets:
                rows = sheet.get_all_values()
                
                # Fill Down을 위한 상태 변수
                # A, B, C, D, E, F, G, H
                # 인덱스: 0, 1, 2, 3, 4, 5, 6, 7
                last_seen = [""] * 8 
                
                # 헤더 스킵 (1행)
                for row_idx, row in enumerate(rows[1:]):
                    if not any(row): continue
                    
                    # 1. Fill Down Logic (A~F: Location/Item Identity)
                    current_identity = []
                    identity_changed = False
                    
                    # A~F (0~5) 처리
                    for i in range(6):
                        val = row[i].strip() if len(row) > i else ""
                        if val:
                            if last_seen[i] != val:
                                identity_changed = True
                            last_seen[i] = val
                            # 하위 레벨 초기화 (상위가 바뀌면 하위는 리셋되어야 함)
                            for j in range(i + 1, 8):
                                last_seen[j] = ""
                        else:
                            # 값이 없으면 이전 값 사용 (Fill Down)
                            # 단, 상위 레벨이 바뀌었으면(identity_changed) 초기화된 값을 사용하게 됨("")
                            pass
                        
                        current_identity.append(last_seen[i])

                    # G, H (6, 7) 처리 (Button, Type)
                    # Identity(A~F)가 같다면 G, H도 Fill Down 가능
                    # Identity가 다르면 G, H는 새로 읽어야 함 (위 루프에서 이미 초기화됨)
                    for i in range(6, 8):
                        val = row[i].strip() if len(row) > i else ""
                        if val:
                            last_seen[i] = val
                        # 값이 없으면 last_seen 사용 (위에서 초기화되었거나 이전 값 유지)

                    # 현재 행의 데이터 구성
                    # A~E: Location Path (0~4)
                    # F: Item Name (5)
                    # G: Button Text (6)
                    # H: Type (7)
                    
                    # 유효한 경로 추출 (A~E 중 값이 있는 것)
                    # A(채널)은 무시하고 B부터 시작? 
                    # 유저: "A열: 해당 카테고리 내에 조사시트가 구현된 채널 이름"
                    # B열: 최상위 지역
                    # 따라서 실제 트리는 B부터 시작. A는 "어디서 시작하는지" 매핑용이지만,
                    # 현재 구조는 Category(Sheet Name) -> B -> C... 구조임.
                    # A열은 검증용이나 시작점 찾기용으로 쓸 수 있음.
                    
                    # B~E (1~4) : 지역 경로
                    location_path = [x for x in last_seen[1:5] if x]
                    item_name = last_seen[5] # F열
                    button_text = last_seen[6] # G열
                    interaction_type = last_seen[7] # H열
                    
                    if not location_path: continue

                    # 트리 구성
                    current_level = world_map
                    path_id = ""
                    
                    # 지역 노드 생성/이동
                    for loc_name in location_path:
                        path_id = f"{path_id}_{loc_name}" if path_id else loc_name
                        if loc_name not in current_level:
                            current_level[loc_name] = {
                                "id": path_id,
                                "name": loc_name,
                                "description": "",
                                "children": {},
                                "items": [], # {name, button_text, variants: []}
                                "type": "location"
                            }
                        # 마지막 노드 저장
                        target_location = current_level[loc_name]
                        current_level = current_level[loc_name]["children"]
                    
                    # 데이터 파싱 (Variant)
                    # I: Condition, M-P: Results, Q: Desc
                    variant_data = {
                        "condition": row[8].strip() if len(row) > 8 else "",
                        "result_crit_success": row[12].strip() if len(row) > 12 else "",
                        "result_success": row[13].strip() if len(row) > 13 else "",
                        "result_fail": row[14].strip() if len(row) > 14 else "",
                        "result_crit_fail": row[15].strip() if len(row) > 15 else "",
                        "description": row[16].strip() if len(row) > 16 else ""
                    }

                    if item_name:
                        # 기물/상호작용인 경우
                        # 이미 존재하는 아이템인지 확인 (Name + Button Text 기준)
                        existing_item = None
                        for item in target_location["items"]:
                            if item["name"] == item_name and item["button_text"] == button_text:
                                existing_item = item
                                break
                        
                        if existing_item:
                            # Variant 추가
                            existing_item["variants"].append(variant_data)
                        else:
                            # 새 아이템 생성
                            new_item = {
                                "name": item_name,
                                "button_text": button_text,
                                "type": interaction_type,
                                "variants": [variant_data],
                                # 호환성을 위해 첫 번째 variant의 condition 등을 최상위에 복사?
                                # 아니면 로직을 전면 수정? -> 로직 수정 예정 (cogs/investigation.py)
                                # 일단 condition은 variants 안에만 둠.
                            }
                            target_location["items"].append(new_item)
                    else:
                        # 기물 이름이 없으면 지역 설명 (Q열)
                        # 조건(I열)이 있을 수도 있음 (상태에 따른 지역 묘사 변화)
                        # 지역 설명도 Variants로 관리?
                        # 현재 구조: "description": str
                        # 개선: "description_variants": []
                        if "description_variants" not in target_location:
                            target_location["description_variants"] = []
                        
                        target_location["description_variants"].append(variant_data)
                        
                        # 하위 호환성 (첫 번째 묘사 사용)
                        if not target_location["description"]:
                            target_location["description"] = variant_data["description"]

            self.cached_data['investigation'] = world_map
            return world_map
        except Exception as e:
            logger.error(f"Error fetching investigation data: {e}")
            return {}

    def get_info_combinations(self):
        """
        구글 스프레드시트 B의 "정보 조합" 시트 데이터를 가져옵니다.
        """
        if not self.client:
            return None
            
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("정보 조합")
            return sheet.get_all_values()
        except Exception as e:
            logger.error(f"Error fetching combination data: {e}")
            return None
