import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "venue_db.json"

with DB_PATH.open("r", encoding="utf-8") as f:
    VENUE_DB = json.load(f)


def lookup_venue(raw_name: str):
    """根据 venue 名称做几轮匹配：精确、别名、模糊。
    返回 (found: bool, data: dict)。
    """
    name = (raw_name or "").strip()
    if not name:
        return False, {
            "venue": "",
            "overall_level": "Unknown",
            "notes": "Empty venue name.",
            "recognised_as_target": False,
        }

    # 1. 精确匹配 key，比如 "CHI"
    if name in VENUE_DB:
        return True, VENUE_DB[name]

    lower_name = name.lower()

    # 2. 别名匹配
    for k, v in VENUE_DB.items():
        for alias in v.get("alias", []):
            if lower_name == alias.lower():
                return True, v

    # 3. 模糊匹配 full_name（包含关系）
    for k, v in VENUE_DB.items():
        full = v.get("full_name", "")
        if lower_name in full.lower():
            return True, v

    # 4. 全部找不到
    return False, {
        "venue": name,
        "overall_level": "Unknown",
        "notes": "This venue is not in the curated database yet.",
        "recognised_as_target": False
    }
