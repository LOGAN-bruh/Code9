"""Configuration helper for Code9.

Provides schema-aware load/save with conservative value normalization.
"""

import json
import os
import sys
from typing import Any, Dict


class Config:
    VALID_INSERT_MODES = {"replace", "append", "noop"}
    VALID_RUN_MODES = {"temp", "active_file", "workspace"}

    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {}
        self.defaults = {
            "username": "Coder",
            "auto_run_coding": True,
            "insert_mode": "replace",
            "run_mode": "workspace",
            "enable_typewriter": True,
            "general_max_tokens": 320,
            "coding_max_tokens": 900,
            "run_timeout_sec": 60,
            "stop_on_bad_response": True,
            "require_code_block_for_injection": True,
            "persist_session": True,
            "restore_last_file": False,
            "last_opened_file": "",
            "last_opened_files": [],
            "preferred_coding_model": "",
            "preferred_shinzen_model": "",
            "auto_install_missing_imports": False,
            "auto_format_on_paste": True,
            "show_ai_diff": True,
            "theme_mode": "auto",
            "python_exec_path": sys.executable,
            "project_root": "",
            "workspace_max_files": 400,
            "context_accumulate_every": 4,
        }
        self.load()

    @staticmethod
    def _coerce_int(value: Any, min_v: int, max_v: int, fallback: int) -> int:
        try:
            n = int(str(value).strip())
            return max(min_v, min(max_v, n))
        except Exception:
            return fallback

    @staticmethod
    def _coerce_str(value: Any, fallback: str = "") -> str:
        if value is None:
            return fallback
        try:
            return str(value)
        except Exception:
            return fallback

    @staticmethod
    def _coerce_str_list(value: Any) -> list:
        if isinstance(value, (list, tuple)):
            out = []
            for item in value:
                try:
                    text = str(item).strip()
                    if text:
                        out.append(text)
                except Exception:
                    continue
            return out
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _normalize_data(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(self.defaults)
        data.update(raw or {})

        data["username"] = self._coerce_str(data.get("username"), self.defaults["username"]).strip() or self.defaults["username"]
        data["auto_run_coding"] = bool(data.get("auto_run_coding", self.defaults["auto_run_coding"]))
        data["enable_typewriter"] = bool(data.get("enable_typewriter", self.defaults["enable_typewriter"]))
        data["stop_on_bad_response"] = bool(data.get("stop_on_bad_response", self.defaults["stop_on_bad_response"]))
        data["require_code_block_for_injection"] = bool(data.get("require_code_block_for_injection", self.defaults["require_code_block_for_injection"]))
        data["persist_session"] = bool(data.get("persist_session", self.defaults["persist_session"]))
        data["restore_last_file"] = bool(data.get("restore_last_file", self.defaults["restore_last_file"]))
        data["auto_install_missing_imports"] = bool(data.get("auto_install_missing_imports", self.defaults["auto_install_missing_imports"]))
        data["auto_format_on_paste"] = bool(data.get("auto_format_on_paste", self.defaults["auto_format_on_paste"]))
        data["show_ai_diff"] = bool(data.get("show_ai_diff", self.defaults["show_ai_diff"]))

        insert_mode = self._coerce_str(data.get("insert_mode"), self.defaults["insert_mode"]).strip().lower()
        data["insert_mode"] = insert_mode if insert_mode in self.VALID_INSERT_MODES else self.defaults["insert_mode"]

        run_mode = self._coerce_str(data.get("run_mode"), self.defaults["run_mode"]).strip().lower()
        data["run_mode"] = run_mode if run_mode in self.VALID_RUN_MODES else self.defaults["run_mode"]

        theme_mode = self._coerce_str(data.get("theme_mode"), self.defaults["theme_mode"]).strip().lower()
        data["theme_mode"] = theme_mode if theme_mode in {"auto", "light", "dark"} else self.defaults["theme_mode"]

        data["coding_max_tokens"] = self._coerce_int(
            data.get("coding_max_tokens", self.defaults["coding_max_tokens"]),
            120,
            4000,
            self.defaults["coding_max_tokens"],
        )
        data["general_max_tokens"] = self._coerce_int(
            data.get("general_max_tokens", self.defaults["general_max_tokens"]),
            80,
            4000,
            self.defaults["general_max_tokens"],
        )
        data["run_timeout_sec"] = self._coerce_int(
            data.get("run_timeout_sec", self.defaults["run_timeout_sec"]),
            5,
            600,
            self.defaults["run_timeout_sec"],
        )

        data["preferred_coding_model"] = self._coerce_str(data.get("preferred_coding_model"), "").strip()
        data["preferred_shinzen_model"] = self._coerce_str(data.get("preferred_shinzen_model"), "").strip()
        data["last_opened_file"] = self._coerce_str(data.get("last_opened_file"), "").strip()
        data["last_opened_files"] = self._coerce_str_list(data.get("last_opened_files", []))
        data["project_root"] = self._coerce_str(data.get("project_root"), "").strip()
        data["workspace_max_files"] = self._coerce_int(
            data.get("workspace_max_files", self.defaults["workspace_max_files"]),
            25,
            3000,
            self.defaults["workspace_max_files"],
        )
        data["context_accumulate_every"] = self._coerce_int(
            data.get("context_accumulate_every", self.defaults["context_accumulate_every"]),
            2,
            12,
            self.defaults["context_accumulate_every"],
        )

        py_exec = self._coerce_str(data.get("python_exec_path"), self.defaults["python_exec_path"]).strip()
        data["python_exec_path"] = py_exec if py_exec else self.defaults["python_exec_path"]

        return data

    def load(self):
        if not os.path.exists(self.path):
            self.data = dict(self.defaults)
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.data = self._normalize_data(raw if isinstance(raw, dict) else {})
        except Exception:
            self.data = dict(self.defaults)

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            payload = self._normalize_data(self.data)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            self.data = payload
        except Exception:
            pass

    def get(self, key: str, default: Any = None):
        return self.data.get(key, self.defaults.get(key, default))

    def set(self, key: str, value: Any):
        self.data[key] = value
