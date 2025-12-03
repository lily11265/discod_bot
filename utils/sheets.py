import asyncio
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

    # =========================================================================
    # 1. 공통 유틸리티
    # =========================================================================

    def parse_nickname(self, nickname):
        """
        다양한 형식의 닉네임 문자열에서 순수 닉네임(이름)만 추출합니다.
        지원 형식: [칭호] 이름/HP/SP 등
        """
        logger.debug(f"[parse_nickname] 닉네임 파싱 시작 - 원본: '{nickname}'")
        
        # 1. [칭호] 부분 제거
        name_part = re.sub(r'\[.*?\]', '', nickname).strip()
        logger.debug(f"[parse_nickname] 칭호 제거 후 - '{name_part}'")
        
        # 2. 구분자로 분리
        tokens = re.split(r'[|/\\Iㅣ]', name_part)
        logger.debug(f"[parse_nickname] 구분자 분리 후 - {tokens}")
        
        # 3. 첫 번째 부분이 이름
        result = tokens[0].strip()
        logger.info(f"[parse_nickname] 파싱 완료 - '{nickname}' -> '{result}'")
        return result

    def normalize_item_name(self, item_name):
        """아이템 이름 정규화 (공백 제거 등)"""
        if not item_name: return ""
        return item_name.replace(" ", "")

    async def get_user_stats_async(self, discord_id, nickname=None):
        """[Async] 유저 스탯 조회"""
        return await asyncio.to_thread(self.get_user_stats, discord_id=str(discord_id), nickname=nickname)

    # =========================================================================
    # 2. Spreadsheet A: 기본 스탯 & 인벤토리
    # =========================================================================

    def get_user_stats(self, nickname: str = None, discord_id: str = None):
        """
        [Sheet A] '캐릭터스탯정리표'에서 유저 기본 스탯(Max HP/SP 등)을 가져옵니다.
        """
        logger.debug(f"[get_user_stats] 스탯 조회 시작 - nickname: {nickname}, discord_id: {discord_id}")
        
        # 1. 이름 찾기
        pure_name = None
        metadata = self.get_metadata_map()
        logger.debug(f"[get_user_stats] 메타데이터 맵 로드 완료 - {len(metadata)}개 항목")
        
        if discord_id and str(discord_id) in metadata:
            pure_name = metadata[str(discord_id)]
            logger.info(f"[get_user_stats] Discord ID로 이름 찾음 - ID: {discord_id}, Name: {pure_name}")
        elif nickname:
            pure_name = self.parse_nickname(nickname)
            logger.info(f"[get_user_stats] 닉네임 파싱 완료 - 원본: {nickname}, 파싱: {pure_name}")
        
        if not pure_name:
            logger.warning(f"[get_user_stats] 이름을 찾을 수 없음 - nickname: {nickname}, discord_id: {discord_id}")
            return None
        
        # 2. 캐시 확인
        if 'stats' in self.cached_data:
            logger.debug(f"[get_user_stats] 캐시에서 검색 시작 - 찾는 이름: {pure_name}")
            for stat in self.cached_data['stats']:
                if stat['name'] == pure_name:
                    logger.info(f"[get_user_stats] 캐시 히트 - {pure_name}: HP={stat['hp']}, Sanity={stat['sanity']}")
                    return stat
            logger.debug(f"[get_user_stats] 캐시 미스 - {pure_name} 캐시에 없음")
        else:
            logger.debug(f"[get_user_stats] 스탯 캐시 없음")
        
        # 3. 캐시에 없으면 직접 조회 (Fallback)
        logger.info(f"[get_user_stats] 캐시 갱신 시작 - fetch_all_stats 호출")
        all_stats = self.fetch_all_stats()
        logger.debug(f"[get_user_stats] 갱신된 스탯에서 재검색 - 총 {len(all_stats)}명")
        for stat in all_stats:
            if stat['name'] == pure_name:
                logger.info(f"[get_user_stats] 갱신 후 찾음 - {pure_name}: HP={stat['hp']}, Sanity={stat['sanity']}")
                return stat
        
        logger.warning(f"[get_user_stats] 최종 실패 - {pure_name} 데이터 없음")
        return None

    def fetch_all_stats(self):
            """[Sheet A] 전체 유저 스탯 캐싱 (수정됨: B열 3행 시작, 지정된 컬럼만 파싱)"""
            if not self.client: return []
            try:
                logger.debug(f"[fetch_all_stats] 스프레드시트 열기 - ID: {config.SPREADSHEET_ID_A}")
                sheet = self.client.open_by_key(config.SPREADSHEET_ID_A).worksheet("캐릭터스탯정리표")
                logger.debug(f"[fetch_all_stats] 데이터 가져오기")
                rows = sheet.get_all_values()
                logger.info(f"[fetch_all_stats] 총 {len(rows)}개 행 조회")
                
                stats_list = []
                
                # 데이터가 3행(인덱스 2)부터 시작하므로 rows[2:] 사용
                for idx, row in enumerate(rows[2:], start=3):
                    # 데이터 확보: I열(의지)까지 필요하므로 최소 9개 열(인덱스 8) 필요
                    # A(0), B(1), C(2), D(3), E(4), F(5), G(6), H(7), I(8)
                    if len(row) < 9:
                        row += [""] * (9 - len(row))
                    
                    # B열(인덱스 1): 이름
                    name = row[1].strip()
                    if not name: continue
                    
                    try:
                        # 불필요한 C(종족), D(나이), J(신청서) 제외하고 필요한 스탯만 매핑
                        stats = {
                            "name": name,
                            "hp": int(row[4]) if row[4].isdigit() else 0,           # E열: 체력
                            "sanity": int(row[5]) if row[5].isdigit() else 0,       # F열: 정신력
                            "perception": int(row[6]) if row[6].isdigit() else 0,   # G열: 감각
                            "intelligence": int(row[7]) if row[7].isdigit() else 0, # H열: 지성
                            "willpower": int(row[8]) if row[8].isdigit() else 0,    # I열: 의지
                        }
                        stats_list.append(stats)
                        logger.debug(f"[fetch_all_stats] 파싱 성공 - {name}")
                    except ValueError as e:
                        logger.warning(f"[fetch_all_stats] 파싱 오류 (행 {idx}, {name}): {e}")
                        continue
                
                self.cached_data['stats'] = stats_list
                self.save_cache()
                logger.info(f"[fetch_all_stats] 캐시 업데이트 완료 - {len(stats_list)}명")
                return stats_list
                
            except Exception as e:
                logger.error(f"Error fetching stats: {e}", exc_info=True)
                return []

    def read_hunger_stats_from_sheet(self):
        """[Sheet A] 인벤토리 시트에서 현재 상태(체력, 정신력, 허기) 읽기"""
        if not self.client: return []
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A)
            ws = sheet.worksheet("인벤토리")
            rows = ws.get_all_values()
            
            metadata = self.get_metadata_map()
            name_to_id = {v: k for k, v in metadata.items()}
            
            updates = []
            for row in rows[1:]:
                if len(row) < 5:
                    row += [""] * (5 - len(row))
                
                if len(row) < 5: continue
                name = row[1].strip()
                if not name or name not in name_to_id: continue
                
                user_id = int(name_to_id[name])
                
                # C: 체력, D: 정신력, E: 허기
                hp = int(row[2]) if row[2].strip().isdigit() else None
                sp = int(row[3]) if row[3].strip().isdigit() else None
                hunger = int(row[4]) if row[4].strip().isdigit() else None
                
                updates.append({
                    'user_id': user_id,
                    'hp': hp,
                    'sp': sp,
                    'hunger': hunger
                })
            return updates
        except Exception as e:
            logger.error(f"Error reading hunger stats: {e}")
            return []

    def sync_hunger_to_sheet(self, user_states):
        """[Sheet A] DB의 현재 상태를 인벤토리 시트에 동기화 (Batch Update)"""
        if not self.client: return
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A)
            ws = sheet.worksheet("인벤토리")
            rows = ws.get_all_values()
            
            metadata = self.get_metadata_map()
            name_to_id = {v: k for k, v in metadata.items()}
            
            # user_states: [(user_id, hp, sp, hunger), ...]
            state_map = {str(u[0]): {'hp': u[1], 'sp': u[2], 'hunger': u[3]} for u in user_states}
            
            updates = []
            
            for i, row in enumerate(rows):
                if i == 0: continue # Header
                if len(row) < 5:
                    row += [""] * (5 - len(row))
                
                if len(row) < 2: continue
                
                name = row[1].strip()
                if name in name_to_id:
                    uid = name_to_id[name]
                    if uid in state_map:
                        state = state_map[uid]
                        
                        # C, D, E 열 업데이트 (인덱스 2, 3, 4)
                        # 변경된 값만 업데이트하도록 최적화 가능하지만, 여기선 일괄 업데이트
                        
                        # 현재 시트 값과 비교
                        current_hp = row[2].strip()
                        current_sp = row[3].strip()
                        current_hunger = row[4].strip()
                        
                        new_hp = str(state['hp'])
                        new_sp = str(state['sp'])
                        new_hunger = str(state['hunger'])
                        
                        if current_hp != new_hp or current_sp != new_sp or current_hunger != new_hunger:
                            range_name = f"C{i+1}:E{i+1}"
                            updates.append({
                                'range': range_name,
                                'values': [[new_hp, new_sp, new_hunger]]
                            })
            
            if updates:
                ws.batch_update(updates)
                logger.info(f"Synced {len(updates)} users from DB to Sheet A")
                
        except Exception as e:
            logger.error(f"Error syncing hunger to sheet: {e}")

    def add_item_to_user(self, user_id, item_name, count=1):
        """[Sheet A] 유저에게 아이템 지급 (단순 로그용, 실제는 DB 사용 권장)"""
        pass

    def remove_item_from_user(self, user_id, item_name, count=1):
        """[Sheet A] 유저 아이템 회수"""
        pass

    # =========================================================================
    # 3. Spreadsheet B: 마스터 데이터
    # =========================================================================

    def get_metadata_map(self, force_refresh=False):
        """[Sheet B] 메타데이터시트 (User Name <-> Discord ID)"""
        # 캐시 유효성 검사 (5분)
        now = datetime.datetime.now()
        last_update = self.cached_data.get('metadata_last_update')
        
        if last_update:
            if isinstance(last_update, str):
                last_update = datetime.datetime.fromisoformat(last_update)
            
            if not force_refresh and (now - last_update).total_seconds() < 300:
                logger.debug(f"[get_metadata_map] 캐시 유효 ({(now - last_update).total_seconds():.0f}초 경과) - API 호출 생략")
                return self.cached_data.get('metadata', {})

        logger.debug(f"[get_metadata_map] 메타데이터 조회 시작 (Force: {force_refresh})")
        
        if self.client:
            try:
                logger.debug(f"[get_metadata_map] 스프레드시트 열기 - ID: {config.SPREADSHEET_ID_B}")
                sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("메타데이터시트")
                logger.debug(f"[get_metadata_map] 워크시트 데이터 가져오기")
                rows = sheet.get_all_values()
                logger.info(f"[get_metadata_map] 총 {len(rows)}개 행 조회 (헤더 포함)")
                
                metadata = {}
                for idx, row in enumerate(rows[1:], start=2):  # 헤더 제외
                    if len(row) >= 2:
                        name = row[0].strip()  # A열: Name
                        discord_id = row[1].strip()  # B열: ID
                        if name and discord_id:
                            metadata[discord_id] = name
                            logger.debug(f"[get_metadata_map] 행 {idx} 매핑 추가 - Discord ID: {discord_id}, Name: {name}")
                        else:
                            logger.debug(f"[get_metadata_map] 행 {idx} 건너뜀 - Name 또는 ID 비어있음")
                    else:
                        logger.debug(f"[get_metadata_map] 행 {idx} 건너뜀 - 컬럼 부족 (최소 2개 필요)")
                
                self.cached_data['metadata'] = metadata
                self.cached_data['metadata_last_update'] = now.isoformat()
                self.save_cache() # 캐시 파일 저장
                
                logger.info(f"[get_metadata_map] 메타데이터 캐시 업데이트 완료 - {len(metadata)}개 매핑")
                return metadata
            except Exception as e:
                if "429" in str(e) or "Quota exceeded" in str(e):
                    logger.warning(f"[get_metadata_map] API 할당량 초과 (429) - 캐시된 데이터 사용 시도")
                else:
                    logger.error(f"[get_metadata_map] 조회 실패 - 오류: {e}", exc_info=True)
        else:
            logger.warning(f"[get_metadata_map] Google Sheets 클라이언트 없음")
        
        cached_metadata = self.cached_data.get('metadata', {})
        logger.info(f"[get_metadata_map] 캐시된 메타데이터 반환 (Fallback) - {len(cached_metadata)}개 항목")
        return cached_metadata

    def get_admin_permission(self, user_id):
        """[Sheet B] 관리자 권한 확인"""
        if not self.client: return False
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("관리자권한")
            rows = sheet.get_all_values()
            for row in rows[1:]:
                if str(user_id) in row:
                    return True
            return False
        except Exception:
            return False

    def get_item_data(self, item_name):
        """[Sheet B] 아이템 데이터 조회"""
        if not self.client: return None
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("아이템데이터")
            rows = sheet.get_all_values()
            for row in rows[1:]:
                if row[1] == item_name: # B열: 이름
                    return {
                        "id": row[0],
                        "name": row[1],
                        "type": row[2],
                        "description": row[3],
                        "effect": row[4] if len(row) > 4 else ""
                    }
            return None
        except Exception as e:
            logger.error(f"Error fetching item data: {e}")
            return None

    def get_madness_data(self):
        """[Sheet B] 광기 데이터 조회"""
        if not self.client: return []
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("광기데이터")
            rows = sheet.get_all_values()
            madness_list = []
            for row in rows[1:]:
                if len(row) >= 3:
                    madness_list.append({
                        "id": row[0],
                        "name": row[1],
                        "description": row[2],
                        "effect": row[3] if len(row) > 3 else ""
                    })
            return madness_list
        except Exception as e:
            logger.error(f"Error fetching madness data: {e}")
            return []

    def get_clue_combinations(self):
        """[Sheet B] 단서 조합 레시피 조회"""
        if not self.client: return []
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("단서조합")
            rows = sheet.get_all_values()
            recipes = []
            for row in rows[1:]:
                if len(row) >= 5:
                    recipe_id = row[0].strip()
                    required_clues = [c.strip() for c in row[1].split(',') if c.strip()]
                    result_type = row[2].strip() # '단서' or '아이템'
                    result_id = row[3].strip()
                    message = row[4].strip()
                    
                    if recipe_id and required_clues and result_id:
                        recipes.append({
                            "recipe_id": recipe_id,
                            "required_clues": required_clues,
                            "result_type": result_type,
                            "result_id": result_id,
                            "message": message
                        })
            return recipes
        except Exception as e:
            # 시트가 없거나 오류 발생 시 빈 리스트 반환 (로그는 디버그 레벨로 낮춤)
            logger.debug(f"No clue combination sheet found or error: {e}")
            return []

    # =========================================================================
    # 4. Spreadsheet C: 조사/월드맵
    # =========================================================================

    def fetch_investigation_data(self):
        """[Sheet C] 조사 데이터 파싱 (명세서 v2.0 호환)"""
        if not self.client: return {}
        try:
            spreadsheet = self.client.open_by_key(config.SPREADSHEET_ID_C)
            worksheets = spreadsheet.worksheets()
            world_map = {}
            
            for sheet in worksheets:
                category_name = sheet.title
                
                # 시트 무시 규칙
                if category_name.startswith("0.") or category_name.startswith("예시"):
                    continue

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
                
                # A~E 열의 이전 값을 저장하기 위한 리스트 (Fill-down 용)
                last_path = [""] * 5 
                
                # 방문한 장소 키(tuple)를 저장하여, 첫 등장 시에만 장소 묘사를 가져오도록 함
                visited_locations = set()

                # 헤더 스킵 (1행)
                for row_idx, row in enumerate(rows[1:]):
                    # 행 데이터 확보 (최소 18열 R열까지)
                    if len(row) < 18:
                        row += [""] * (18 - len(row))
                    
                    # 1. 경로 파싱 (A~E)
                    current_path = [row[i].strip() for i in range(5)]
                    
                    # 빈 행(데이터 없음) 무시 체크
                    # A~E가 모두 비어있고 F(아이템)도 비어있으면 빈 행으로 간주
                    if not any(current_path) and not row[5].strip():
                        continue

                    # Fill-Down 로직
                    # 명세서: "장소 하나에 해당하는 행들은 연속된 구간에 몰아서 적는다"
                    # A열이 비어있으면 이전 경로를 그대로 사용한다고 가정
                    for i in range(5):
                        if not current_path[i]:
                            current_path[i] = last_path[i]
                    
                    # 갱신된 경로를 last_path로 저장
                    last_path = list(current_path)
                    
                    # 유효 경로 추출 (빈 문자열 제외)
                    clean_path = [p for p in current_path if p]
                    if not clean_path: continue

                    # location_key: 장소를 식별하는 유니크한 키 (튜플)
                    location_key = tuple(clean_path)

                    # 2. 트리 구조 생성/탐색
                    current_level = category_root["children"]
                    path_id = category_name
                    target_location = None
                    
                    for depth, loc_name in enumerate(clean_path):
                        path_id = f"{path_id}_{loc_name}"
                        if loc_name not in current_level:
                            is_channel = (depth == 0) # 첫 번째 깊이는 채널급
                            current_level[loc_name] = {
                                "id": path_id,
                                "name": loc_name,
                                "description": "", # Q열에서 채움
                                "children": {},
                                "items": [],
                                "type": "location",
                                "is_channel": is_channel,
                                "description_variants": []
                            }
                        target_location = current_level[loc_name]
                        current_level = current_level[loc_name]["children"]
                    
                    # 3. 데이터 파싱
                    item_name = row[5].strip()      # F: 기물 이름
                    button_text = row[6].strip()    # G: 버튼 텍스트
                    interaction_type = row[7].strip() # H: 타입
                    condition = row[8].strip()      # I: 조건
                    
                    # 결과 및 묘사
                    # M: 대성공, N: 성공, O: 실패, P: 대실패, Q: 묘사
                    variant_data = {
                        "condition": condition,
                        "type": interaction_type,
                        "result_crit_success": row[12].strip(), # M
                        "result_success": row[13].strip(),      # N
                        "result_fail": row[14].strip(),         # O
                        "result_crit_fail": row[15].strip(),    # P
                        "description": row[16].strip()          # Q
                    }

                    # 4. 데이터 적용
                    
                    # 4-1. 장소 묘사 (Location Description)
                    # "각 장소의 첫 번째 행의 Q열은 그 장소 자체의 묘사"
                    if location_key not in visited_locations:
                        target_location["description"] = variant_data["description"]
                        
                        # 아이템이 없는 경우, 이 행의 조건은 장소 진입 조건으로 간주
                        if not item_name:
                            target_location["condition"] = condition
                            
                        visited_locations.add(location_key)
                        
                        # 만약 기물 이름이 없다면 이 행은 순수하게 장소 묘사만을 위한 행임.
                        # 기물 이름이 있다면, 장소 묘사 + 첫 번째 아이템 정의가 동시에 있는 행임.
                    
                    # 4-2. 아이템/상호작용 추가
                    if item_name:
                        # 기존 아이템 찾기 (이름과 버튼 텍스트가 모두 같아야 같은 그룹)
                        existing_item = None
                        for item in target_location["items"]:
                            if item["name"] == item_name and item["button_text"] == button_text:
                                existing_item = item
                                break
                        
                        if not existing_item:
                            existing_item = {
                                "name": item_name,
                                "button_text": button_text,
                                "type": interaction_type, # 대표 타입 (첫 행 기준)
                                "variants": []
                            }
                            target_location["items"].append(existing_item)
                        
                        existing_item["variants"].append(variant_data)

            self.cached_data['investigation'] = world_map
            return world_map
        except Exception as e:
            logger.error(f"Error fetching investigation data: {e}", exc_info=True)
            return {}

    # =========================================================================
    # 5. Spreadsheet D: 동적 로그
    # =========================================================================

    def sync_db_to_sheets(self, user_states_data):
        """[Sheet D] DB 데이터를 동적 로그 시트에 동기화 (03:00 AM)"""
        if not self.client: return
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_D)
            
            # 1. 유저_상태 동기화
            ws_state = sheet.worksheet("유저_상태")
            
            # 기존 시트 데이터 가져오기
            sheet_rows = ws_state.get_all_values()
            header = ["Discord ID", "캐릭터명", "현재 체력", "현재 정신력", "현재 허기", "감염도", "마지막 허기 업데이트", "마지막 정신력 회복"]
            
            if not sheet_rows:
                existing_data = []
            else:
                # 헤더가 있을 수 있으므로 첫 줄 확인
                if sheet_rows[0] == header:
                    existing_data = sheet_rows[1:]
                else:
                    existing_data = sheet_rows # 헤더가 없거나 다르면 전체 데이터로 간주

            # user_states_data: list of tuples (user_id, hp, sanity, hunger, infection, last_hunger, last_sanity, ...)
            
            metadata = self.get_metadata_map()
            
            # DB 데이터를 딕셔너리로 변환 (Key: Discord ID)
            db_data_map = {}
            for state in user_states_data:
                uid = str(state[0])
                name = metadata.get(uid, "Unknown")
                db_data_map[uid] = [
                    uid, name, state[1], state[2], state[3], state[4], state[5], state[6]
                ]
            
            final_rows = []
            processed_ids = set()
            
            # 1. 기존 시트 데이터 순회하며 업데이트
            for row in existing_data:
                if not row: continue
                uid = str(row[0]).strip()
                
                if uid in db_data_map:
                    # DB에 있는 데이터면 DB 값으로 교체 (업데이트)
                    final_rows.append(db_data_map[uid])
                    processed_ids.add(uid)
                else:
                    # DB에 없는 데이터면 기존 값 유지 (보존)
                    final_rows.append(row)
            
            # 2. DB에는 있지만 시트에는 없던 새로운 데이터 추가
            for uid, row_data in db_data_map.items():
                if uid not in processed_ids:
                    final_rows.append(row_data)
            
            # 시트 클리어 후 재작성
            ws_state.clear()
            ws_state.append_row(header)
            if final_rows:
                ws_state.append_rows(final_rows)
            
            logger.info(f"Synced User State to Sheet D (Merged {len(final_rows)} rows)")
            
        except Exception as e:
            logger.error(f"Error syncing DB to Sheets: {e}")

    # =========================================================================
    # 6. 기타 (창고 등)
    # =========================================================================
    
    def get_warehouse_items(self, item_type):
        """[Sheet A] 공동아이템 (창고)"""
        # (기존 로직 유지, 시트 ID만 A로 확인)
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A)
            ws = sheet.worksheet("공동아이템")
            # ... (기존 범위 로직)
            return {} # Placeholder
        except Exception as e:
            return {}

    def update_warehouse_item(self, item_name, item_type, count_change):
        """[Sheet A] 창고 업데이트"""
        # (기존 로직 유지)
        pass

    def sync_sheet_inventory_to_db(self, db_manager):
        """[Sheet A -> DB] 시트 인벤토리를 DB로 동기화 (Startup)"""
        if not self.client: return
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A)
            ws = sheet.worksheet("인벤토리")
            rows = ws.get_all_values()
            
            metadata = self.get_metadata_map()
            name_to_id = {v: k for k, v in metadata.items()}
            
            # DB 업데이트를 위한 데이터 준비
            user_items = {} # user_id: {item_name: count}
            
            for row in rows[1:]:
                if len(row) < 10: continue
                name = row[1].strip()
                if not name or name not in name_to_id: continue
                
                user_id = int(name_to_id[name])
                items = []
                
                # 기본 슬롯 (F-I, idx 5-8)
                for i in range(5, 9):
                    if i < len(row) and row[i].strip():
                        items.append(row[i].strip())
                        
                # 추가 슬롯 (J, idx 9)
                if len(row) > 9 and row[9].strip():
                    extra = [x.strip() for x in row[9].split(',') if x.strip()]
                    items.extend(extra)
                    
                # 카운팅
                if user_id not in user_items:
                    user_items[user_id] = {}
                
                for item in items:
                    user_items[user_id][item] = user_items[user_id].get(item, 0) + 1
            
            return user_items
            
        except Exception as e:
            logger.error(f"Error reading sheet inventory: {e}")
            return {}

    def sync_db_inventory_to_sheet(self, db_manager, all_inventories):
        """[DB -> Sheet A] DB 인벤토리를 시트로 동기화 (Periodic)"""
        if not self.client: return
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A)
            ws = sheet.worksheet("인벤토리")
            rows = ws.get_all_values()
            
            metadata = self.get_metadata_map()
            name_to_id = {v: k for k, v in metadata.items()}
            
            # all_inventories: [(user_id, item_name, count), ...]
            # 유저별 아이템 리스트로 변환
            user_items_map = {}
            for uid, item, count in all_inventories:
                uid = str(uid)
                if uid not in user_items_map:
                    user_items_map[uid] = []
                user_items_map[uid].extend([item] * count)
            
            updates = []
            
            for i, row in enumerate(rows):
                if i == 0: continue
                if len(row) < 2: continue
                name = row[1].strip()
                
                if name in name_to_id:
                    uid = name_to_id[name]
                    current_items = user_items_map.get(uid, [])
                    
                    # 시트 데이터 포맷팅
                    basic = current_items[:4]
                    while len(basic) < 4: basic.append("")
                    
                    extra = current_items[4:]
                    extra_str = ",".join(extra) if extra else ""
                    
                    # 변경 확인 (최적화)
                    sheet_basic = [row[k].strip() if k < len(row) else "" for k in range(5, 9)]
                    sheet_extra = row[9].strip() if len(row) > 9 else ""
                    
                    if basic != sheet_basic or extra_str != sheet_extra:
                        # F-I 업데이트
                        updates.append({
                            'range': f"F{i+1}:I{i+1}",
                            'values': [basic]
                        })
                        # J 업데이트
                        updates.append({
                            'range': f"J{i+1}",
                            'values': [[extra_str]]
                        })
            
            if updates:
                ws.batch_update(updates)
                logger.info(f"Synced inventory to Sheet A ({len(updates)//2} users updated)")
                
        except Exception as e:
            logger.error(f"Error syncing inventory to sheet: {e}")

    def register_item_metadata(self, name, type_, description):
        """[Sheet B] 아이템 데이터 등록"""
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B)
            ws = sheet.worksheet("아이템데이터")
            ws.append_row([name, name, type_, description]) # ID는 이름으로 대체하거나 자동생성 필요
        except Exception as e:
            logger.error(f"Error registering item: {e}")
    # =========================================================================
    # Async Wrappers
    # =========================================================================

    async def update_user_stats_async(self, discord_id, stats):
        """[Async] 유저 스탯 업데이트"""
        return await asyncio.to_thread(self.update_user_stats, discord_id, stats)

    async def get_item_data_async(self, item_name):
        """[Async] 아이템 데이터 조회"""
        return await asyncio.to_thread(self.get_item_data, item_name)

    async def get_madness_data_async(self):
        """[Async] 광기 데이터 조회"""
        return await asyncio.to_thread(self.get_madness_data)
        
    async def get_clue_combinations_async(self):
        """[Async] 단서 조합 레시피 조회"""
        return await asyncio.to_thread(self.get_clue_combinations)

    async def fetch_investigation_data_async(self):
        """[Async] 조사 데이터 파싱"""
        return await asyncio.to_thread(self.fetch_investigation_data)

    async def sync_db_to_sheets_async(self, db_manager):
        """[Async] DB -> Sheets 동기화"""
        # 1. DB 데이터 비동기 조회
        user_states = await db_manager.fetch_all("SELECT * FROM user_state")
        # 2. 시트 동기화 (스레드)
        return await asyncio.to_thread(self.sync_db_to_sheets, user_states)

    async def get_metadata_map_async(self):
        """[Async] 메타데이터 조회"""
        return await asyncio.to_thread(self.get_metadata_map)

    async def fetch_all_stats_async(self):
        """[Async] 전체 스탯 조회"""
        return await asyncio.to_thread(self.fetch_all_stats)

    async def sync_hunger_from_sheet_async(self, db_manager):
        """[Async] 시트 -> DB 허기 동기화"""
        # 1. 시트 데이터 읽기 (스레드)
        updates = await asyncio.to_thread(self.read_hunger_stats_from_sheet)
        
        # 2. DB 업데이트 (비동기)
        for update in updates:
            query_parts = []
            params = []
            
            if update['hp'] is not None:
                query_parts.append("current_hp = ?")
                params.append(update['hp'])
            if update['sp'] is not None:
                query_parts.append("current_sanity = ?")
                params.append(update['sp'])
            if update['hunger'] is not None:
                query_parts.append("current_hunger = ?")
                params.append(update['hunger'])
                
            if query_parts:
                params.append(update['user_id'])
                query = f"UPDATE user_state SET {', '.join(query_parts)} WHERE user_id = ?"
                await db_manager.execute_query(query, tuple(params))
        
        logger.info(f"Synced {len(updates)} users from Sheet A to DB")

    async def sync_hunger_to_sheet_async(self, db_manager):
        """[Async] DB -> 시트 허기 동기화"""
        # 1. DB 데이터 비동기 조회
        user_states = await db_manager.fetch_all("SELECT user_id, current_hp, current_sanity, current_hunger FROM user_state")
        # 2. 시트 동기화 (스레드)
        return await asyncio.to_thread(self.sync_hunger_to_sheet, user_states)

    async def save_cache_async(self):
        """[Async] 캐시 저장"""
        return await asyncio.to_thread(self.save_cache)

    async def sync_sheet_inventory_to_db_async(self, db_manager):
        """[Async] 시트 -> DB 인벤토리 동기화"""
        # 1. 시트 데이터 읽기 (스레드)
        user_items = await asyncio.to_thread(self.sync_sheet_inventory_to_db, db_manager)
        
        if not user_items: return
        
        # 2. DB 업데이트 (비동기)
        # 전체 인벤토리 초기화 후 재삽입 방식이 안전함 (동기화 관점)
        # 하지만 유저가 접속 중일 수 있으므로 트랜잭션 주의
        # 여기서는 간단하게 기존 인벤토리 삭제 후 삽입
        try:
            await db_manager.execute_query("DELETE FROM user_inventory")
            
            for uid, items in user_items.items():
                for item_name, count in items.items():
                    await db_manager.execute_query(
                        "INSERT INTO user_inventory (user_id, item_name, count) VALUES (?, ?, ?)",
                        (uid, item_name, count)
                    )
            logger.info("Synced inventory from Sheet A to DB")
        except Exception as e:
            logger.error(f"Error updating DB inventory: {e}")

    async def sync_db_inventory_to_sheet_async(self, db_manager):
        """[Async] DB -> 시트 인벤토리 동기화"""
        # 1. DB 데이터 조회
        all_inventories = await db_manager.fetch_all("SELECT user_id, item_name, count FROM user_inventory")
        # 2. 시트 업데이트 (스레드)
        await asyncio.to_thread(self.sync_db_inventory_to_sheet, db_manager, all_inventories)

    async def initialize_worksheets_async(self):
        """[Async] 워크시트 초기화"""
        # return await asyncio.to_thread(self.initialize_worksheets) # 메서드 없음
        pass
