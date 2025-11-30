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

    def parse_nickname(self, nickname: str) -> str:
        """
        다양한 형식의 닉네임 문자열에서 순수 닉네임(이름)만 추출합니다.
        지원 형식: [칭호] 이름/HP/SP 등
        """
        # 1. [칭호] 부분 제거
        name_part = re.sub(r'\[.*?\]', '', nickname).strip()
        # 2. 구분자로 분리
        tokens = re.split(r'[|/\\Iㅣ]', name_part)
        # 3. 첫 번째 부분이 이름
        return tokens[0].strip()

    def normalize_item_name(self, item_name):
        return item_name.replace(" ", "")

    # =========================================================================
    # 2. Spreadsheet A: 기본 스탯 & 인벤토리
    # =========================================================================

    def get_user_stats(self, nickname: str = None, discord_id: str = None):
        """
        [Sheet A] '캐릭터 스탯 정리표'에서 유저 기본 스탯(Max HP/SP 등)을 가져옵니다.
        """
        # 1. 이름 찾기
        pure_name = None
        metadata = self.get_metadata_map() # 캐시된 메타데이터 사용
        
        if discord_id and str(discord_id) in metadata:
            pure_name = metadata[str(discord_id)]
        elif nickname:
            pure_name = self.parse_nickname(nickname)
            
        if not pure_name:
            return None

        # 2. 캐시 확인
        if 'stats' in self.cached_data:
            for stat in self.cached_data['stats']:
                if stat['name'] == pure_name:
                    return stat

        # 3. API 호출
        if not self.client: return None

        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A).worksheet("캐릭터 스탯 정리표")
            data = sheet.get_all_values()
            
            for row in data[1:]:
                if len(row) > 1 and row[0].strip() == pure_name: # A열이 이름
                    stat_data = {
                        "name": pure_name,
                        "hp": int(row[3]) if len(row) > 3 and row[3].isdigit() else 0, # D열
                        "sanity": int(row[4]) if len(row) > 4 and row[4].isdigit() else 0, # E열
                        "perception": int(row[5]) if len(row) > 5 and row[5].isdigit() else 0, # F열
                        "intelligence": int(row[6]) if len(row) > 6 and row[6].isdigit() else 0, # G열
                        "willpower": int(row[7]) if len(row) > 7 and row[7].isdigit() else 0 # H열
                    }
                    return stat_data
            return None
        except Exception as e:
            logger.error(f"Error fetching user stats for {pure_name}: {e}")
            return None

    def fetch_all_stats(self):
        """[Sheet A] 모든 캐릭터 스탯을 가져와 캐시에 저장"""
        if not self.client: return []
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A).worksheet("캐릭터 스탯 정리표")
            data = sheet.get_all_values()
            stats_list = []
            for row in data[1:]:
                if len(row) > 0 and row[0].strip():
                    stats_list.append({
                        "name": row[0].strip(),
                        "hp": int(row[3]) if len(row) > 3 and row[3].isdigit() else 0,
                        "sanity": int(row[4]) if len(row) > 4 and row[4].isdigit() else 0,
                        "perception": int(row[5]) if len(row) > 5 and row[5].isdigit() else 0,
                        "intelligence": int(row[6]) if len(row) > 6 and row[6].isdigit() else 0,
                        "willpower": int(row[7]) if len(row) > 7 and row[7].isdigit() else 0
                    })
            self.cached_data['stats'] = stats_list
            return stats_list
        except Exception as e:
            logger.error(f"Error fetching all stats: {e}")
            return []

    def sync_hunger_from_sheet(self, db_manager):
        """[Sheet A] 시트의 허기/HP/SP 값을 DB로 동기화 (시트 -> DB)"""
        if not self.client: return
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A)
            ws = sheet.worksheet("인벤토리")
            rows = ws.get_all_values()
            
            # B열: Name, C: HP, D: SP, E: Hunger
            # DB: user_state (user_id, hp, sanity, hunger, ...)
            
            # 1. 메타데이터로 이름 -> ID 매핑
            metadata = self.get_metadata_map()
            name_to_id = {v: k for k, v in metadata.items()}
            
            for row in rows[1:]:
                if len(row) < 5: continue
                name = row[1].strip()
                if not name or name not in name_to_id: continue
                
                user_id = name_to_id[name]
                
                # 시트 값 파싱
                try:
                    sheet_hp = int(row[2]) if row[2].isdigit() else None
                    sheet_sp = int(row[3]) if row[3].isdigit() else None
                    sheet_hunger = int(row[4]) if row[4].isdigit() else None
                except:
                    continue
                    
                if sheet_hp is None: continue

                # DB 업데이트
                # 값이 있는 경우에만 업데이트
                updates = []
                params = []
                
                if sheet_hp is not None:
                    updates.append("current_hp = ?")
                    params.append(sheet_hp)
                if sheet_sp is not None:
                    updates.append("current_sanity = ?")
                    params.append(sheet_sp)
                if sheet_hunger is not None:
                    updates.append("current_hunger = ?")
                    params.append(sheet_hunger)
                    
                if updates:
                    params.append(user_id)
                    query = f"UPDATE user_state SET {', '.join(updates)} WHERE user_id = ?"
                    db_manager.execute_query(query, tuple(params))
                    
            logger.info("Synced Hunger/Stats from Sheet A to DB")
        except Exception as e:
            logger.error(f"Error syncing from sheet: {e}")

    def sync_hunger_to_sheet(self, db_manager):
        """[Sheet A] DB의 허기/HP/SP 값을 시트로 동기화 (DB -> 시트)"""
        if not self.client: return
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A)
            ws = sheet.worksheet("인벤토리")
            rows = ws.get_all_values()
            
            # DB 상태 가져오기
            user_states = db_manager.fetch_all("SELECT user_id, current_hp, current_sanity, current_hunger FROM user_state")
            state_map = {str(s[0]): {'hp': s[1], 'sp': s[2], 'hunger': s[3]} for s in user_states}
            
            metadata = self.get_metadata_map()
            name_to_id = {v: k for k, v in metadata.items()}
            
            updates = []
            
            for i, row in enumerate(rows):
                if i == 0: continue # 헤더
                if len(row) < 2: continue
                name = row[1].strip()
                
                if name in name_to_id:
                    uid = name_to_id[name]
                    if uid in state_map:
                        state = state_map[uid]
                        
                        # 시트의 현재 값과 비교하여 다를 경우에만 업데이트 목록에 추가
                        # (성능 최적화를 위해 모든 값을 업데이트하지 않음)
                        try:
                            current_hp = int(row[2]) if row[2].isdigit() else None
                            current_sp = int(row[3]) if row[3].isdigit() else None
                            current_hunger = int(row[4]) if row[4].isdigit() else None
                        except:
                            current_hp, current_sp, current_hunger = None, None, None

                        if (current_hp != state['hp'] or 
                            current_sp != state['sp'] or 
                            current_hunger != state['hunger']):
                            
                            # C{i+1}:E{i+1} 범위 업데이트
                            updates.append({
                                'range': f"C{i+1}:E{i+1}",
                                'values': [[state['hp'], state['sp'], state['hunger']]]
                            })

            if updates:
                ws.batch_update(updates)
                logger.info(f"Synced {len(updates)} rows from DB to Sheet A")
            else:
                logger.info("No updates needed for Sheet A")
                
        except Exception as e:
            logger.error(f"Error syncing to sheet: {e}")

    def add_item_to_user(self, user_nickname, item_name, count=1):
        """[Sheet A] 유저 인벤토리에 아이템 추가"""
        try:
            user_info = self.get_user_info(user_nickname)
            if not user_info: return False, "유저 정보를 찾을 수 없습니다."
            
            current_items = user_info['items']
            max_slots = user_info['max_slots']
            row = user_info['row']

            if len(current_items) + count > max_slots:
                return False, "인벤토리가 가득 찼습니다."

            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A)
            ws = sheet.worksheet("인벤토리")
            
            new_items = current_items + [item_name] * count
            
            # 업데이트
            ws.batch_clear([f"F{row}:I{row}", f"J{row}"])
            
            basic = new_items[:4]
            while len(basic) < 4: basic.append("")
            ws.update(range_name=f"F{row}:I{row}", values=[basic])

            extra = new_items[4:]
            if extra:
                ws.update_cell(row, 10, ",".join(extra))

            return True, "아이템이 지급되었습니다."
        except Exception as e:
            logger.error(f"Error adding item: {e}")
            return False, f"오류 발생: {e}"

    def remove_item_from_user(self, user_nickname, item_name, count=1):
        """[Sheet A] 유저 인벤토리에서 아이템 제거"""
        try:
            user_info = self.get_user_info(user_nickname)
            if not user_info: return False, "유저 정보를 찾을 수 없습니다."

            current_items = user_info['items']
            row = user_info['row']

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

            sheet = self.client.open_by_key(config.SPREADSHEET_ID_A)
            ws = sheet.worksheet("인벤토리")
            
            ws.batch_clear([f"F{row}:I{row}", f"J{row}"])

            basic = temp_items[:4]
            while len(basic) < 4: basic.append("")
            ws.update(range_name=f"F{row}:I{row}", values=[basic])

            extra = temp_items[4:]
            if extra:
                ws.update_cell(row, 10, ",".join(extra))
                
            return True, "아이템이 제거되었습니다."
        except Exception as e:
            logger.error(f"Error removing item: {e}")
            return False, f"오류 발생: {e}"

    # =========================================================================
    # 3. Spreadsheet B: 마스터 데이터
    # =========================================================================

    def get_metadata_map(self):
        """[Sheet B] 메타데이터시트 (User Name <-> Discord ID)"""
        if self.client:
            try:
                sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("메타데이터시트")
                rows = sheet.get_all_values()
                metadata = {}
                for row in rows[1:]:
                    if len(row) >= 2:
                        name = row[0].strip() # A열: Name
                        discord_id = row[1].strip() # B열: ID
                        if name and discord_id:
                            metadata[discord_id] = name
                self.cached_data['metadata'] = metadata
                return metadata
            except Exception as e:
                logger.error(f"Error fetching metadata: {e}")
        return self.cached_data.get('metadata', {})

    def get_admin_permission(self, user_id):
        """[Sheet B] 관리자 권한 확인"""
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B)
            ws = sheet.worksheet("메타데이터시트")
            cell = ws.find(str(user_id), in_column=2) # B열이 ID
            if cell:
                # C열이 Admin 여부
                perm = ws.cell(cell.row, 3).value
                if perm and str(perm).strip().upper() == 'Y':
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking admin permission: {e}")
            return False

    def get_item_data(self, item_name):
        """[Sheet B] 아이템 데이터 조회"""
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("아이템데이터")
            rows = sheet.get_all_values()
            normalized_target = self.normalize_item_name(item_name)
            
            for row in rows[1:]:
                if len(row) >= 2 and self.normalize_item_name(row[1]) == normalized_target:
                    return {
                        "id": row[0],
                        "name": row[1],
                        "type": row[2],
                        "description": row[3],
                        "hunger_recovery": int(row[4]) if len(row)>4 and row[4].isdigit() else 0,
                        "hp_recovery": int(row[5]) if len(row)>5 and row[5].isdigit() else 0,
                        "sanity_recovery": int(row[6]) if len(row)>6 and row[6].isdigit() else 0
                    }
            return None
        except Exception as e:
            logger.error(f"Error getting item data: {e}")
            return None

    def get_madness_data(self):
        """[Sheet B] 광기 데이터 조회"""
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B).worksheet("광기데이터")
            rows = sheet.get_all_values()
            madness_list = []
            for row in rows[1:]:
                if len(row) >= 2:
                    madness_list.append({
                        "madness_id": row[0],
                        "name": row[1],
                        "description": row[2],
                        "effect_type": row[3],
                        "effect_value": row[4],
                        "recovery_difficulty": row[5],
                        "acquisition_condition": row[6]
                    })
            return madness_list
        except Exception as e:
            logger.error(f"Error getting madness data: {e}")
            return []

    # =========================================================================
    # 4. Spreadsheet C: 조사/월드맵
    # =========================================================================

    def fetch_investigation_data(self):
        """[Sheet C] 조사 데이터 파싱"""
        if not self.client: return {}
        try:
            spreadsheet = self.client.open_by_key(config.SPREADSHEET_ID_C)
            worksheets = spreadsheet.worksheets()
            world_map = {}
            
            for sheet in worksheets:
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
                last_seen = [""] * 8 
                
                for row in rows[1:]:
                    if not any(row): continue
                    
                    # Fill Down Logic (A~E)
                    for i in range(5):
                        val = row[i].strip() if len(row) > i else ""
                        if val:
                            if last_seen[i] != val:
                                for j in range(i + 1, 8): last_seen[j] = ""
                            last_seen[i] = val
                    
                    # F, G, H
                    for i in range(5, 8):
                        val = row[i].strip() if len(row) > i else ""
                        if val: last_seen[i] = val

                    location_path = [x for x in last_seen[0:5] if x]
                    item_name = last_seen[5] # F
                    button_text = last_seen[6] # G
                    interaction_type = last_seen[7] # H
                    
                    if not location_path: continue

                    current_level = category_root["children"]
                    path_id = category_name
                    
                    for depth, loc_name in enumerate(location_path):
                        path_id = f"{path_id}_{loc_name}"
                        if loc_name not in current_level:
                            is_channel = (depth == 0)
                            current_level[loc_name] = {
                                "id": path_id,
                                "name": loc_name,
                                "description": "",
                                "children": {},
                                "items": [], 
                                "type": "location",
                                "is_channel": is_channel
                            }
                        target_location = current_level[loc_name]
                        current_level = current_level[loc_name]["children"]
                    
                    variant_data = {
                        "condition": row[8].strip() if len(row) > 8 else "",
                        "result_crit_success": row[12].strip() if len(row) > 12 else "",
                        "result_success": row[13].strip() if len(row) > 13 else "",
                        "result_fail": row[14].strip() if len(row) > 14 else "",
                        "result_crit_fail": row[15].strip() if len(row) > 15 else "",
                        "description": row[16].strip() if len(row) > 16 else ""
                    }
                    
                    if item_name:
                        target_location["items"].append({
                            "name": item_name,
                            "button_text": button_text,
                            "type": interaction_type,
                            "variants": [variant_data]
                        })
            
            self.cached_data['investigation'] = world_map
            return world_map
        except Exception as e:
            logger.error(f"Error fetching investigation data: {e}")
            return {}

    # =========================================================================
    # 5. Spreadsheet D: 동적 로그
    # =========================================================================

    def sync_db_to_sheets(self, db_manager):
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

            # DB 데이터 가져오기
            user_states = db_manager.fetch_all("SELECT * FROM user_state")
            # DB: user_id, hp, sanity, hunger, infection, last_hunger, last_sanity
            
            metadata = self.get_metadata_map()
            
            # DB 데이터를 딕셔너리로 변환 (Key: Discord ID)
            db_data_map = {}
            for state in user_states:
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
            
            # (다른 시트들도 유사하게 구현 가능: 유저_인벤토리, 유저_단서 등)
            
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

    def register_item_metadata(self, name, type_, description):
        """[Sheet B] 아이템 데이터 등록"""
        try:
            sheet = self.client.open_by_key(config.SPREADSHEET_ID_B)
            ws = sheet.worksheet("아이템데이터")
            ws.append_row([name, name, type_, description]) # ID는 이름으로 대체하거나 자동생성 필요
        except Exception as e:
            logger.error(f"Error registering item: {e}")
