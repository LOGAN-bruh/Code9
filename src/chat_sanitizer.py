"""Sanitization and code-extraction helpers for chat responses.

Contains ChatSanitizer to remove role markers, collapse repeated paragraphs, and
extract fenced Python code blocks. These utilities mirror logic in the UI but
are encapsulated for reuse and testability.
"""
import re
from typing import List


class ChatSanitizer:
    @staticmethod
    def sanitize_response(text: str, mode: str = None) -> str:
        if not text:
            return text
        # remove simple role markers
        lines = [ln for ln in text.splitlines() if ln.strip() not in ("User:", "Assistant:", "General AI:", "Coding AI:")]
        # collapse consecutive identical lines
        collapsed = []
        for ln in lines:
            if collapsed and ln.strip() == collapsed[-1].strip():
                continue
            collapsed.append(ln)
        result = "\n".join(collapsed).strip()

        # coding mode: truncate after final fenced code block + one short concluding paragraph
        if mode == "coding":
            try:
                pattern = r"```([a-zA-Z0-9_+\-]*)\s*\n([\s\S]*?)```"
                matches = list(re.finditer(pattern, result))
                if matches:
                    last = matches[-1]
                    end_idx = last.end()
                    after = result[end_idx:]
                    concl = ""
                    if after.strip():
                        # first paragraph only
                        paras = re.split(r"\n\s*\n", after.strip())
                        if paras:
                            concl = paras[0].strip()[:600]
                    truncated = result[:end_idx]
                    if concl:
                        truncated = truncated + "\n\n" + concl
                    result = truncated
            except Exception:
                pass

        # dedupe consecutive paragraphs
        paras = [p.strip() for p in re.split(r"\n\s*\n", result) if p.strip()]
        dedup_paras = []
        for p in paras:
            if dedup_paras and p == dedup_paras[-1]:
                continue
            dedup_paras.append(p)
        final = "\n\n".join(dedup_paras)

        # final safeguard: if the text is repeating large blocks, keep first occurrence
        if len(final) > 400:
            half = final[: len(final) // 2]
            if half in final[len(half) :]:
                final = final[: len(final) // 2]
        return final

    @staticmethod
    def extract_code_blocks(text: str) -> List[str]:
        blocks: List[str] = []
        try:
            pattern = r"```([a-zA-Z0-9_+\-]*)\s*\n([\s\S]*?)```"
            all_blocks = []
            for match in re.finditer(pattern, text):
                lang = (match.group(1) or "").strip().lower()
                code = (match.group(2) or "").strip()
                if code:
                    all_blocks.append((lang, code + "\n"))

            if all_blocks:
                py_blocks = [code for lang, code in all_blocks if lang in {"", "python", "py"}]
                return py_blocks if py_blocks else [code for _, code in all_blocks]

            # fallback: heuristics
            if ChatSanitizer._looks_like_python(text):
                blocks.append(text.strip() + "\n")
        except Exception:
            pass
        return blocks

    @staticmethod
    def _looks_like_python(text: str) -> bool:
        if "\n" not in text:
            return False
        markers = ["def ", "import ", "print(", "if __name__", "class ", "return ", "for ", "while "]
        score = sum(1 for m in markers if m in text)
        return score >= 2
