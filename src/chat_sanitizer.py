"""Sanitization and code-extraction helpers for chat responses.

Focuses on reducing repetitive or nonsensical model output.
"""

import ast
import re
from typing import Dict, List, Tuple


class ChatSanitizer:
    @staticmethod
    def sanitize_response(text: str, mode: str = None) -> str:
        if not text:
            return text

        lines = [
            ln for ln in text.splitlines()
            if ln.strip() not in ("User:", "Assistant:", "General AI:", "Coding AI:", "Shinzen:")
        ]

        # Collapse consecutive identical lines
        collapsed = []
        for ln in lines:
            if collapsed and ln.strip() == collapsed[-1].strip():
                continue
            collapsed.append(ln)

        result = "\n".join(collapsed).strip()

        # Remove obvious repeated sentence loops
        result = ChatSanitizer._dedupe_repeated_sentences(result)

        if mode == "coding":
            result = ChatSanitizer._truncate_after_last_code_block(result)

        # Dedupe repeated paragraphs
        paras = [p.strip() for p in re.split(r"\n\s*\n", result) if p.strip()]
        dedup_paras = []
        for p in paras:
            if dedup_paras and p == dedup_paras[-1]:
                continue
            dedup_paras.append(p)

        final = "\n\n".join(dedup_paras)

        # Keep response compact and avoid extreme tails
        if len(final) > 12000:
            final = final[:12000].rstrip() + "\n\n...[truncated]"

        return final

    @staticmethod
    def _truncate_after_last_code_block(text: str) -> str:
        try:
            pattern = r"```([a-zA-Z0-9_+\-]*)\s*\n([\s\S]*?)```"
            matches = list(re.finditer(pattern, text))
            if not matches:
                return text

            last = matches[-1]
            end_idx = last.end()
            after = text[end_idx:]
            concl = ""
            if after.strip():
                paras = re.split(r"\n\s*\n", after.strip())
                if paras:
                    concl = paras[0].strip()[:350]

            truncated = text[:end_idx]
            if concl:
                truncated = truncated + "\n\n" + concl
            return truncated
        except Exception:
            return text

    @staticmethod
    def _dedupe_repeated_sentences(text: str) -> str:
        # Split by sentence-ish boundaries while preserving line breaks roughly.
        chunks = re.split(r"(?<=[\.!\?])\s+", text)
        out = []
        seen = set()
        for ch in chunks:
            norm = re.sub(r"\s+", " ", ch).strip().lower()
            if not norm:
                continue
            # Skip only if it's already seen and substantial.
            if len(norm) > 30 and norm in seen:
                continue
            out.append(ch)
            seen.add(norm)
        return " ".join(out).replace(" \n", "\n")

    @staticmethod
    def is_nonsense(text: str, mode: str = "coding") -> bool:
        if not text:
            return True

        stripped = text.strip()
        if len(stripped) < 8:
            return True

        # Excessive repeated lines/paragraphs
        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        if len(lines) >= 6:
            uniq = len(set(lines))
            if uniq / max(1, len(lines)) < 0.45:
                return True

        # Strong token repetition in longer outputs
        words = re.findall(r"[A-Za-z_]{2,}", stripped.lower())
        if len(words) >= 80:
            uniq_words = len(set(words))
            if uniq_words / len(words) < 0.2:
                return True

        # Coding mode should usually include code block or look like python for longer responses
        if mode == "coding" and len(stripped) > 180:
            has_block = "```" in stripped
            if not has_block and not ChatSanitizer._looks_like_python(stripped):
                return True

        return False

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

            if ChatSanitizer._looks_like_python(text):
                blocks.append(text.strip() + "\n")
        except Exception:
            pass
        return blocks

    @staticmethod
    def _normalize_code_text(code: str) -> str:
        if not code:
            return ""
        cleaned = code.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"^\s*python\s*\n", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip("\n") + "\n"

    @staticmethod
    def validate_python(code: str) -> Tuple[bool, str]:
        if not code or not code.strip():
            return False, "No Python code found."
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            line = getattr(e, "lineno", "?")
            msg = getattr(e, "msg", str(e))
            return False, f"Syntax error at line {line}: {msg}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _score_code_candidate(code: str) -> int:
        text = code or ""
        if not text.strip():
            return -1
        if not ChatSanitizer._is_plausible_python(text):
            return -1
        markers = ["def ", "class ", "import ", "if ", "for ", "while ", "return ", "try:"]
        marker_score = sum(1 for m in markers if m in text) * 10
        valid, _ = ChatSanitizer.validate_python(text)
        parse_bonus = 120 if valid else 0
        length_bonus = min(900, len(text))
        return parse_bonus + marker_score + length_bonus

    @staticmethod
    def _choose_best_code_block(blocks: List[str]) -> str:
        if not blocks:
            return ""
        ranked = []
        for code in blocks:
            norm = ChatSanitizer._normalize_code_text(code)
            ranked.append((ChatSanitizer._score_code_candidate(norm), norm))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    @staticmethod
    def _strip_code_blocks(text: str) -> str:
        return re.sub(r"```([a-zA-Z0-9_+\-]*)\s*\n[\s\S]*?```", "", text or "")

    @staticmethod
    def _is_plausible_python(code: str) -> bool:
        s = (code or "").strip()
        if not s:
            return False

        # Guard against trivial single-word text extracted from non-python fences.
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s):
            return False

        markers = [
            "def ", "class ", "import ", "from ", "if ", "elif ", "else:", "for ", "while ", "try:", "except",
            "return ", "print(", "=", ":", "(", ")", "[", "]", "{", "}",
        ]
        if any(m in s for m in markers):
            return True

        return "\n" in s

    @staticmethod
    def _first_sentence(text: str, max_chars: int = 180) -> str:
        if not text:
            return ""
        first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0].strip()
        if len(first) > max_chars:
            return first[:max_chars].rstrip() + "..."
        return first

    @staticmethod
    def normalize_coding_reply(text: str, require_code_block: bool = True) -> Dict[str, object]:
        """Return a stable coding payload with display text + validated injectable code."""
        cleaned = ChatSanitizer.sanitize_response(text or "", mode="coding")
        blocks = ChatSanitizer.extract_code_blocks(cleaned)
        had_block = bool(blocks)
        code = ChatSanitizer._choose_best_code_block(blocks) if blocks else ""

        if (not code) and (not require_code_block):
            loose = ChatSanitizer._normalize_code_text(cleaned)
            if ChatSanitizer._looks_like_python(loose) or ChatSanitizer._is_plausible_python(loose):
                code = loose

        if code and (not ChatSanitizer._is_plausible_python(code)):
            code = ""

        syntax_ok, syntax_error = ChatSanitizer.validate_python(code) if code else (False, "No Python code found.")
        issue = ""
        if require_code_block and (not had_block):
            issue = "No fenced Python code block found."
        elif code and (not syntax_ok):
            issue = syntax_error
        elif not code:
            issue = "No Python code found."

        response = cleaned.strip()
        if code:
            response = f"```python\n{code.rstrip()}\n```"
            comment = ChatSanitizer._first_sentence(ChatSanitizer._strip_code_blocks(cleaned))
            if comment:
                response = f"{response}\n\n{comment}"

        quality_score = ChatSanitizer._score_code_candidate(code) if code else 0
        return {
            "response_text": response,
            "code": code if (code and syntax_ok) else "",
            "syntax_ok": bool(code and syntax_ok),
            "had_code_block": had_block,
            "needs_retry": bool(issue),
            "issue": issue,
            "quality_score": quality_score,
        }

    @staticmethod
    def _looks_like_python(text: str) -> bool:
        if "\n" not in text:
            return False
        markers = ["def ", "import ", "print(", "if __name__", "class ", "return ", "for ", "while "]
        score = sum(1 for m in markers if m in text)
        return score >= 2
