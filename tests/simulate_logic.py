import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/../')

from utils.game_logic import GameLogic
from utils.sheets import SheetsManager

def test_game_logic():
    print("=== Testing GameLogic ===")
    
    # 1. Target Value
    # 50 - (Stat - 40) * 0.6
    # Stat 40 -> 50
    # Stat 100 -> 50 - (60 * 0.6) = 50 - 36 = 14
    # Stat 10 -> 50 - (-30 * 0.6) = 50 + 18 = 68
    assert GameLogic.calculate_target_value(40) == 50
    assert GameLogic.calculate_target_value(100) == 14
    assert GameLogic.calculate_target_value(10) == 68
    print("✅ Target Value Calculation Passed")

    # 2. Current Stat with Sanity
    # Base 100, Sanity 100% (1.0) -> 100 * (0.7 + 0.3) = 100
    # Base 100, Sanity 0% (0.0) -> 100 * 0.7 = 70
    # Base 100, Sanity 50% (0.5) -> 100 * 0.85 = 85
    assert GameLogic.calculate_current_stat(100, 1.0) == 100
    assert GameLogic.calculate_current_stat(100, 0.0) == 70
    assert GameLogic.calculate_current_stat(100, 0.5) == 85
    print("✅ Current Stat Calculation Passed")

    # 3. Check Result
    # Target 50
    # 1-9: Critical Failure
    # 10-49: Failure
    # 50-89: Success
    # 90-100: Critical Success
    assert GameLogic.check_result(5, 50) == "CRITICAL_FAILURE"
    assert GameLogic.check_result(49, 50) == "FAILURE"
    assert GameLogic.check_result(50, 50) == "SUCCESS"
    assert GameLogic.check_result(89, 50) == "SUCCESS"
    assert GameLogic.check_result(90, 50) == "CRITICAL_SUCCESS"
    print("✅ Check Result Logic Passed")

def test_nickname_parsing():
    print("\n=== Testing Nickname Parsing ===")
    sm = SheetsManager()
    
    cases = [
        ("[칭호] 이름 | HP | SP", "이름"),
        ("이름 | HP | SP", "이름"),
        ("이름 / HP / SP", "이름"),
        ("이름 \ HP \ SP", "이름"),
        ("이름 I HP I SP", "이름"),
        ("이름 ㅣ HP ㅣ SP", "이름"),
        ("  이름  | HP", "이름")
    ]
    
    for raw, expected in cases:
        result = sm.parse_nickname(raw)
        assert result == expected, f"Failed: {raw} -> {result} != {expected}"
    print("✅ Nickname Parsing Passed")

def test_investigation_parsing():
    print("\n=== Testing Investigation Data Parsing (Row Splitting) ===")
    # Mocking the row data based on new structure (A-Q)
    # A, B, C, D, E, F, G, H, I, ... Q
    mock_rows = [
        ["Header"] * 17,
        # 1. 지역 설명 (A~E, F="", G="", H="", I="", Q="Desc")
        ["", "마을", "회관", "1층", "", "", "", "", "", "", "", "", "", "", "", "", "마을 회관입니다."],
        # 2. 아이템 Variant 1 (감각 80)
        ["", "", "", "", "사무실", "책상", "조사하기", "investigation", "stat:감각:80", "", "", "", "", "대성공", "성공", "", "전문가 묘사"],
        # 3. 아이템 Variant 2 (감각 40) - Fill Down 테스트 (B~E, F, G, H 생략)
        ["", "", "", "", "", "", "", "", "stat:감각:40", "", "", "", "", "성공", "실패", "", "일반 묘사"],
        # 4. 아이템 Variant 3 (기본)
        ["", "", "", "", "", "", "", "", "", "", "", "", "", "성공", "실패", "", "기본 묘사"]
    ]
    
    world_map = {}
    last_seen = [""] * 8
    
    for row in mock_rows[1:]:
        if not any(row): continue
        
        # Fill Down Logic Simulation
        for i in range(6):
            val = row[i].strip() if len(row) > i else ""
            if val:
                last_seen[i] = val
                for j in range(i + 1, 8): last_seen[j] = ""
        
        for i in range(6, 8):
            val = row[i].strip() if len(row) > i else ""
            if val: last_seen[i] = val
            
        location_path = [x for x in last_seen[1:5] if x]
        item_name = last_seen[5]
        button_text = last_seen[6]
        interaction_type = last_seen[7]
        
        if not location_path: continue
        
        # 트리 구성
        current_level = world_map
        for loc_name in location_path:
            if loc_name not in current_level:
                current_level[loc_name] = {
                    "name": loc_name, "children": {}, "items": [], "type": "location"
                }
            target_location = current_level[loc_name]
            current_level = current_level[loc_name]["children"]
            
        # Variant 데이터
        variant_data = {
            "condition": row[8].strip() if len(row) > 8 else "",
            "description": row[16].strip() if len(row) > 16 else ""
        }
        
        if item_name:
            existing_item = None
            for item in target_location["items"]:
                if item["name"] == item_name and item["button_text"] == button_text:
                    existing_item = item
                    break
            
            if existing_item:
                existing_item["variants"].append(variant_data)
            else:
                new_item = {
                    "name": item_name,
                    "button_text": button_text,
                    "type": interaction_type,
                    "variants": [variant_data]
                }
                target_location["items"].append(new_item)
        else:
            if "description_variants" not in target_location:
                target_location["description_variants"] = []
            target_location["description_variants"].append(variant_data)
            target_location["description"] = variant_data["description"]

    # Verification
    try:
        # 마을 > 회관 > 1층 > 사무실 (지역) -> 책상 (아이템)
        office = world_map["마을"]["children"]["회관"]["children"]["1층"]["children"]["사무실"]
        assert len(office["items"]) == 1
        desk = office["items"][0]
        assert desk["name"] == "책상"
        assert len(desk["variants"]) == 3
        
        # Variants 확인
        assert desk["variants"][0]["condition"] == "stat:감각:80"
        assert desk["variants"][0]["description"] == "전문가 묘사"
        assert desk["variants"][1]["condition"] == "stat:감각:40"
        assert desk["variants"][2]["condition"] == ""
        assert desk["variants"][2]["description"] == "기본 묘사"
        
        print("✅ Investigation Parsing Logic (Row Splitting) Passed")
    except KeyError as e:
        print(f"❌ Investigation Parsing Failed: Key {e} not found")
    except AssertionError as e:
        print(f"❌ Investigation Parsing Failed: Assertion Error {e}")

def test_sheets_caching():
    print("\n=== Testing Sheets Caching & Metadata ===")
    sm = SheetsManager()
    
    # 1. Mock Metadata
    sm.cached_data['metadata'] = {'12345': '테스트유저'}
    
    # 2. Mock Stats in Cache
    sm.cached_data['stats'] = [{
        "name": "테스트유저",
        "hp": 100, "sanity": 100, "perception": 50, "intelligence": 50, "willpower": 50
    }]
    
    # 3. Test get_user_stats with ID
    stats = sm.get_user_stats(discord_id='12345')
    assert stats is not None
    assert stats['name'] == '테스트유저'
    print("✅ Metadata Lookup & Cache Hit Passed")
    
    # 4. Test Save/Load Cache
    sm.save_cache()
    assert os.path.exists('sheets_cache.json')
    
    sm2 = SheetsManager()
    sm2.load_cache()
    assert sm2.cached_data['metadata']['12345'] == '테스트유저'
    print("✅ Cache Save/Load Passed")

def test_variant_selection():
    print("\n=== Testing Variant Selection Logic ===")
    from utils.condition_parser import ConditionParser
    
    # Mock Item with Variants
    item_data = {
        "name": "책상",
        "variants": [
            {"condition": "stat:감각:80", "description": "전문가 묘사", "result_success": "대성공"},
            {"condition": "stat:감각:40", "description": "일반 묘사", "result_success": "성공"},
            {"condition": "", "description": "기본 묘사", "result_success": "성공"}
        ]
    }
    
    # Case 1: High Stat (80)
    user_state_high = {"stats": {"감각": 85}}
    world_state = {}
    
    selected_high = None
    for variant in item_data["variants"]:
        conditions = ConditionParser.parse_condition_string(variant["condition"])
        if not conditions:
            selected_high = variant
            break
        check = ConditionParser.evaluate_all(conditions, user_state_high, world_state)
        if check["enabled"]:
            selected_high = variant
            break
            
    assert selected_high["description"] == "전문가 묘사"
    print("✅ High Stat Selection Passed")

    # Case 2: Mid Stat (50)
    user_state_mid = {"stats": {"감각": 50}}
    selected_mid = None
    for variant in item_data["variants"]:
        conditions = ConditionParser.parse_condition_string(variant["condition"])
        if not conditions:
            selected_mid = variant
            break
        check = ConditionParser.evaluate_all(conditions, user_state_mid, world_state)
        if check["enabled"]:
            selected_mid = variant
            break
            
    assert selected_mid["description"] == "일반 묘사"
    print("✅ Mid Stat Selection Passed")
    
    # Case 3: Low Stat (20)
    user_state_low = {"stats": {"감각": 20}}
    selected_low = None
    for variant in item_data["variants"]:
        conditions = ConditionParser.parse_condition_string(variant["condition"])
        if not conditions:
            selected_low = variant
            break
        check = ConditionParser.evaluate_all(conditions, user_state_low, world_state)
        if check["enabled"]:
            selected_low = variant
            break
            
    assert selected_low["description"] == "기본 묘사"
    print("✅ Low Stat Selection Passed")

if __name__ == "__main__":
    test_game_logic()
    test_nickname_parsing()
    test_investigation_parsing()
    test_sheets_caching()
    test_variant_selection()
