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
        - 이름 \\ HP \\ SP  # ✅ 이스케이프 수정
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
                # 카테고리(워크시트) 노드 생성
                category_name = sheet.title
                if category_name not in world_map:
                    world_map[category_name] = {
                        "id": category_name,
                        "name": category_name,
                        "description": f"{category_name} 지역입니다.",
                        "children": {},
                        "items": [],
                        "type": "category"
                    }
                
                category_root = world_map[category_name]
                
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
                            pass
                        
                        current_identity.append(last_seen[i])

                    # G, H (6, 7) 처리 (Button, Type)
                    for i in range(6, 8):
                        val = row[i].strip() if len(row) > i else ""
                        if val:
                            last_seen[i] = val

                    # 현재 행의 데이터 구성
                    # A~E: Location Path (0~4) - A열 포함!
                    # F: Item Name (5)
                    # G: Button Text (6)
                    # H: Type (7)
                    
                    # 유효한 경로 추출 (A~E 중 값이 있는 것)
                    location_path = [x for x in last_seen[0:5] if x]
                    item_name = last_seen[5] # F열
                    button_text = last_seen[6] # G열
                    interaction_type = last_seen[7] # H열
                    
                    if not location_path: continue

                    # 트리 구성
                    current_level = category_root["children"]
                    path_id = category_name
                    
                    # 지역 노드 생성/이동
                    for depth, loc_name in enumerate(location_path):
                        path_id = f"{path_id}_{loc_name}"
                        if loc_name not in current_level:
                            # A열(depth 0)은 채널로 취급
                            is_channel = (depth == 0)
                            
                            current_level[loc_name] = {
                                "id": path_id,
                                "name": loc_name,
                                "description": "",
                                "children": {},
                                "items": [], 
                                "type": "location",
                                "is_channel": is_channel # 채널 여부 플래그
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

    def initialize_worksheets(self):
        """
        필요한 워크시트가 있는지 확인하고, 없으면 생성하고 헤더와 예시 데이터를 추가합니다.
        """
        if not self.client:
            logger.warning("Google Sheets 클라이언트가 초기화되지 않았습니다.")
            return

        # 1. 스프레드시트 A (설정 데이터)
        try:
            sheet_a = self.client.open_by_key(config.SPREADSHEET_ID_A)
            required_sheets_a = {
                "캐릭터 스탯 정리표": [
                    "Discord ID", "캐릭터명", "종족", "직업", "체력", "정신력", "감각", "지성", "의지"
                ]

            }
            
            # 예시 데이터
            example_data_a = {
                "캐릭터 스탯 정리표": [
                    "1234567890", "테스트캐릭터", "인간", "조사관", "100", "100", "50", "50", "50"
                ]
            }

            existing_titles_a = [ws.title for ws in sheet_a.worksheets()]
            
            for title, headers in required_sheets_a.items():
                if title not in existing_titles_a:
                    logger.info(f"Creating missing worksheet in A: {title}")
                    ws = sheet_a.add_worksheet(title=title, rows=100, cols=20)
                    ws.append_row(headers)
                    if title in example_data_a:
                        ws.append_row(example_data_a[title])
                    logger.info(f"✅ Created: {title}")
        except Exception as e:
            logger.error(f"Error initializing Spreadsheet A: {e}")

        # 2. 스프레드시트 B (메타데이터/아이템)
        try:
            sheet_b = self.client.open_by_key(config.SPREADSHEET_ID_B)
            required_sheets_b = {
                "메타데이터시트": [
                    "User Name", "Discord ID", "Admin (Y/N)"
                ],
                "아이템데이터": [
                    "아이템 ID", "아이템명", "타입", "설명", "허기 회복", "체력 회복", "정신력 회복"
                ],
                "정보 조합": [
                    "조합 ID", "필요 단서 1", "필요 단서 2", "필요 단서 3", "결과 단서"
                ],
                "광기데이터": [
                    "광기 ID", "광기명", "설명", "효과 타입", "효과 값", "회복 난이도", "획득 조건"
                ],
                "생각데이터": [
                    "생각 ID", "생각명", "설명", "필요 단서", "기본 진행도", "완성 조건", "효과 타입", "효과 내용", "제약 내용", "슬롯 비용"
                ],
                "단서데이터": [
                    "단서 ID", "단서명", "카테고리", "설명", "연관 단서", "조합 가능 여부", "비고"
                ]
            }
            
            example_data_b = {
                "메타데이터시트": [
                    "테스트유저", "1234567890", "Y"
                ],
                "아이템데이터": [
                    "item_bread", "건빵", "음식", "딱딱한 빵", "15", "0", "0"
                ],
                "정보 조합": [
                    "combo_01", "clue_desk1_basic", "clue_calendar", "", "clue_ritual_date"
                ],
                "광기데이터": [
                    "madness_paranoia", "피해망상", "타인을 의심하게 됨", "페널티", "신뢰_판정:-15", "50", "정신력_0_괴물조우"
                ],
                "생각데이터": [
                    "thought_sharp_eye", "날카로운 관찰력", "세밀한 것을 본다", "clue_magnifier", "10", "100", "보너스", "조사_성공률:+10", "-", "1"
                ],
                "단서데이터": [
                    "clue_desk1_basic", "책상의 서류", "물적증거", "찢어진 문서 조각", "clue_desk2", "Y", "-"
                ]
            }

            existing_titles_b = [ws.title for ws in sheet_b.worksheets()]
            
            for title, headers in required_sheets_b.items():
                if title not in existing_titles_b:
                    logger.info(f"Creating missing worksheet in B: {title}")
                    ws = sheet_b.add_worksheet(title=title, rows=100, cols=20)
                    ws.append_row(headers)
                    if title in example_data_b:
                        ws.append_row(example_data_b[title])
                    logger.info(f"✅ Created: {title}")
        except Exception as e:
            logger.error(f"Error initializing Spreadsheet B: {e}")

        # 3. 스프레드시트 D (유저 동적 데이터)
        if not config.SPREADSHEET_ID_D:
            logger.warning("SPREADSHEET_ID_D is not set. Skipping initialization.")
            return

        try:
            sheet_d = self.client.open_by_key(config.SPREADSHEET_ID_D)
            required_sheets_d = {
                "유저_상태": [
                    "Discord ID", "캐릭터명", "현재 체력", "현재 정신력", "현재 허기", "감염도", "마지막 허기 업데이트", "마지막 정신력 회복", "허기 0 지속 일수", "최종 업데이트"
                ],
                "유저_인벤토리": [
                    "Discord ID", "캐릭터명", "아이템 ID", "아이템명", "수량", "획득 시각"
                ],
                "유저_단서": [
                    "Discord ID", "캐릭터명", "단서 ID", "단서명", "획득 시각"
                ],
                "유저_광기": [
                    "Discord ID", "캐릭터명", "광기 ID", "광기명", "획득 시각", "마지막 회복 시도"
                ],
                "유저_사고": [
                    "Discord ID", "캐릭터명", "생각 ID", "생각명", "상태", "진행도", "시작 시각", "완성 시각"
                ],
                "월드_트리거": [
                    "트리거 ID", "트리거명", "활성 여부", "활성화한 유저 ID", "활성화 시각"
                ],
                "월드_상태": [
                    "키", "값", "설명", "최종 업데이트"
                ],
                "조사_카운트": [
                    "Discord ID", "캐릭터명", "아이템 고유 ID", "조사 횟수", "마지막 조사 시각", "리셋 타입"
                ],
                "제거된_아이템": [
                    "지역 ID", "아이템 ID", "제거한 유저 ID", "제거 시각"
                ],
                "차단된_지역": [
                    "지역 ID", "차단 사유", "차단 시각"
                ]
            }
            
            existing_titles_d = [ws.title for ws in sheet_d.worksheets()]
            
            for title, headers in required_sheets_d.items():
                if title not in existing_titles_d:
                    logger.info(f"Creating missing worksheet in D: {title}")
                    ws = sheet_d.add_worksheet(title=title, rows=100, cols=20)
                    ws.append_row(headers)
                    logger.info(f"✅ Created: {title}")
        except Exception as e:
            logger.error(f"Error initializing Spreadsheet D: {e}")

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

    # --- Phase 2: Core Systems Extensions ---

    def sync_hunger_from_sheet(self, db_manager):
        """
        구글 시트 A의 "인벤토리" 워크시트 E열(허기) -> DB user_state.current_hunger
        """
        if not self.client:
            return

        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A).worksheet("인벤토리")
            rows = sheet.get_all_values()
            
            # 메타데이터 로드 (이름 -> Discord ID)
            metadata = self.get_metadata_map()
            name_to_id = {v: k for k, v in metadata.items()}
            
            count = 0
            for row in rows[1:]: # 헤더 스킵
                if len(row) > 4:
                    name = row[0].strip()
                    hunger_str = row[4].strip() # E열 (0-indexed: 4)
                    
                    if name in name_to_id and hunger_str.isdigit():
                        user_id = name_to_id[name]
                        hunger = int(hunger_str)
                        
                        # DB 업데이트
                        db_manager.execute_query(
                            "UPDATE user_state SET current_hunger = ? WHERE user_id = ?",
                            (hunger, user_id)
                        )
                        count += 1
            
            logger.info(f"Synced hunger from sheet for {count} users.")
        except Exception as e:
            logger.error(f"Error syncing hunger from sheet: {e}")

    def sync_hunger_to_sheet(self, db_manager):
        """
        DB user_state.current_hunger -> 구글 시트 A의 "인벤토리" 워크시트 E열
        """
        if not self.client:
            return

        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A).worksheet("인벤토리")
            rows = sheet.get_all_values()
            
            # DB에서 모든 유저 허기 조회
            db_users = db_manager.fetch_all("SELECT user_id, current_hunger FROM user_state")
            user_hunger_map = {str(uid): hunger for uid, hunger in db_users}
            
            # 메타데이터 로드 (Discord ID -> 이름)
            metadata = self.get_metadata_map()
            
            updates = []
            for i, row in enumerate(rows):
                if i == 0: continue # 헤더
                
                name = row[0].strip()
                # 이름으로 Discord ID 찾기 (역검색 필요하지만 metadata는 ID->Name)
                # metadata 값 중 name과 일치하는 키 찾기
                target_id = None
                for uid, uname in metadata.items():
                    if uname == name:
                        target_id = uid
                        break
                
                if target_id and target_id in user_hunger_map:
                    # E열 (5번째 열) 업데이트
                    # gspread는 1-based index: Row=i+1, Col=5
                    updates.append({
                        'range': f'E{i+1}',
                        'values': [[user_hunger_map[target_id]]]
                    })
            
            if updates:
                sheet.batch_update(updates)
                logger.info(f"Synced hunger to sheet for {len(updates)} users.")
                
        except Exception as e:
            logger.error(f"Error syncing hunger to sheet: {e}")

    def get_item_data(self, item_name: str):
        """
        SPREADSHEET_ID_B > "아이템데이터" 시트에서 아이템 정보 조회
        """
        # 캐시 확인
        if 'items' in self.cached_data:
            for item in self.cached_data['items']:
                if item['name'] == item_name:
                    return item
        
        # 캐시에 없으면 시트 조회 (또는 전체 로드 후 캐싱)
        if not self.client:
            return None

        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("아이템데이터")
            rows = sheet.get_all_values()
            
            items_list = []
            target_item = None
            
            for row in rows[1:]:
                if len(row) < 2: continue
                # 가정: A=ID, B=Name, C=Type, D=Desc, E=Hunger, F=HP, G=Sanity
                item = {
                    'item_id': row[0].strip(),
                    'name': row[1].strip(),
                    'type': row[2].strip() if len(row) > 2 else "",
                    'description': row[3].strip() if len(row) > 3 else "",
                    'hunger_recovery': int(row[4]) if len(row) > 4 and row[4].isdigit() else 0,
                    'hp_recovery': int(row[5]) if len(row) > 5 and row[5].isdigit() else 0,
                    'sanity_recovery': int(row[6]) if len(row) > 6 and row[6].isdigit() else 0
                }
                items_list.append(item)
                if item['name'] == item_name:
                    target_item = item
            
            # 전체 캐싱
            self.cached_data['items'] = items_list
            return target_item
            
        except Exception as e:
            logger.error(f"Error fetching item data: {e}")
            return None

    def get_madness_data(self, madness_id: str = None):
        """
        SPREADSHEET_ID_B > "광기데이터" 시트에서 광기 정보 조회
        """
        # 캐시 확인
        if 'madness_list' in self.cached_data:
            madness_list = self.cached_data['madness_list']
            if madness_id:
                for m in madness_list:
                    if m['madness_id'] == madness_id:
                        return m
                return None
            return madness_list

        if not self.client:
            return None

        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("광기데이터")
            rows = sheet.get_all_values()
            
            madness_list = []
            
            for row in rows[1:]:
                if len(row) < 2: continue
                # A=ID, B=Name, C=Desc, D=Type, E=Value, F=Diff, G=Condition
                m_data = {
                    'madness_id': row[0].strip(),
                    'name': row[1].strip(),
                    'description': row[2].strip() if len(row) > 2 else "",
                    'effect_type': row[3].strip() if len(row) > 3 else "",
                    'effect_value': row[4].strip() if len(row) > 4 else "",
                    'recovery_difficulty': int(row[5]) if len(row) > 5 and row[5].isdigit() else 0,
                    'acquisition_condition': row[6].strip() if len(row) > 6 else ""
                }
                madness_list.append(m_data)
            
            self.cached_data['madness_list'] = madness_list
            
            if madness_id:
                for m in madness_list:
                    if m['madness_id'] == madness_id:
                        return m
                return None
            return madness_list
            
        except Exception as e:
            logger.error(f"Error fetching madness data: {e}")
            return None
