"""Central code formatting helpers for editor, clipboard, and AI output.

The formatter is intentionally conservative: it normalizes text reliably,
uses Black when it is already installed, and otherwise avoids risky rewrites
that could change behavior or destroy partially typed code.
"""

import ast
import json
import os
import re
from typing import Optional, Tuple


class CodeFormatter:
    CODE_BLOCK_PATTERN = re.compile(r"```([a-zA-Z0-9_+\-]*)\s*\n([\s\S]*?)```")

    PYTHON_EXTENSIONS = {".py", ".pyw", ".pyi"}
    JSON_EXTENSIONS = {".json", ".jsonc"}
    JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    WEB_EXTENSIONS = {".html", ".htm", ".css", ".scss", ".sass"}
    TEXT_EXTENSIONS = {
        ".py",
        ".pyw",
        ".pyi",
        ".txt",
        ".md",
        ".json",
        ".jsonc",
        ".csv",
        ".tsv",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".xml",
        ".svg",
        ".sh",
        ".zsh",
        ".bash",
        ".sql",
    }

    @staticmethod
    def _extension(filename: Optional[str]) -> str:
        return os.path.splitext(filename or "")[1].lower()

    @staticmethod
    def normalize_line_endings(text: str) -> str:
        return (text or "").replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def strip_fence(text: str) -> Tuple[str, str]:
        """Return (language, code) for a fenced block, or ("", original text)."""
        val = (text or "").strip()
        match = CodeFormatter.CODE_BLOCK_PATTERN.fullmatch(val)
        if not match:
            return "", text or ""
        return (match.group(1) or "").strip().lower(), match.group(2) or ""

    @staticmethod
    def detect_language(text: str, filename: Optional[str] = None, language: Optional[str] = None) -> str:
        if language:
            lang = language.strip().lower()
            if lang in {"py", "python3"}:
                return "python"
            if lang in {"js", "javascript"}:
                return "javascript"
            if lang in {"ts", "typescript"}:
                return "typescript"
            return lang

        ext = CodeFormatter._extension(filename)
        if ext in CodeFormatter.PYTHON_EXTENSIONS:
            return "python"
        if ext in CodeFormatter.JSON_EXTENSIONS:
            return "json"
        if ext in CodeFormatter.JS_EXTENSIONS:
            return "javascript"
        if ext in CodeFormatter.WEB_EXTENSIONS:
            return ext.lstrip(".")

        stripped = (text or "").strip()
        if not stripped:
            return "text"
        if stripped.startswith(("{", "[")):
            return "json"

        python_markers = [
            "def ",
            "class ",
            "import ",
            "from ",
            "if __name__",
            "print(",
            "async def ",
        ]
        if "\n" in stripped and sum(1 for marker in python_markers if marker in stripped) >= 1:
            return "python"
        return "text"

    @staticmethod
    def looks_like_code(text: str, filename: Optional[str] = None) -> bool:
        lang = CodeFormatter.detect_language(text, filename=filename)
        if lang != "text":
            return True
        stripped = (text or "").strip()
        if "```" in stripped:
            return True
        codeish = [";", "{", "}", "=", "=>", "</", "#include", "SELECT ", "function "]
        return any(token in stripped for token in codeish)

    @staticmethod
    def is_text_file(path: str, sample_size: int = 4096) -> bool:
        ext = CodeFormatter._extension(path)
        if ext in CodeFormatter.TEXT_EXTENSIONS:
            return True
        try:
            with open(path, "rb") as f:
                sample = f.read(sample_size)
            if b"\x00" in sample:
                return False
            sample.decode("utf-8")
            return True
        except Exception:
            return False

    @staticmethod
    def _clean_basic(text: str, ensure_final_newline: bool = True) -> str:
        cleaned = CodeFormatter.normalize_line_endings(text).expandtabs(4)
        lines = [line.rstrip() for line in cleaned.split("\n")]
        cleaned = "\n".join(lines).strip("\n")
        if ensure_final_newline and cleaned:
            cleaned += "\n"
        return cleaned

    @staticmethod
    def _best_python_candidate(code: str) -> str:
        basic = CodeFormatter._clean_basic(code)
        candidates = [basic]

        lines = basic.splitlines()
        non_empty = [line for line in lines if line.strip()]
        if non_empty:
            min_indent = min(len(line) - len(line.lstrip(" ")) for line in non_empty)
            if min_indent >= 4:
                shifted = "\n".join((line[min_indent:] if len(line) >= min_indent else line) for line in lines)
                candidates.append(CodeFormatter._clean_basic(shifted))

        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                ast.parse(candidate)
                return candidate
            except SyntaxError:
                continue
            except Exception:
                continue
        return basic

    @staticmethod
    def _format_python(code: str, ensure_final_newline: bool = True) -> str:
        candidate = CodeFormatter._best_python_candidate(code)
        try:
            import black  # type: ignore

            candidate = black.format_str(candidate, mode=black.FileMode(line_length=100))
        except Exception:
            try:
                import autopep8  # type: ignore

                candidate = autopep8.fix_code(candidate, options={"max_line_length": 100})
            except Exception:
                pass

        candidate = CodeFormatter._clean_basic(candidate, ensure_final_newline=ensure_final_newline)
        return candidate

    @staticmethod
    def _format_json(code: str, ensure_final_newline: bool = True) -> str:
        cleaned = CodeFormatter._clean_basic(code, ensure_final_newline=False)
        try:
            parsed = json.loads(cleaned)
            cleaned = json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            pass
        if ensure_final_newline and cleaned:
            cleaned += "\n"
        return cleaned

    @staticmethod
    def format_code(
        text: str,
        filename: Optional[str] = None,
        language: Optional[str] = None,
        ensure_final_newline: bool = True,
    ) -> str:
        fence_lang, code = CodeFormatter.strip_fence(text or "")
        lang = CodeFormatter.detect_language(code, filename=filename, language=language or fence_lang)

        if lang in {"python", "py"}:
            return CodeFormatter._format_python(code, ensure_final_newline=ensure_final_newline)
        if lang == "json":
            return CodeFormatter._format_json(code, ensure_final_newline=ensure_final_newline)
        return CodeFormatter._clean_basic(code, ensure_final_newline=ensure_final_newline)

    @staticmethod
    def format_fenced_blocks(text: str) -> str:
        def repl(match):
            lang = (match.group(1) or "").strip()
            code = match.group(2) or ""
            formatted = CodeFormatter.format_code(code, language=lang, ensure_final_newline=True)
            return f"```{lang}\n{formatted}```" if lang else f"```\n{formatted}```"

        return CodeFormatter.CODE_BLOCK_PATTERN.sub(repl, text or "")
