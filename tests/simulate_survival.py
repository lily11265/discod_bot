import logging

# Mocking DB and Sheets for logic testing
class MockDB:
    def __init__(self):
        self.data = {
            "user_state": {
                1: {"user_id": 1, "hunger": 100, "sanity": 50, "last_sanity_recovery": None}
            },
            "user_inventory": {
                1: {"건빵": 2}
            }
        }
    
    def fetch_one(self, query, params):
        if "user_state" in query:
            uid = params[0]
            s = self.data["user_state"].get(uid)
            if s:
                return (s["user_id"], 100, s["sanity"], s["hunger"], 0, None, s["last_sanity_recovery"], 0)
        if "user_inventory" in query:
            uid = params[0]
            item = params[1]
            inv = self.data["user_inventory"].get(uid, {}).get(item)
            if inv: return (inv,)
        return None

    def execute_query(self, query, params):
        if "UPDATE user_state" in query:
            # Simple mock update
            pass

class MockSheets:
    def get_user_stats(self, discord_id):
        return {"willpower": 50, "intelligence": 50}

def test_hunger_logic():
    print("\n=== Testing Hunger Logic ===")
    # Formula: 10 + (Willpower * 0.04)
    willpower = 50
    decay = 10 + (willpower * 0.04)
    expected = 12.0
    assert decay == expected
    print(f"✅ Decay Calculation: Willpower {willpower} -> Decay {decay}")

    # Eating
    current_hunger = 80
    item_recovery = 15
    new_hunger = min(100, current_hunger + item_recovery)
    assert new_hunger == 95
    print(f"✅ Eating: {current_hunger} + {item_recovery} -> {new_hunger}")

def test_sanity_logic():
    print("\n=== Testing Sanity Logic ===")
    # Threshold: 30 + (Intelligence * 0.2)
    intelligence = 50
    threshold = 30 + (intelligence * 0.2)
    expected_threshold = 40.0
    assert threshold == expected_threshold
    print(f"✅ Threshold Calculation: Int {intelligence} -> Threshold {threshold}")

    # Recovery: 10 + (Willpower / 10)
    willpower = 50
    recovery = 10 + (willpower / 10)
    expected_recovery = 15.0
    assert recovery == expected_recovery
    print(f"✅ Recovery Calculation: Will {willpower} -> Recovery {recovery}")

    # Check Condition
    hunger = 45
    can_recover = hunger >= threshold
    assert can_recover is True
    print(f"✅ Recovery Condition: Hunger {hunger} >= Threshold {threshold} -> {can_recover}")

if __name__ == "__main__":
    test_hunger_logic()
    test_sanity_logic()
