"""Helpers to build small, safe attachment payloads from UI text areas.

These helpers accept strings (runtime output, editor content, general chat text)
and return trimmed, labeled payloads suitable for inserting into a chat prompt.
"""
import os
from typing import Iterable, Optional


class AttachmentManager:
    @staticmethod
    def _clip_text(text: str, max_chars: int) -> str:
        val = (text or "").strip()
        if len(val) <= max_chars:
            return val
        return val[-max_chars:]

    @staticmethod
    def prepare_runtime_snippet(output_text: str, max_chars: int = 1200) -> Optional[str]:
        if not output_text or not output_text.strip():
            return None
        snippet = AttachmentManager._clip_text(output_text, max_chars)
        return f"--- Runtime output (truncated) ---\n{snippet}\n--- end ---"

    @staticmethod
    def prepare_engine_snippet(code_text: str, max_chars: int = 1600) -> Optional[str]:
        if not code_text or not code_text.strip():
            return None
        snippet = (code_text or "").strip()[:max_chars]
        return f"--- Engine code (truncated) ---\n```python\n{snippet}\n```\n--- end ---"

    @staticmethod
    def prepare_error_snippet(output_text: str, max_lines: int = 80) -> Optional[str]:
        if not output_text or not output_text.strip():
            return None
        lines = [
            l
            for l in output_text.splitlines()
            if (
                l.strip().startswith("ERR:")
                or "Traceback" in l
                or "Exception" in l
                or "Error:" in l
                or "SyntaxError" in l
            )
        ]
        if not lines:
            return None
        snippet = "\n".join(lines[-max_lines:])
        return f"--- Errors (truncated) ---\n{snippet}\n--- end ---"

    @staticmethod
    def prepare_chat_snippet(chat_text: str, max_chars: int = 1200) -> Optional[str]:
        if not chat_text or not chat_text.strip():
            return None
        snippet = AttachmentManager._clip_text(chat_text, max_chars)
        return f"--- General AI chat (truncated) ---\n{snippet}\n--- end ---"

    @staticmethod
    def prepare_shinzen_snippet(suggestion_text: str, max_chars: int = 320) -> Optional[str]:
        if not suggestion_text or not suggestion_text.strip():
            return None
        snippet = AttachmentManager._clip_text(suggestion_text, max_chars)
        return f"--- Shinzen suggestion ---\n{snippet}\n--- end ---"

    @staticmethod
    def _rel(path: str, root: Optional[str] = None) -> str:
        try:
            if root:
                rel = os.path.relpath(path, root)
                if rel and not rel.startswith(".."):
                    return rel
            return os.path.basename(path) or path
        except Exception:
            return os.path.basename(path) or str(path)

    @staticmethod
    def prepare_file_inventory(
        paths: Iterable[str],
        root: Optional[str] = None,
        max_files: int = 120,
        label: str = "Project file inventory",
    ) -> Optional[str]:
        clean_paths = []
        seen = set()
        for path in paths or []:
            try:
                if not path:
                    continue
                abs_path = os.path.abspath(path)
                if abs_path in seen:
                    continue
                seen.add(abs_path)
                clean_paths.append(abs_path)
            except Exception:
                continue

        if not clean_paths:
            return None

        shown = clean_paths[:max(1, int(max_files))]
        lines = [f"- {AttachmentManager._rel(path, root)}" for path in shown]
        remaining = len(clean_paths) - len(shown)
        if remaining > 0:
            lines.append(f"- ...and {remaining} more file(s)")
        return f"--- {label} ---\n" + "\n".join(lines) + "\n--- end ---"

    @staticmethod
    def prepare_file_snippet(path: str, root: Optional[str] = None, max_chars: int = 1800) -> Optional[str]:
        try:
            if not path or not os.path.isfile(path):
                return None
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read(max_chars + 1)
            if not data.strip():
                return None
            clipped = data[:max_chars]
            if len(data) > max_chars:
                clipped = clipped.rstrip() + "\n...[truncated]"
            rel = AttachmentManager._rel(path, root)
            return f"--- File: {rel} ---\n{clipped}\n--- end ---"
        except Exception:
            return None
