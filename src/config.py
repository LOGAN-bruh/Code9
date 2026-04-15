"""Simple configuration helper for Code9.

Provides a tiny Config class for load/save of user prefs used by the UI.
"""
import json
import os
from typing import Any, Dict


class Config:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {}
        self.defaults = {
            "auto_run_coding": True,
            "insert_mode": "replace",
            "run_mode": "temp",
            "enable_typewriter": True,
            "general_max_tokens": 320,
            "coding_max_tokens": 900,
            "run_timeout_sec": 60,
            "persist_session": True,
            "restore_last_file": False,
            "last_opened_file": "",
        }
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            self.data = dict(self.defaults)
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = dict(self.defaults)

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def get(self, key: str, default: Any = None):
        return self.data.get(key, self.defaults.get(key, default))

    def set(self, key: str, value: Any):
        self.data[key] = value
