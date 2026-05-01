"""Tiny rolling context memory for Code9 model prompts.

This is not model training. It borrows the "gradient accumulation" idea:
collect small observations one by one, promote them only after enough chunks
arrive, and keep the saved memory tiny so prompts do not balloon RAM usage.
"""

import hashlib
import json
import os
import re
import time
from typing import Dict, List


class ContextAccumulator:
    def __init__(self, path: str, promote_every: int = 4, max_memory_items: int = 24):
        self.path = path
        self.promote_every = max(2, int(promote_every or 4))
        self.max_memory_items = max(6, int(max_memory_items or 24))
        self.data = {"pending": {}, "memory": {}}
        self.load()

    def load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self.data["pending"] = raw.get("pending", {}) if isinstance(raw.get("pending", {}), dict) else {}
                    self.data["memory"] = raw.get("memory", {}) if isinstance(raw.get("memory", {}), dict) else {}
        except Exception:
            self.data = {"pending": {}, "memory": {}}

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def _clean_text(text: str, max_chars: int = 900) -> str:
        clean = re.sub(r"\s+", " ", text or "").strip()
        if len(clean) > max_chars:
            clean = clean[:max_chars].rsplit(" ", 1)[0].rstrip() + "..."
        return clean

    @staticmethod
    def _digest(text: str) -> str:
        return hashlib.sha1((text or "").encode("utf-8", errors="ignore")).hexdigest()[:12]

    def _summarize_chunk(self, text: str, source: str = "") -> str:
        clean = self._clean_text(text, max_chars=700)
        if not clean:
            return ""
        code_markers = []
        for marker in ("def ", "class ", "import ", "Traceback", "SyntaxError", "TODO", "FIXME"):
            if marker in clean:
                code_markers.append(marker.strip())
        prefix = f"{source}: " if source else ""
        if code_markers:
            prefix += "[" + ", ".join(code_markers[:4]) + "] "
        return prefix + clean

    def add(self, bucket: str, text: str, source: str = "") -> bool:
        """Add a small chunk. Returns True when memory was promoted."""
        bucket = (bucket or "general").strip().lower()
        summary = self._summarize_chunk(text, source=source)
        if not summary:
            return False

        pending: Dict[str, List[dict]] = self.data.setdefault("pending", {})
        items = pending.setdefault(bucket, [])
        digest = self._digest(summary)
        if any(item.get("digest") == digest for item in items[-8:]):
            return False
        items.append({"digest": digest, "summary": summary, "ts": time.time()})
        pending[bucket] = items[-self.promote_every :]

        promoted = False
        if len(pending[bucket]) >= self.promote_every:
            promoted = True
            memory = self.data.setdefault("memory", {}).setdefault(bucket, [])
            combined = " | ".join(item.get("summary", "") for item in pending[bucket] if item.get("summary"))
            memory.append({
                "digest": self._digest(combined),
                "summary": self._clean_text(combined, max_chars=900),
                "ts": time.time(),
            })
            self.data["memory"][bucket] = memory[-self.max_memory_items :]
            self.data["pending"][bucket] = []

        self.save()
        return promoted

    def prompt_context(self, bucket: str, max_items: int = 5) -> str:
        bucket = (bucket or "general").strip().lower()
        memory = self.data.get("memory", {}).get(bucket, [])
        if not memory:
            return ""
        items = memory[-max(1, int(max_items)) :]
        lines = [f"- {item.get('summary', '')}" for item in items if item.get("summary")]
        if not lines:
            return ""
        return "Accumulated project memory:\n" + "\n".join(lines)

