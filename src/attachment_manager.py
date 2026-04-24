"""Helpers to build small, safe attachment payloads from UI text areas.

These helpers accept strings (runtime output, editor content, general chat text)
and return trimmed, labeled payloads suitable for inserting into a chat prompt.
"""
from typing import Optional


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
