"""Sanitization and code-extraction helpers for chat responses.

Focuses on reducing repetitive or nonsensical model output without damaging
code indentation/formatting.
"""

import ast
import re
import textwrap
from typing import Dict, List, Tuple

try:
    from code_formatter import CodeFormatter
except Exception:
    CodeFormatter = None


class AIResponseCleaner:
    """Remove chat-template residue and separate real answers from model noise."""

    SPECIAL_TOKEN_PATTERN = re.compile(
        r"<\|/?(?:im_start|im_end|assistant|user|system|endoftext|begin_of_text|eot_id|start_header_id|end_header_id)\|>|</?s>",
        flags=re.IGNORECASE,
    )
    ROLE_PREFIX_PATTERN = re.compile(
        r"^\s*(?:assistant|user|system|coding ai|general ai|shinzen)\s*:\s*",
        flags=re.IGNORECASE,
    )

    @staticmethod
    def strip_template_tokens(text: str) -> str:
        if not text:
            return ""
        cleaned = AIResponseCleaner.SPECIAL_TOKEN_PATTERN.sub("", text)
        cleaned = cleaned.replace("<|im_start|>", "").replace("<|im_end|>", "")
        lines = []
        for line in cleaned.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            stripped = line.strip()
            if stripped.lower() in {"assistant", "user", "system", "assistant:", "user:", "system:"}:
                continue
            lines.append(AIResponseCleaner.ROLE_PREFIX_PATTERN.sub("", line))
        return "\n".join(lines).strip()

    @staticmethod
    def clean(text: str, mode: str = None) -> str:
        cleaned = AIResponseCleaner.strip_template_tokens(text or "")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if mode == "coding":
            # Remove boilerplate before a first fenced code block unless it has actual explanatory value.
            first_block = ChatSanitizer.CODE_BLOCK_PATTERN.search(cleaned)
            if first_block:
                before = cleaned[: first_block.start()].strip()
                if before and len(before) < 80 and any(x in before.lower() for x in ("sure", "here", "below", "of course")):
                    cleaned = cleaned[first_block.start():].lstrip()
        return cleaned


class ChatSanitizer:
    ROLE_LABELS = {"User:", "Assistant:", "General AI:", "Coding AI:", "Shinzen:"}
    CODE_BLOCK_PATTERN = re.compile(r"```([a-zA-Z0-9_+\-]*)\s*\n([\s\S]*?)```")

    @staticmethod
    def sanitize_response(text: str, mode: str = None) -> str:
        if not text:
            return text
        text = AIResponseCleaner.clean(text, mode=mode)

        segments = ChatSanitizer._split_code_segments(text)
        cleaned_parts: List[str] = []

        for is_code, chunk in segments:
            if not chunk:
                continue
            if is_code:
                cleaned_parts.append(ChatSanitizer._normalize_fenced_block(chunk))
            else:
                prose = ChatSanitizer._sanitize_prose_segment(chunk)
                if prose:
                    cleaned_parts.append(prose)

        result = "\n\n".join(part for part in cleaned_parts if part.strip()).strip()

        if mode == "coding":
            result = ChatSanitizer._truncate_after_last_code_block(result)

        result = re.sub(r"\n{3,}", "\n\n", result)

        if len(result) > 12000:
            result = result[:12000].rstrip() + "\n\n...[truncated]"

        return result

    @staticmethod
    def _split_code_segments(text: str) -> List[Tuple[bool, str]]:
        out: List[Tuple[bool, str]] = []
        idx = 0
        for m in ChatSanitizer.CODE_BLOCK_PATTERN.finditer(text or ""):
            if m.start() > idx:
                out.append((False, text[idx:m.start()]))
            out.append((True, m.group(0)))
            idx = m.end()
        if idx < len(text or ""):
            out.append((False, text[idx:]))
        if not out:
            out.append((False, text or ""))
        return out

    @staticmethod
    def _normalize_fenced_block(block_text: str) -> str:
        m = ChatSanitizer.CODE_BLOCK_PATTERN.fullmatch(block_text.strip())
        if not m:
            return block_text.strip()
        lang = (m.group(1) or "").strip()
        code = (m.group(2) or "").replace("\r\n", "\n").replace("\r", "\n")
        if CodeFormatter is not None and lang.lower() in {"", "python", "py", "json"}:
            try:
                code = CodeFormatter.format_code(code, language=lang or "python")
            except Exception:
                pass
        if code and not code.endswith("\n"):
            code += "\n"
        return f"```{lang}\n{code}```" if lang else f"```\n{code}```"

    @staticmethod
    def _sanitize_prose_segment(text: str) -> str:
        lines = [ln for ln in (text or "").splitlines() if ln.strip() not in ChatSanitizer.ROLE_LABELS]

        collapsed: List[str] = []
        for ln in lines:
            if collapsed and ln.strip() == collapsed[-1].strip():
                continue
            collapsed.append(ln)

        compact = "\n".join(collapsed).strip()
        if not compact:
            return ""

        paras = [p.strip() for p in re.split(r"\n\s*\n", compact) if p.strip()]
        dedup_paras: List[str] = []
        for p in paras:
            p2 = ChatSanitizer._dedupe_repeated_sentences(p)
            if dedup_paras and p2 == dedup_paras[-1]:
                continue
            dedup_paras.append(p2)

        return "\n\n".join(dedup_paras).strip()

    @staticmethod
    def _truncate_after_last_code_block(text: str) -> str:
        try:
            matches = list(ChatSanitizer.CODE_BLOCK_PATTERN.finditer(text or ""))
            if not matches:
                return text

            last = matches[-1]
            end_idx = last.end()
            after = (text or "")[end_idx:]
            concl = ""
            if after.strip():
                paras = re.split(r"\n\s*\n", after.strip())
                if paras:
                    concl = paras[0].strip()[:350]

            truncated = (text or "")[:end_idx].rstrip()
            if concl:
                truncated = truncated + "\n\n" + concl
            return truncated
        except Exception:
            return text

    @staticmethod
    def _dedupe_repeated_sentences(text: str) -> str:
        s = (text or "").strip()
        if not s:
            return ""
        # Avoid flattening prose that appears to be plain code-like text.
        if ChatSanitizer._looks_like_python(s):
            return s

        chunks = re.split(r"(?<=[\.!\?])\s+", s)
        out: List[str] = []
        seen = set()
        for ch in chunks:
            norm = re.sub(r"\s+", " ", ch).strip().lower()
            if not norm:
                continue
            if len(norm) > 30 and norm in seen:
                continue
            out.append(ch.strip())
            seen.add(norm)
        return " ".join(out).strip()

    @staticmethod
    def is_nonsense(text: str, mode: str = "coding") -> bool:
        if not text:
            return True

        stripped = text.strip()
        if len(stripped) < 8:
            return True

        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        if len(lines) >= 6:
            uniq = len(set(lines))
            if uniq / max(1, len(lines)) < 0.45:
                return True

        words = re.findall(r"[A-Za-z_]{2,}", stripped.lower())
        if len(words) >= 80:
            uniq_words = len(set(words))
            if uniq_words / len(words) < 0.2:
                return True

        if mode == "coding" and len(stripped) > 180:
            has_block = "```" in stripped
            if not has_block and not ChatSanitizer._looks_like_python(stripped):
                return True

        return False

    @staticmethod
    def extract_code_blocks(text: str) -> List[str]:
        blocks: List[str] = []
        try:
            all_blocks: List[Tuple[str, str]] = []
            for match in ChatSanitizer.CODE_BLOCK_PATTERN.finditer(text or ""):
                lang = (match.group(1) or "").strip().lower()
                code = (match.group(2) or "").strip("\n")
                if code:
                    all_blocks.append((lang, code + "\n"))

            if all_blocks:
                py_blocks = [code for lang, code in all_blocks if lang in {"", "python", "py"}]
                return py_blocks if py_blocks else [code for _, code in all_blocks]

            if ChatSanitizer._looks_like_python(text or ""):
                blocks.append((text or "").strip() + "\n")
        except Exception:
            pass
        return blocks

    @staticmethod
    def classify_intent(text: str) -> str:
        """Classify Coding AI requests as code, question, or idea.

        The app uses this to avoid replacing Engine code when the user is only
        asking for an explanation or brainstorming.
        """
        raw = (text or "").strip()
        if not raw:
            return "question"

        low = raw.lower()
        if low.startswith(("/idea", "/ideas")):
            return "idea"
        if low.startswith(("/ask", "/chat", "/question", "/explain")):
            return "question"

        idea_words = {
            "idea",
            "ideas",
            "brainstorm",
            "suggestion",
            "suggestions",
            "roadmap",
            "feature ideas",
            "upgrade ideas",
            "improvements",
        }
        if any(word in low for word in idea_words):
            return "idea"

        if low.startswith(("i need ", "we need ", "please add ", "please make ", "make me ", "build me ")):
            if not any(word in low for word in ("explain", "understand", "why", "question", "advice")):
                return "code"

        code_words = {
            "write",
            "create",
            "build",
            "make",
            "implement",
            "code",
            "fix",
            "debug",
            "refactor",
            "rewrite",
            "add",
            "remove",
            "change",
            "update",
            "generate",
            "convert",
            "optimize",
            "format",
        }
        question_starters = (
            "what ",
            "why ",
            "how ",
            "when ",
            "where ",
            "which ",
            "who ",
            "can ",
            "could ",
            "should ",
            "would ",
            "do ",
            "does ",
            "did ",
            "is ",
            "are ",
            "am ",
            "explain ",
            "tell me ",
            "describe ",
        )

        if low.endswith("?") or low.startswith(question_starters):
            if any(phrase in low for phrase in ("what does", "how does", "why does", "what is", "can you explain", "explain why")):
                return "question"
            if not any(word in low for word in code_words):
                return "question"
            if any(phrase in low for phrase in ("how do i", "how can i", "what is", "why does")):
                return "question"

        if any(word in low for word in code_words):
            return "code"
        return "question"

    @staticmethod
    def _normalize_code_text(code: str) -> str:
        if not code:
            return ""
        cleaned = code.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"^\s*python\s*\n", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.expandtabs(4)
        lines = [ln.rstrip() for ln in cleaned.split("\n")]
        cleaned = "\n".join(lines).strip("\n")
        return cleaned + "\n"

    @staticmethod
    def _repair_indentation(code: str) -> str:
        norm = ChatSanitizer._normalize_code_text(code)
        if CodeFormatter is not None:
            try:
                formatted = CodeFormatter.format_code(norm, language="python")
                if formatted:
                    norm = formatted
            except Exception:
                pass
        candidates = [norm]

        dedented = textwrap.dedent(norm)
        if dedented != norm:
            candidates.append(dedented if dedented.endswith("\n") else dedented + "\n")

        lines = norm.splitlines()
        non_empty = [ln for ln in lines if ln.strip()]
        if non_empty and all(ln.startswith("    ") for ln in non_empty):
            shifted = "\n".join((ln[4:] if ln.startswith("    ") else ln) for ln in lines).strip("\n") + "\n"
            candidates.append(shifted)

        seen = set()
        for cand in candidates:
            if cand in seen:
                continue
            seen.add(cand)
            ok, _ = ChatSanitizer.validate_python(cand)
            if ok:
                return cand
        return norm

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
            norm = ChatSanitizer._repair_indentation(code)
            ranked.append((ChatSanitizer._score_code_candidate(norm), norm))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    @staticmethod
    def _strip_code_blocks(text: str) -> str:
        return ChatSanitizer.CODE_BLOCK_PATTERN.sub("", text or "")

    @staticmethod
    def _is_plausible_python(code: str) -> bool:
        s = (code or "").strip()
        if not s:
            return False

        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s):
            return False

        markers = [
            "def ",
            "class ",
            "import ",
            "from ",
            "if ",
            "elif ",
            "else:",
            "for ",
            "while ",
            "try:",
            "except",
            "return ",
            "print(",
            "=",
            ":",
            "(",
            ")",
            "[",
            "]",
            "{",
            "}",
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
            loose = ChatSanitizer._repair_indentation(cleaned)
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
            comment = ChatSanitizer._first_sentence(ChatSanitizer._sanitize_prose_segment(ChatSanitizer._strip_code_blocks(cleaned)))
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
        s = text or ""
        if "\n" not in s:
            return False
        markers = ["def ", "import ", "print(", "if __name__", "class ", "return ", "for ", "while "]
        score = sum(1 for m in markers if m in s)
        return score >= 2
