# ✅ ml_logger.py — Simple behavior tracker (JSONL format)

import json
import os
from datetime import datetime

# Create ml_data folder if missing
LOG_DIR = "ml_data"
LOG_FILE = os.path.join(LOG_DIR, "user_behavior.jsonl")

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def log_user_action(action_type: str, metadata: dict):
    """
    Appends a JSON object to user_behavior.jsonl with timestamp.
    - action_type: "view_log", "analyze_log", "search", etc.
    - metadata: any extra details like filename, filter, tab
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "action": action_type,
        "details": metadata
    }

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"[ml_logger] Failed to write log: {e}")

