import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, simpledialog
import subprocess
import tempfile
import os
import threading
import sys
import traceback
import re
import time
import difflib
import json
import random
from Shinzen import Shinzen

# Optional MLX integration
try:
    from mlx_lm import load, generate
    MLX_AVAILABLE = True
except Exception:
    MLX_AVAILABLE = False

    def load(model_name, **kwargs):
        return None, None

    def generate(model, tokenizer, prompt, max_tokens=200):
        return ""


# Detect device for model loading (MPS if available)
def detect_device():
    try:
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


DEVICE = detect_device()

# Warm minimalist palette
BG = "#F7F0E8"
SURFACE = "#FFF8F1"
SURFACE_ALT = "#FFF2E6"
SOFT = "#EFCFB6"
ACCENT = "#D48657"
ACCENT_HOVER = "#BC7348"
TEXT = "#3A2C26"
MUTED = "#856B5E"
BORDER = "#EADACB"
OUTPUT_BG = "#FAF5EF"

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


def choose_font(fallback_size=13):
    candidates = ["Inter", "Avenir Next", "SF Pro Text", "Helvetica Neue", "Helvetica", "Arial"]
    for name in candidates:
        try:
            return (name, fallback_size)
        except Exception:
            pass
    return ("Helvetica", fallback_size)


BASE_FONT = choose_font(13)
MONO_FONT = (choose_font(13)[0], 13)


class RotatingLoader:
    def __init__(self, parent, size=18, color=SOFT):
        self.parent = parent
        self.size = size
        self.color = color
        self.canvas = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bg=parent["bg"])
        self.angle = 0
        self._job = None
        self.arc = self.canvas.create_arc(2, 2, size - 2, size - 2, start=0, extent=300, style="arc", width=3, outline=color)

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def start(self):
        self._animate()

    def _animate(self):
        self.angle = (self.angle + 8) % 360
        self.canvas.itemconfigure(self.arc, start=self.angle)
        self._job = self.canvas.after(30, self._animate)

    def stop(self):
        if self._job:
            self.canvas.after_cancel(self._job)
            self._job = None
        self.canvas.pack_forget()


class Code9Claude(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Code9 - Dual AI Studio")
        self.geometry("1360x860")
        self.minsize(1120, 740)
        self.configure(fg_color=BG)

        # Model/runtime state
        self.model = None
        self.tokenizer = None
        self.model_ready = False
        self.model_failed = False
        self.current_proc = None
        self.current_out_text = None
        self.current_file_path = None
        self.editor_dirty = False
        self._autosave_job = None
        self._settings_window = None

        # Persistent paths
        self.config_dir = os.path.join(os.path.expanduser("~"), ".code9")
        self.settings_path = os.path.join(self.config_dir, "settings.json")
        self.session_path = os.path.join(self.config_dir, "session_draft.py")
        os.makedirs(self.config_dir, exist_ok=True)

        # Defaults (overridden by settings)
        self.auto_run_coding = True
        self.insert_mode = "replace"          # replace | append
        self.run_mode = "temp"                # temp | active_file
        self.enable_typewriter = True
        self.general_max_tokens = 320
        self.coding_max_tokens = 900
        self.run_timeout_sec = 60
        self.persist_session = True
        self.restore_last_file = False
        self.last_opened_file = ""

        # Safety and verification controls
        self.enable_verifier = True
        self.safe_defaults = {"temperature": 0.0, "top_p": 0.8, "repetition_penalty": 1.4}

        self.project_ideas = [
            "Add a visual run history timeline with diff snapshots and re-run buttons.",
            "Support multi-file projects with a compact file tree and tabbed editors.",
            "Add an AI debugging mode that suggests fixes directly from traceback output.",
            "Create reusable prompt presets for tasks like refactor, explain, test, and document.",
            "Add a safe package installer panel for dependencies with one-click import checks.",
            "Build a test runner card (pytest/unittest) with pass/fail summaries and jump-to-line.",
            "Include code quality checks (format/lint) before run with a quick-fix pipeline.",
            "Add local project templates (CLI app, API app, data script, game prototype).",
            "Create a side-by-side compare mode for AI-generated code alternatives.",
            "Add versioned checkpoints so users can roll back to any previous engine state.",
        ]

        self._load_preferences()

        # Tokens used to cancel in-progress AI responses (increment to cancel)
        self.abort_tokens = {"general": 0, "coding": 0}
        # Active tasks counter used to determine Idle status
        self._active_tasks = 0
        # Attachments for coding prompts: key -> payload
        self.coding_attachments = {}

        # 2/3 left engine, 1/3 right dual chat
        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=1, minsize=360)
        self.grid_rowconfigure(1, weight=1)

        self._build_topbar()
        self._build_engine_panel()
        self._build_right_panel()
        self._bind_shortcuts()

        self._setup_editor_tags()
        self.editor.bind("<<Modified>>", self._on_editor_modified)

        self._load_initial_editor_content()
        self._highlight_syntax()
        self._update_run_mode_badge()
        self._refresh_coding_controls()

        if MLX_AVAILABLE:
            threading.Thread(target=self._load_model, daemon=True).start()
        else:
            self.status_label.configure(text="Model: not installed")

    # -------------------- UI BUILDERS --------------------
    def _build_topbar(self):
        self.topbar = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, height=74)
        self.topbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.topbar.grid_propagate(False)

        title_wrap = tk.Frame(self.topbar, bg=BG)
        title_wrap.pack(side="left", padx=24, pady=10)

        self.title_label = ctk.CTkLabel(
            title_wrap,
            text="Code9",
            font=(BASE_FONT[0], 21, "bold"),
            text_color=TEXT,
            fg_color=BG,
        )
        self.title_label.pack(anchor="w")

        self.file_label = ctk.CTkLabel(
            title_wrap,
            text="Engine file: session draft",
            font=(BASE_FONT[0], 12),
            text_color=MUTED,
            fg_color=BG,
        )
        self.file_label.pack(anchor="w", pady=(2, 0))

        status_wrap = tk.Frame(self.topbar, bg=BG)
        status_wrap.pack(side="right", padx=(8, 20), pady=10)

        self.status_label = ctk.CTkLabel(
            status_wrap,
            text="Model: loading..." if MLX_AVAILABLE else "Model: not installed",
            font=(BASE_FONT[0], 11),
            text_color=MUTED,
            fg_color=BG,
        )
        self.status_label.pack(side="right")

        self.loader_frame = tk.Frame(status_wrap, bg=BG)
        self.loader = Shinzen(
            self.loader_frame,
            sprite_paths=[
                os.path.join(os.path.dirname(__file__), "SnailSprite", "SnailLoading1.png"),
                os.path.join(os.path.dirname(__file__), "SnailSprite", "SnailLoading2.png"),
                os.path.join(os.path.dirname(__file__), "SnailSprite", "SnailLoading3.png"),
            ],
            frame_duration=160,
            size=(20, 20),
        )

        self.btn_bar = tk.Frame(self.topbar, bg=BG)
        self.btn_bar.pack(side="right", padx=10, pady=10)

        self.open_button = ctk.CTkButton(self.btn_bar, text="Open", width=70, fg_color=SURFACE_ALT, hover_color=SOFT, text_color=TEXT, command=self._on_open_clicked)
        self.open_button.pack(side="left", padx=4)

        self.save_button = ctk.CTkButton(self.btn_bar, text="Save", width=70, fg_color=SOFT, hover_color=SURFACE_ALT, text_color=TEXT, command=self._on_save_clicked)
        self.save_button.pack(side="left", padx=4)

        self.save_as_button = ctk.CTkButton(self.btn_bar, text="Save As", width=82, fg_color=SURFACE_ALT, hover_color=SOFT, text_color=TEXT, command=self._on_save_as_clicked)
        self.save_as_button.pack(side="left", padx=4)

        self.run_button = ctk.CTkButton(self.btn_bar, text="Run", width=72, fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white", command=self._on_run_clicked)
        self.run_button.pack(side="left", padx=4)

        self.stop_button = ctk.CTkButton(self.btn_bar, text="Stop", width=72, fg_color="#E8A395", hover_color="#DA8D7D", text_color=TEXT, command=self._on_stop_clicked)
        self.stop_button.pack(side="left", padx=4)

        self.ai_fill_btn = ctk.CTkButton(self.btn_bar, text="AI Fill", width=82, fg_color=SURFACE_ALT, hover_color=SOFT, text_color=TEXT, command=self._on_ai_fill_clicked)
        self.ai_fill_btn.pack(side="left", padx=4)

        self.shell_btn = ctk.CTkButton(self.btn_bar, text="Shell", width=72, fg_color=SURFACE_ALT, hover_color=SOFT, text_color=TEXT, command=self._on_create_shell_clicked)
        self.shell_btn.pack(side="left", padx=4)

        self.ideas_btn = ctk.CTkButton(self.btn_bar, text="Ideas", width=72, fg_color=SURFACE_ALT, hover_color=SOFT, text_color=TEXT, command=self._share_project_ideas)
        self.ideas_btn.pack(side="left", padx=4)

        self.settings_btn = ctk.CTkButton(self.btn_bar, text="Settings", width=84, fg_color=SURFACE_ALT, hover_color=SOFT, text_color=TEXT, command=self._open_settings)
        self.settings_btn.pack(side="left", padx=4)

        self.clear_chat_btn = ctk.CTkButton(self.btn_bar, text="Clear", width=68, fg_color=SURFACE_ALT, hover_color=SOFT, text_color=TEXT, command=self._on_clear_clicked)
        self.clear_chat_btn.pack(side="left", padx=4)

    def _build_engine_panel(self):
        self.left = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=18, border_width=1, border_color=BORDER)
        self.left.grid(row=1, column=0, padx=(20, 10), pady=18, sticky="nsew")
        self.left.grid_rowconfigure(1, weight=4)
        self.left.grid_rowconfigure(2, weight=2)
        self.left.grid_columnconfigure(0, weight=1)

        left_header = tk.Frame(self.left, bg=SURFACE)
        left_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        left_header.grid_columnconfigure(0, weight=1)

        engine_title = ctk.CTkLabel(
            left_header,
            text="Engine",
            font=(BASE_FONT[0], 16, "bold"),
            text_color=TEXT,
            fg_color=SURFACE,
        )
        engine_title.grid(row=0, column=0, sticky="w")

        self.run_mode_badge = ctk.CTkLabel(
            left_header,
            text="Run: Temp Sandbox",
            font=(BASE_FONT[0], 11),
            text_color=MUTED,
            fg_color=SURFACE,
        )
        self.run_mode_badge.grid(row=0, column=1, sticky="e")

        editor_holder = tk.Frame(self.left, bg=SURFACE)
        editor_holder.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        editor_holder.grid_rowconfigure(0, weight=1)
        editor_holder.grid_columnconfigure(0, weight=1)

        self.editor = tk.Text(
            editor_holder,
            font=(MONO_FONT[0], 13),
            bg="#FFF9F4",
            fg=TEXT,
            insertbackground=TEXT,
            bd=0,
            relief="flat",
            highlightthickness=0,
            wrap="none",
            padx=12,
            pady=12,
            undo=True,
            autoseparators=True,
            maxundo=-1,
        )
        self.editor.grid(row=0, column=0, sticky="nsew")

        self.editor_vsb = tk.Scrollbar(editor_holder, orient="vertical", command=self.editor.yview)
        self.editor_vsb.grid(row=0, column=1, sticky="ns")

        self.editor_hsb = tk.Scrollbar(editor_holder, orient="horizontal", command=self.editor.xview)
        self.editor_hsb.grid(row=1, column=0, sticky="ew")

        self.editor.config(yscrollcommand=self.editor_vsb.set, xscrollcommand=self.editor_hsb.set)

        output_holder = tk.Frame(self.left, bg=SURFACE)
        output_holder.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        output_holder.grid_rowconfigure(1, weight=1)
        output_holder.grid_columnconfigure(0, weight=1)

        out_header = tk.Frame(output_holder, bg=SURFACE)
        out_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        out_header.grid_columnconfigure(0, weight=1)

        out_title = ctk.CTkLabel(
            out_header,
            text="Runtime Output",
            font=(BASE_FONT[0], 13, "bold"),
            text_color=TEXT,
            fg_color=SURFACE,
        )
        out_title.grid(row=0, column=0, sticky="w")

        self.clear_output_btn = ctk.CTkButton(
            out_header,
            text="Clear Output",
            width=100,
            fg_color=SURFACE_ALT,
            hover_color=SOFT,
            text_color=TEXT,
            command=self._clear_output_panel,
        )
        self.clear_output_btn.grid(row=0, column=1, sticky="e")

        self.output_text = tk.Text(
            output_holder,
            font=(MONO_FONT[0], 12),
            bg=OUTPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            bd=0,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            padx=12,
            pady=10,
            state="disabled",
        )
        self.output_text.grid(row=1, column=0, sticky="nsew")

    def _build_right_panel(self):
        self.right = ctk.CTkFrame(self, fg_color=BG, corner_radius=18)
        self.right.grid(row=1, column=1, padx=(8, 18), pady=18, sticky="nsew")
        self.right.grid_rowconfigure(0, weight=1)
        self.right.grid_rowconfigure(1, weight=1)
        self.right.grid_columnconfigure(0, weight=1)

        self.general_card = self._build_chat_card(
            parent=self.right,
            row=0,
            title="General AI",
            placeholder="Ask anything...",
            ask_cmd=self._on_general_ask_clicked,
            kind="general",
        )

        self.coding_card = self._build_chat_card(
            parent=self.right,
            row=1,
            title="Coding AI",
            placeholder="Ask for code, fixes, or refactors...",
            ask_cmd=self._on_coding_ask_clicked,
            kind="coding",
        )

    def _build_chat_card(self, parent, row, title, placeholder, ask_cmd, kind="general"):
        card = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=18, border_width=1, border_color=BORDER)
        card.grid(row=row, column=0, sticky="nsew", pady=(0, 10) if row == 0 else (8, 0))
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        header = tk.Frame(card, bg=SURFACE)
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 8))
        header.grid_columnconfigure(0, weight=1)

        lbl = ctk.CTkLabel(header, text=title, font=(BASE_FONT[0], 15, "bold"), text_color=TEXT, fg_color=SURFACE)
        lbl.grid(row=0, column=0, sticky="w")

        if kind == "coding":
            self.auto_run_btn = ctk.CTkButton(
                header,
                text="Auto Run: On" if self.auto_run_coding else "Auto Run: Off",
                width=104,
                fg_color=SURFACE_ALT,
                hover_color=SOFT,
                text_color=TEXT,
                command=self._toggle_auto_run,
            )
            self.auto_run_btn.grid(row=0, column=1, padx=(6, 4), sticky="e")

            self.insert_mode_btn = ctk.CTkButton(
                header,
                text="Insert: Replace" if self.insert_mode == "replace" else "Insert: Append",
                width=112,
                fg_color=SURFACE_ALT,
                hover_color=SOFT,
                text_color=TEXT,
                command=self._toggle_insert_mode,
            )
            self.insert_mode_btn.grid(row=0, column=2, padx=(4, 0), sticky="e")

        # Stop button available on both chat cards to cancel ongoing replies
        stop_btn = ctk.CTkButton(
            header,
            text="Stop",
            width=80,
            fg_color=SURFACE_ALT,
            hover_color=SOFT,
            text_color=TEXT,
            command=lambda k=kind: self._stop_response(k),
        )
        stop_btn.grid(row=0, column=3, padx=(6, 0), sticky="e")
        # keep a reference so tests or other code can access it
        if kind == "general":
            self.general_stop_btn = stop_btn
        else:
            self.coding_stop_btn = stop_btn

        text_wrap = tk.Frame(card, bg=SURFACE)
        text_wrap.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        text_wrap.grid_rowconfigure(0, weight=1)
        text_wrap.grid_columnconfigure(0, weight=1)

        chat_text = tk.Text(
            text_wrap,
            bg="#FFF9F4",
            fg=TEXT,
            bd=0,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            padx=12,
            pady=12,
            state="disabled",
            font=(BASE_FONT[0], 12),
        )
        chat_text.grid(row=0, column=0, sticky="nsew")

        chat_vsb = tk.Scrollbar(text_wrap, orient="vertical", command=chat_text.yview)
        chat_vsb.grid(row=0, column=1, sticky="ns")
        chat_text.config(yscrollcommand=chat_vsb.set)
        self._setup_chat_tags(chat_text)

        # Attachments row (visible only for coding card)
        attachments_frame = tk.Frame(card, bg=SURFACE)
        attachments_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        attachments_frame.grid_columnconfigure(0, weight=1)

        input_row = tk.Frame(card, bg=SURFACE)
        input_row.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        input_row.grid_columnconfigure(0, weight=1)

        input_var = tk.StringVar()
        input_entry = ctk.CTkEntry(
            input_row,
            placeholder_text=placeholder,
            textvariable=input_var,
            fg_color=SURFACE_ALT,
            border_width=0,
            text_color=TEXT,
        )
        input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ask_btn = ctk.CTkButton(
            input_row,
            text="Ask",
            width=70,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="white",
            command=ask_cmd,
        )
        ask_btn.grid(row=0, column=2, sticky="e")

        copy_btn = ctk.CTkButton(
            input_row,
            text="Copy",
            width=70,
            fg_color=SURFACE_ALT,
            hover_color=SOFT,
            text_color=TEXT,
            command=lambda: self._copy_from_widget(chat_text),
        )
        copy_btn.grid(row=0, column=1, sticky="e", padx=(0, 8))

        return {
            "frame": card,
            "text": chat_text,
            "var": input_var,
            "entry": input_entry,
            "ask": ask_btn,
            "copy": copy_btn,
            "attachments_frame": attachments_frame,
        }

    # -------------------- SETTINGS & PERSISTENCE --------------------
    def _load_preferences(self):
        try:
            if not os.path.exists(self.settings_path):
                return
            with open(self.settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.auto_run_coding = bool(data.get("auto_run_coding", self.auto_run_coding))
            self.insert_mode = data.get("insert_mode", self.insert_mode) if data.get("insert_mode") in {"replace", "append"} else self.insert_mode
            self.run_mode = data.get("run_mode", self.run_mode) if data.get("run_mode") in {"temp", "active_file"} else self.run_mode
            self.enable_typewriter = bool(data.get("enable_typewriter", self.enable_typewriter))
            self.general_max_tokens = self._coerce_int(data.get("general_max_tokens", self.general_max_tokens), 80, 2400, self.general_max_tokens)
            self.coding_max_tokens = self._coerce_int(data.get("coding_max_tokens", self.coding_max_tokens), 120, 4000, self.coding_max_tokens)
            self.run_timeout_sec = self._coerce_int(data.get("run_timeout_sec", self.run_timeout_sec), 5, 600, self.run_timeout_sec)
            self.persist_session = bool(data.get("persist_session", self.persist_session))
            self.restore_last_file = bool(data.get("restore_last_file", self.restore_last_file))
            self.last_opened_file = data.get("last_opened_file", "")
        except Exception:
            pass

    def _save_preferences(self):
        data = {
            "auto_run_coding": self.auto_run_coding,
            "insert_mode": self.insert_mode,
            "run_mode": self.run_mode,
            "enable_typewriter": self.enable_typewriter,
            "general_max_tokens": self.general_max_tokens,
            "coding_max_tokens": self.coding_max_tokens,
            "run_timeout_sec": self.run_timeout_sec,
            "persist_session": self.persist_session,
            "restore_last_file": self.restore_last_file,
            "last_opened_file": self.current_file_path or self.last_opened_file,
        }
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load_initial_editor_content(self):
        sample = (
            'def hello():\n'
            '    print("Hello from Code9 engine")\n\n'
            'if __name__ == "__main__":\n'
            '    hello()\n'
        )

        loaded = False

        if self.restore_last_file and self.last_opened_file and os.path.exists(self.last_opened_file):
            loaded = self._open_snippet(path=self.last_opened_file, from_restore=True)

        if not loaded and self.persist_session and os.path.exists(self.session_path):
            try:
                with open(self.session_path, "r", encoding="utf-8") as f:
                    data = f.read()
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", data if data.strip() else sample)
                self.current_file_path = None
                loaded = True
            except Exception:
                loaded = False

        if not loaded:
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", sample)

        self.editor.edit_modified(False)
        self.editor_dirty = False
        self._update_file_label()

    def _schedule_session_autosave(self):
        if not self.persist_session:
            return
        try:
            if self._autosave_job is not None:
                self.after_cancel(self._autosave_job)
            self._autosave_job = self.after(800, self._save_session_draft)
        except Exception:
            pass

    def _save_session_draft(self):
        self._autosave_job = None
        if not self.persist_session:
            return
        try:
            content = self.editor.get("1.0", "end-1c")
            with open(self.session_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

    def _open_settings(self):
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return

        win = ctk.CTkToplevel(self)
        win.title("Code9 Settings")
        win.geometry("520x520")
        win.configure(fg_color=SURFACE)
        win.resizable(False, False)
        self._settings_window = win

        wrap = ctk.CTkFrame(win, fg_color=SURFACE, corner_radius=0)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(wrap, text="Behavior", text_color=TEXT, font=(BASE_FONT[0], 16, "bold")).pack(anchor="w", pady=(0, 8))

        auto_run_var = tk.BooleanVar(value=self.auto_run_coding)
        type_var = tk.BooleanVar(value=self.enable_typewriter)
        persist_var = tk.BooleanVar(value=self.persist_session)
        restore_var = tk.BooleanVar(value=self.restore_last_file)

        ctk.CTkCheckBox(wrap, text="Auto-run code from Coding AI", variable=auto_run_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Typewriter animation in chat", variable=type_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Persist session draft", variable=persist_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Restore last opened file on launch", variable=restore_var, text_color=TEXT).pack(anchor="w", pady=4)

        ctk.CTkLabel(wrap, text="Run Mode", text_color=TEXT, font=(BASE_FONT[0], 13, "bold")).pack(anchor="w", pady=(14, 4))
        run_mode_map = {
            "Temp Sandbox (isolated)": "temp",
            "Active File (save + run)": "active_file",
        }
        run_mode_var = tk.StringVar(value="Temp Sandbox (isolated)" if self.run_mode == "temp" else "Active File (save + run)")
        ctk.CTkOptionMenu(wrap, values=list(run_mode_map.keys()), variable=run_mode_var, fg_color=SURFACE_ALT, button_color=SOFT, button_hover_color=ACCENT_HOVER, text_color=TEXT).pack(anchor="w", pady=2)

        ctk.CTkLabel(wrap, text="Code Insert Mode", text_color=TEXT, font=(BASE_FONT[0], 13, "bold")).pack(anchor="w", pady=(12, 4))
        insert_map = {
            "Replace Engine Content": "replace",
            "Append to Engine Content": "append",
        }
        insert_var = tk.StringVar(value="Replace Engine Content" if self.insert_mode == "replace" else "Append to Engine Content")
        ctk.CTkOptionMenu(wrap, values=list(insert_map.keys()), variable=insert_var, fg_color=SURFACE_ALT, button_color=SOFT, button_hover_color=ACCENT_HOVER, text_color=TEXT).pack(anchor="w", pady=2)

        grid = ctk.CTkFrame(wrap, fg_color=SURFACE)
        grid.pack(fill="x", pady=(14, 2))
        grid.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(grid, text="General max tokens", text_color=MUTED).grid(row=0, column=0, sticky="w", pady=6)
        general_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT, border_width=0)
        general_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=6)
        general_entry.insert(0, str(self.general_max_tokens))

        ctk.CTkLabel(grid, text="Coding max tokens", text_color=MUTED).grid(row=1, column=0, sticky="w", pady=6)
        coding_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT, border_width=0)
        coding_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=6)
        coding_entry.insert(0, str(self.coding_max_tokens))

        ctk.CTkLabel(grid, text="Run timeout (sec)", text_color=MUTED).grid(row=2, column=0, sticky="w", pady=6)
        timeout_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT, border_width=0)
        timeout_entry.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=6)
        timeout_entry.insert(0, str(self.run_timeout_sec))

        btns = ctk.CTkFrame(wrap, fg_color=SURFACE)
        btns.pack(fill="x", pady=(16, 2))

        def apply_and_close():
            self.auto_run_coding = bool(auto_run_var.get())
            self.enable_typewriter = bool(type_var.get())
            self.persist_session = bool(persist_var.get())
            self.restore_last_file = bool(restore_var.get())

            self.run_mode = run_mode_map.get(run_mode_var.get(), self.run_mode)
            self.insert_mode = insert_map.get(insert_var.get(), self.insert_mode)

            self.general_max_tokens = self._coerce_int(general_entry.get(), 80, 2400, self.general_max_tokens)
            self.coding_max_tokens = self._coerce_int(coding_entry.get(), 120, 4000, self.coding_max_tokens)
            self.run_timeout_sec = self._coerce_int(timeout_entry.get(), 5, 600, self.run_timeout_sec)

            self._refresh_coding_controls()
            self._update_run_mode_badge()
            self._save_preferences()
            self._set_status_temporary("Settings saved", duration=1800)
            try:
                win.destroy()
            except Exception:
                pass

        ctk.CTkButton(btns, text="Cancel", width=90, height=40, fg_color=SURFACE_ALT, hover_color=SOFT, text_color=TEXT, command=win.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text="Save", width=90, height=40, fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white", command=apply_and_close).pack(side="right")

    # -------------------- CHAT HELPERS --------------------
    def _setup_chat_tags(self, widget):
        try:
            widget.tag_config("role", foreground=MUTED, font=(BASE_FONT[0], 10, "bold"), spacing1=6)
            widget.tag_config("user", foreground=TEXT, background="#FCEEE1", lmargin1=8, lmargin2=8, spacing1=2, spacing3=6)
            widget.tag_config("assistant", foreground=TEXT, background="#FFF9F3", lmargin1=8, lmargin2=8, spacing1=2, spacing3=8)
        except Exception:
            pass

    def _append_user(self, widget, text):
        try:
            widget.config(state="normal")
            widget.insert("end", "You:\n", ("role",))
            start = widget.index("end-1c")
            widget.insert("end", text + "\n")
            end = widget.index("end-1c")
            widget.tag_add("user", start, end)
            widget.see("end")
            widget.config(state="disabled")
        except Exception:
            pass

    def _append_assistant(self, widget, text, label="Assistant", kind=None, request_id=None):
        """Append assistant text to a chat widget. If request_id is provided, this append is cancelled
        when self.abort_tokens[kind] changes.
        """
        safe_text = self._sanitize_text(text)

        # If a request id is provided and doesn't match current, skip appending
        try:
            if kind and request_id is not None:
                if request_id != self.abort_tokens.get(kind):
                    # cancelled before append started
                    return
        except Exception:
            pass

        if not self.enable_typewriter:
            try:
                widget.config(state="normal")
                widget.insert("end", f"\n{label}:\n", ("role",))
                start = widget.index("end-1c")
                widget.insert("end", safe_text + "\n")
                end = widget.index("end-1c")
                widget.tag_add("assistant", start, end)
                widget.see("end")
                widget.config(state="disabled")
            except Exception:
                pass
            return

        try:
            widget.config(state="normal")
            widget.insert("end", f"\n{label}:\n", ("role",))
            start = widget.index("end-1c")
            widget.see("end")
            i = 0

            def step():
                nonlocal i, start
                try:
                    # If cancellation occurred during typing, abort
                    if kind and request_id is not None and request_id != self.abort_tokens.get(kind):
                        widget.config(state="disabled")
                        return

                    if i < len(safe_text):
                        widget.insert("end", safe_text[i])
                        widget.see("end")
                        i += 1
                        self.after(7, step)
                    else:
                        widget.insert("end", "\n")
                        end = widget.index("end-1c")
                        try:
                            widget.tag_add("assistant", start, end)
                        except Exception:
                            pass
                        widget.config(state="disabled")
                except Exception:
                    try:
                        widget.config(state="disabled")
                    except Exception:
                        pass

            step()
        except Exception:
            try:
                widget.config(state="normal")
                widget.insert("end", f"\n{label}:\n{safe_text}\n")
                widget.config(state="disabled")
            except Exception:
                pass

    def _clear_chat_widget(self, widget):
        try:
            widget.config(state="normal")
            widget.delete("1.0", "end")
            widget.config(state="disabled")
        except Exception:
            pass

    def _copy_from_widget(self, widget):
        """Copy selection if present, else copy the entire widget content to clipboard."""
        try:
            try:
                sel = widget.get("sel.first", "sel.last")
                text = sel.strip()
            except Exception:
                text = widget.get("1.0", "end-1c").strip()

            if not text:
                self._set_status_temporary("Nothing to copy", duration=1400)
                return

            # Ensure clean text (no role markers)
            cleaned = re.sub(r"^\s*(You:|Assistant:|General AI:|Coding AI:)[\r\n]+", "", text, flags=re.I | re.M)
            self.clipboard_clear()
            self.clipboard_append(cleaned)
            self._set_status_temporary("Copied to clipboard", duration=1400)
        except Exception:
            pass

    # -------------------- MODEL --------------------
    def _model_status_text(self):
        if not MLX_AVAILABLE:
            return "Model: not installed"
        if self.model_ready:
            return f"Model: ready ({DEVICE})"
        if self.model_failed:
            return "Model: failed"
        return f"Model: loading ({DEVICE})"

    def _load_model(self):
        try:
            self.status_label.configure(text=f"Loading model on {DEVICE}...")
            import inspect
            sig = inspect.signature(load)
            kwargs = {}
            if "device" in sig.parameters:
                kwargs["device"] = DEVICE
            model, tokenizer = load("mlx-community/Meta-Llama-3-8B-Instruct-4bit", **kwargs)
            self.model = model
            self.tokenizer = tokenizer
            self.model_ready = True
            self.model_failed = False
            # Refresh status (Idle if no active work)
            self._refresh_status()
        except Exception as e:
            self.model_ready = False
            self.model_failed = True
            # Show failure message
            self._refresh_status()
            print("Model load error:", e)

    def _sanitize_response(self, text, mode=None):
        """
        Basic post-processing to reduce self-talk, role markers, and exact repeated lines.
        For coding mode, also truncate the response after the final code block plus a short concluding paragraph
        to avoid repeated code dumps or trailing duplicates.
        """
        try:
            if not text:
                return text

            # Remove obvious role markers
            lines = [ln for ln in text.splitlines() if ln.strip() not in ("User:", "Assistant:", "General AI:", "Coding AI:")]
            # Collapse consecutive identical lines
            collapsed = []
            for ln in lines:
                if collapsed and ln.strip() == collapsed[-1].strip():
                    continue
                collapsed.append(ln)
            result = "\n".join(collapsed).strip()

            # For coding responses: truncate after last fenced code block and at most one short concluding paragraph
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
                            m = re.search(r"\n\s*\n", after)
                            if m:
                                concl = after[: m.start()].strip()
                            else:
                                # take first paragraph or up to 600 chars
                                para = after.strip().splitlines()
                                if para:
                                    joined = "\n".join(para[:5])
                                    concl = joined[:600].strip()
                        truncated = result[:end_idx]
                        if concl:
                            truncated = truncated + "\n\n" + concl
                        result = truncated
                except Exception:
                    pass

            # If the model repeats an entire paragraph multiple times, keep only first occurrence
            paras = [p.strip() for p in re.split(r"\n\s*\n", result) if p.strip()]
            dedup_paras = []
            for p in paras:
                if dedup_paras and p == dedup_paras[-1]:
                    continue
                dedup_paras.append(p)
            final = "\n\n".join(dedup_paras)

            # As a final safeguard, if the entire text is repeated multiple times, keep only one occurrence
            # e.g., 'A A A' long repeats
            if len(final) > 200:
                half = final[: len(final) // 2]
                if half in final[len(half) :]:
                    # keep only first occurrence
                    final = final[: len(final) // 2]

            return final
        except Exception:
            return text

    def _safe_generate(self, prompt, max_tokens, temperature=None):
        """Call the underlying generate function with conservative decoding params when supported.
        The function detects common parameter names and falls back gracefully.
        """
        try:
            import inspect
            sig = inspect.signature(generate)
            params = sig.parameters
            call_kwargs = {}

            # Prompt/input naming
            if "prompt" in params:
                call_kwargs["prompt"] = prompt
            elif "inputs" in params:
                call_kwargs["inputs"] = prompt
            else:
                call_kwargs["prompt"] = prompt

            # Max tokens naming
            if "max_tokens" in params:
                call_kwargs["max_tokens"] = max_tokens
            elif "max_new_tokens" in params:
                call_kwargs["max_new_tokens"] = max_tokens
            elif "max_output_tokens" in params:
                call_kwargs["max_output_tokens"] = max_tokens

            # Decoding defaults (favor deterministic/stable outputs)
            # Allow an override temperature to be passed explicitly
            if temperature is None:
                if "temperature" in params:
                    call_kwargs["temperature"] = 0.0
            else:
                if "temperature" in params:
                    call_kwargs["temperature"] = temperature

            if "top_p" in params:
                call_kwargs["top_p"] = 0.8
            if "repetition_penalty" in params:
                call_kwargs["repetition_penalty"] = 1.4

            # Add stop sequences if supported to reduce run-on replies
            if "stop" in params:
                call_kwargs["stop"] = ["\n\nAssistant:", "\n\nYou:", "\n\nUser:"]

            # Some generate signatures expect (model, tokenizer, **kwargs)
            try:
                return generate(self.model, self.tokenizer, **call_kwargs)
            except TypeError:
                # Best-effort fallback
                return generate(self.model, self.tokenizer, prompt=prompt, max_tokens=max_tokens)
        except Exception:
            try:
                return generate(self.model, self.tokenizer, prompt=prompt, max_tokens=max_tokens)
            except Exception:
                return ""

    def _run_verifier(self, assistant_text, mode):
        """Run a short verifier pass that highlights potentially hallucinated claims.
        If verifier is not enabled or model unavailable, returns empty string.
        """
        try:
            if (not MLX_AVAILABLE) or (not self.model_ready) or (not getattr(self, "enable_verifier", True)):
                return ""

            verify_prompt = (
                "You are a factual verifier. Review the assistant response delimited by <<<RESPONSE>>>.\n"
                "List at most five statements that might be hallucinations or require citations, each as a short bullet with a one-line reason.\n"
                "If none, reply with OK.\n\n"
                "<<<RESPONSE>>>\n"
                f"{assistant_text}\n"
                "<<<END>>>\n"
            )

            raw = self._safe_generate(verify_prompt, max_tokens=180)
            cleaned = self._sanitize_response(raw, mode="general")
            if cleaned.strip().lower().startswith("ok"):
                return ""
            return "\n\n[Verifier notes]:\n" + cleaned
        except Exception:
            return ""

    def _generate_text(self, prompt, max_tokens, mode="general"):
        # Local fallback when model is unavailable
        if not MLX_AVAILABLE or not self.model_ready:
            if mode == "coding":
                return (
                    "```python\n"
                    "# Model is not ready yet.\n"
                    "# You can still write and run code in the engine.\n"
                    "print('Model not ready. Try again in a moment.')\n"
                    "```"
                )
            return "The model is still loading. You can continue editing and running code while it initializes."

        try:
            raw = self._safe_generate(prompt, max_tokens)

            # Optional lightweight verifier pass to flag risky/hallucinated claims.
            # This runs with conservative limits and appends a short note if anything questionable is found.
            note = ""
            try:
                if getattr(self, "enable_verifier", True):
                    note = self._run_verifier(raw, mode)
            except Exception:
                note = ""

            return self._sanitize_response((raw or "") + (note or ""), mode=mode)
        except Exception as e:
            if mode == "coding":
                return f"```python\n# Generation error\nprint({repr(str(e))})\n```"
            return f"Generation error: {e}"

    # -------------------- ASK HANDLERS --------------------
    def _on_general_ask_clicked(self):
        self.ask_general_ai()

    def _on_coding_ask_clicked(self):
        self.ask_coding_ai()

    def ask_general_ai(self, event=None):
        query = self.general_card["var"].get().strip()
        if not query:
            return

        # increment request token and capture it for cancellation checks
        try:
            self.abort_tokens['general'] = self.abort_tokens.get('general', 0) + 1
            req_id = self.abort_tokens['general']
        except Exception:
            req_id = None

        self._append_user(self.general_card["text"], query)
        self.general_card["var"].set("")
        self.start_loader()
        self.status_label.configure(text="General AI thinking...")

        threading.Thread(target=self._general_worker, args=(query, req_id), daemon=True).start()

    def ask_coding_ai(self, event=None):
        # Read the entry but strip the visual prefix (if present) so attachments remain visible in the entry
        var = self.coding_card["var"]
        val = var.get()
        prefix = getattr(self, "_coding_attach_prefix", "")

        # If user typed attachment tags like /Errors or /Engine at start, process them into attachments
        try:
            leading = val
            if prefix and val.startswith(prefix):
                leading = val[len(prefix):].lstrip()
            # find tags like /Errors, /Runtime, /Engine, /General (case-insensitive) anywhere in leading text
            tags = [t.strip('/') for t in re.findall(r"/(\w+)", leading)]
            if tags:
                # map tag to attach call
                for t in tags:
                    tl = t.lower()
                    if tl.startswith("err"):
                        self._attach_errors_to_coding()
                    elif tl.startswith("run") or tl == "runtime":
                        self._attach_runtime_output_to_coding()
                    elif tl.startswith("eng"):
                        self._attach_editor_to_coding()
                    elif tl.startswith("gen"):
                        self._attach_general_chat_to_coding()
                # remove tags from value
                # strip all /word tokens
                leading = re.sub(r"/\w+", "", leading).strip()
            # final query text is remaining leading + rest after prefix removed
            if prefix and val.startswith(prefix):
                remaining = leading
            else:
                remaining = leading
            query = remaining.strip()
        except Exception:
            # fallback parsing
            if prefix and val.startswith(prefix):
                query = val[len(prefix):].strip()
            else:
                query = val.strip()

        if not query:
            return

        try:
            self.abort_tokens['coding'] = self.abort_tokens.get('coding', 0) + 1
            req_id = self.abort_tokens['coding']
        except Exception:
            req_id = None

        self._append_user(self.coding_card["text"], query)
        # keep the prefix in the entry after sending
        if prefix:
            var.set(prefix)
        else:
            var.set("")
        self.start_loader()
        self.status_label.configure(text="Coding AI generating...")

        threading.Thread(target=self._coding_worker, args=(query, req_id), daemon=True).start()

    def _general_worker(self, query, req_id=None):
        prompt = (
            "You are Code9's all-purpose assistant. "
            "Be warm, clear, practical, and concise. "
            "Do not invent facts — if you do not know, say 'I don't know' and suggest how to verify. "
            "If the user asks technical questions, answer directly and offer actionable next steps.\n\n"
            f"User:\n{query}\n\nAssistant:"
        )

        try:
            resp = self._generate_text(prompt=prompt, max_tokens=self.general_max_tokens, mode="general")
            # If request was cancelled while generating, don't display
            if req_id is not None and req_id != self.abort_tokens.get('general'):
                self.after(0, lambda: self._set_status_temporary("General AI response cancelled", duration=1200))
            else:
                self.after(0, lambda r=resp, rid=req_id: self._append_assistant(self.general_card["text"], r, label="General AI", kind="general", request_id=rid))
        finally:
            self.after(0, self.stop_loader)
            self.after(0, self._refresh_status)

    def _coding_worker(self, query, req_id=None):
        editor_snapshot = self.editor.get("1.0", "end-1c")
        # Include any attached resources into the prompt so the model can use them.
        attachments_text = ""
        try:
            if self.coding_attachments:
                attachments_text = "Attached resources:\n\n" + "\n\n".join(self.coding_attachments.values()) + "\n\n"
        except Exception:
            attachments_text = ""

        prompt = (
            "You are Code9's coding assistant. "
            "Provide a brief explanation and include runnable Python in fenced code blocks when code is needed. "
            "If multiple files are needed, clearly label each block. "
            "Do not invent file contents or external facts — if unsure, say you don't know. "
            "Do not give extranious unused code. "
            "Do not role-play another assistant or talk to yourself.\n\n"
            f"{attachments_text}"
            "Current engine code:\n"
            f"```python\n{editor_snapshot[:6000]}\n```\n\n"
            f"User request:\n{query}\n\n"
            "Assistant:"
        )

        try:
            resp = self._generate_text(prompt=prompt, max_tokens=self.coding_max_tokens, mode="coding")
            # If request cancelled while generating, do not append or inject
            if req_id is not None and req_id != self.abort_tokens.get('coding'):
                self.after(0, lambda: self._set_status_temporary("Coding AI response cancelled", duration=1200))
                return

            code_candidates = self._extract_code_blocks(resp)

            self.after(0, lambda r=resp, rid=req_id: self._append_assistant(self.coding_card["text"], r, label="Coding AI", kind="coding", request_id=rid))

            if code_candidates:
                selected = code_candidates[-1]
                self.after(0, lambda c=selected: self._inject_code_into_engine(c))
            else:
                self.after(0, lambda: self._set_status_temporary("No code block found in coding reply", duration=2200))
        finally:
            self.after(0, self.stop_loader)
            self.after(0, self._refresh_status)

    def _extract_code_blocks(self, text):
        blocks = []
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

            if self._looks_like_python(text):
                blocks.append(text.strip() + "\n")
        except Exception:
            pass
        return blocks

    def _looks_like_python(self, text):
        if "\n" not in text:
            return False
        markers = ["def ", "import ", "print(", "if __name__", "class ", "return ", "for ", "while "]
        score = sum(1 for m in markers if m in text)
        return score >= 2

    def _inject_code_into_engine(self, code):
        normalized = code if code.endswith("\n") else (code + "\n")

        if self.insert_mode == "append":
            current = self.editor.get("1.0", "end-1c")
            if current.strip():
                self.editor.insert("end", "\n\n")
            self.editor.insert("end", normalized)
        else:
            self._apply_minimal_edits_to_editor(normalized)

        self._highlight_syntax()
        self._mark_editor_dirty()
        self._schedule_session_autosave()

        if self.auto_run_coding:
            code_to_run = self.editor.get("1.0", "end-1c")
            threading.Thread(target=self._run_code, args=(code_to_run, False), daemon=True).start()
            self._set_status_temporary("Injected code into engine and started run", duration=2200)
        else:
            self._set_status_temporary("Injected code into engine", duration=1800)

    # -------------------- RUN / ENGINE --------------------
    def _run_code(self, code, manage_loader=False):
        code_to_write = code if code.endswith("\n") else code + "\n"

        try:
            compile(code_to_write, "<engine>", "exec")
        except Exception as e:
            self.after(0, self._clear_output_panel)
            self.after(0, lambda: self._append_output(f"Syntax error:\n{e}\n"))
            if manage_loader:
                self.after(0, self.stop_loader)
            return

        temp_ctx = None
        run_path = None
        run_cwd = None

        if self.run_mode == "active_file" and self.current_file_path:
            try:
                run_path = self.current_file_path
                run_cwd = os.path.dirname(run_path) or os.getcwd()
                with open(run_path, "w", encoding="utf-8") as f:
                    f.write(code_to_write)
                self.after(0, self._mark_editor_saved)
            except Exception as e:
                self.after(0, lambda err=str(e): self._append_output(f"Could not save active file, falling back to temp run: {err}\n"))
                run_path = None

        if run_path is None:
            temp_ctx = tempfile.TemporaryDirectory()
            run_cwd = temp_ctx.name
            run_path = os.path.join(temp_ctx.name, "snippet.py")
            with open(run_path, "w", encoding="utf-8") as f:
                f.write(code_to_write)

        cmd = [sys.executable, "-u", run_path]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        self.after(0, self._clear_output_panel)
        self.after(0, lambda: self._append_output(f"[Run started {time.strftime('%H:%M:%S')}]\n$ {' '.join(cmd)}\n\n"))
        self.after(0, lambda: self.status_label.configure(text="Running engine code..."))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=run_cwd,
                env=env,
                bufsize=1,
            )
            self.current_proc = proc

            def reader(stream, prefix=""):
                try:
                    for line in iter(stream.readline, ""):
                        if line == "":
                            break
                        safe_line = self._sanitize_text(line)
                        self.after(0, lambda ln=prefix + safe_line: self._append_output(ln))
                finally:
                    try:
                        stream.close()
                    except Exception:
                        pass

            t1 = threading.Thread(target=reader, args=(proc.stdout, ""), daemon=True)
            t2 = threading.Thread(target=reader, args=(proc.stderr, "ERR: "), daemon=True)
            t1.start()
            t2.start()

            try:
                proc.wait(timeout=self.run_timeout_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.after(0, lambda: self._append_output(f"\nExecution timed out after {self.run_timeout_sec}s.\n"))

            t1.join(timeout=0.2)
            t2.join(timeout=0.2)

            rc = proc.returncode
            self.after(0, lambda: self._append_output(f"\n[Process exited with code {rc}]\n"))
        except Exception:
            tb = traceback.format_exc()
            self.after(0, lambda txt=tb: self._append_output("\n" + txt + "\n"))
        finally:
            self.current_proc = None
            if temp_ctx is not None:
                try:
                    temp_ctx.cleanup()
                except Exception:
                    pass
            self.after(0, self._refresh_status)
            if manage_loader:
                self.after(0, self.stop_loader)

    def _append_output(self, text):
        try:
            self.output_text.config(state="normal")
            self.output_text.insert("end", text)
            self.output_text.see("end")
            self.output_text.config(state="disabled")
        except Exception:
            pass

    def _clear_output_panel(self):
        try:
            self.output_text.config(state="normal")
            self.output_text.delete("1.0", "end")
            self.output_text.config(state="disabled")
        except Exception:
            pass

    def _kill_current_proc(self):
        proc = getattr(self, "current_proc", None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    proc.kill()
                self._append_output("\n[Process killed by user]\n")
            except Exception:
                pass
        self.current_proc = None

    # -------------------- FILE OPS --------------------
    def _open_snippet(self, path=None, from_restore=False):
        fn = path
        if not fn:
            fn = filedialog.askopenfilename(
                title="Open Python file",
                filetypes=[("Python files", "*.py"), ("Text files", "*.txt"), ("All files", "*.*")],
            )
        if not fn:
            return False

        try:
            with open(fn, "r", encoding="utf-8") as f:
                data = f.read()
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", data)
            self.current_file_path = fn
            self.last_opened_file = fn
            self.editor_dirty = False
            self.editor.edit_modified(False)
            self._highlight_syntax()
            self._update_file_label()
            self._save_preferences()
            if not from_restore:
                self._set_status_temporary(f"Opened {os.path.basename(fn)}", duration=1800)
            return True
        except Exception as e:
            self._set_status_temporary(f"Open failed: {e}", duration=2400)
            return False

    def _save_snippet(self, force_dialog=False):
        fn = self.current_file_path
        if force_dialog or not fn:
            fn = filedialog.asksaveasfilename(
                defaultextension=".py",
                filetypes=[("Python files", "*.py"), ("Text files", "*.txt"), ("All files", "*.*")],
                title="Save engine code as",
            )
        if not fn:
            return False

        try:
            content = self.editor.get("1.0", "end-1c")
            with open(fn, "w", encoding="utf-8") as f:
                f.write(content)
            self.current_file_path = fn
            self.last_opened_file = fn
            self.editor_dirty = False
            self.editor.edit_modified(False)
            self._update_file_label()
            self._save_preferences()
            self._set_status_temporary(f"Saved {os.path.basename(fn)}", duration=1800)
            return True
        except Exception as e:
            self._set_status_temporary(f"Save failed: {e}", duration=2400)
            return False

    def _update_file_label(self):
        if self.current_file_path:
            name = os.path.basename(self.current_file_path)
            suffix = " *" if self.editor_dirty else ""
            self.file_label.configure(text=f"Engine file: {name}{suffix}")
        else:
            suffix = " *" if self.editor_dirty else ""
            self.file_label.configure(text=f"Engine file: session draft{suffix}")

    def _mark_editor_dirty(self):
        if not self.editor_dirty:
            self.editor_dirty = True
            self._update_file_label()

    def _mark_editor_saved(self):
        self.editor_dirty = False
        self._update_file_label()

    def _update_run_mode_badge(self):
        txt = "Run: Active File" if self.run_mode == "active_file" else "Run: Temp Sandbox"
        self.run_mode_badge.configure(text=txt)

    # -------------------- SYNTAX + SANITIZE --------------------
    def _setup_editor_tags(self):
        try:
            self.editor.tag_config("kw", foreground="#B25A2A")
            self.editor.tag_config("str", foreground="#0D7A5A")
            self.editor.tag_config("comment", foreground=MUTED)
            self.editor.tag_config("builtin", foreground="#9A4E1D")
        except Exception:
            pass

    def _highlight_syntax(self, event=None):
        try:
            text = self.editor.get("1.0", "end-1c")
            for tag in ["kw", "str", "comment", "builtin"]:
                self.editor.tag_remove(tag, "1.0", "end")

            for m in re.finditer(r"#.*", text):
                self.editor.tag_add("comment", f"1.0+{m.start()}c", f"1.0+{m.end()}c")

            for m in re.finditer(r"('(?:\\.|[^\\'])*'|\"(?:\\.|[^\\\"])*\")", text):
                self.editor.tag_add("str", f"1.0+{m.start()}c", f"1.0+{m.end()}c")

            kw = r"\b(?:def|class|if|else|elif|for|while|try|except|finally|with|return|import|from|as|pass|break|continue|in|is|and|or|not|lambda)\b"
            for m in re.finditer(kw, text):
                self.editor.tag_add("kw", f"1.0+{m.start()}c", f"1.0+{m.end()}c")

            bi = r"\b(?:print|len|range|open|int|str|float|list|dict|set|tuple|enumerate|zip|map|sum|min|max)\b"
            for m in re.finditer(bi, text):
                self.editor.tag_add("builtin", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        except Exception:
            pass

    def _on_editor_modified(self, event=None):
        try:
            if self.editor.edit_modified():
                self._mark_editor_dirty()
                self._schedule_session_autosave()
                self.after(120, self._highlight_syntax)
                self.editor.edit_modified(False)
        except Exception:
            pass

    def _sanitize_text(self, text, limit=80, keep=10):
        try:
            def _repl(m):
                ch = m.group(1)
                n = len(m.group(0))
                return ch * keep + f"...[truncated {n} chars]"

            pattern = r"(.)\\1{" + str(limit) + r",}"
            text = re.sub(pattern, _repl, text)

            def _tok_repl(m):
                tok = m.group(0)
                n = len(tok)
                keep_tok = 60
                return tok[:keep_tok] + f"...[truncated {n - keep_tok} chars]"

            text = re.sub(r"\S{200,}", _tok_repl, text)

            lines = text.splitlines(True)
            out_lines = []
            max_line = 1100
            for ln in lines:
                if len(ln) > max_line:
                    out_lines.append(ln[:max_line] + f"...[truncated {len(ln) - max_line} chars]\n")
                else:
                    out_lines.append(ln)
            total = "".join(out_lines)

            max_total = 220000
            if len(total) > max_total:
                return total[:max_total] + f"\n...[truncated {len(total) - max_total} chars]"
            return total
        except Exception:
            cleaned = "".join(c for c in text if (c.isprintable() or c in "\n\t"))
            if len(cleaned) > 220000:
                return cleaned[:220000] + "\n...[truncated]"
            return cleaned

    # -------------------- MISC EDITOR UTILS --------------------
    def _apply_minimal_edits_to_editor(self, generated):
        try:
            orig = self.editor.get("1.0", "end-1c")
            if orig == generated:
                return
            sm = difflib.SequenceMatcher(None, orig, generated)
            ops = sm.get_opcodes()
            for tag, i1, i2, j1, j2 in reversed(ops):
                if tag == "equal":
                    continue
                start = f"1.0+{i1}c"
                end = f"1.0+{i2}c"
                if i2 > i1:
                    self.editor.delete(start, end)
                rep = generated[j1:j2]
                if rep:
                    self.editor.insert(start, rep)
        except Exception:
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", generated)

    def _ai_fill(self):
        try:
            sel = self.editor.tag_ranges("sel")
            if sel:
                code = self.editor.get(sel[0], sel[1])
            else:
                code = self.editor.get("1.0", "end-1c")
        except Exception:
            sel = None
            code = self.editor.get("1.0", "end-1c")

        instr = simpledialog.askstring("AI Fill", "Describe how to modify the selected code:")
        if not instr:
            return

        prompt = (
            "You are editing Python code. "
            "Double check that it works before giving the user it"
            "Return only the updated code in a fenced Python block.\n\n"
            f"Current code:\n```python\n{code}\n```\n\n"
            f"Instruction:\n{instr}\n"
        )

        self.start_loader()
        self.status_label.configure(text="AI Fill running...")
        threading.Thread(target=self._generate_and_insert, args=(prompt, sel), daemon=True).start()

    def _generate_and_insert(self, prompt, selection_ranges=None):
        try:
            resp = self._generate_text(prompt=prompt, max_tokens=self.coding_max_tokens, mode="coding")
            blocks = self._extract_code_blocks(resp)
            new_code = blocks[-1] if blocks else resp

            def apply_changes():
                if selection_ranges:
                    self.editor.delete(selection_ranges[0], selection_ranges[1])
                    self.editor.insert(selection_ranges[0], new_code)
                else:
                    self._apply_minimal_edits_to_editor(new_code)
                self._highlight_syntax()
                self._mark_editor_dirty()
                self._schedule_session_autosave()
                self._append_assistant(self.coding_card["text"], resp, label="Coding AI")
                if self.auto_run_coding:
                    code_to_run = self.editor.get("1.0", "end-1c")
                    threading.Thread(target=self._run_code, args=(code_to_run, False), daemon=True).start()

            self.after(0, apply_changes)
        finally:
            self.after(0, self.stop_loader)
            self.after(0, self._refresh_status)

    def _create_shell(self):
        code = self.editor.get("1.0", "end-1c")
        wrapper = (
            "import tempfile\n"
            "import os\n"
            "import sys\n\n"
            "code = r\"\"\"" + code.replace('"""', '\\"\\"\\"') + "\"\"\"\n\n"
            "with tempfile.TemporaryDirectory() as tmpdir:\n"
            "    path = os.path.join(tmpdir, 'snippet.py')\n"
            "    with open(path, 'w', encoding='utf-8') as f:\n"
            "        f.write(code)\n"
            "    os.execv(sys.executable, [sys.executable, path])\n"
        )

        fn = filedialog.asksaveasfilename(
            defaultextension=".py",
            initialfile="run_snippet.py",
            filetypes=[("Python files", "*.py"), ("All files", "*.*")],
        )
        if not fn:
            return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                f.write(wrapper)
            self._set_status_temporary(f"Created wrapper: {os.path.basename(fn)}", duration=2000)
        except Exception as e:
            self._set_status_temporary(f"Wrapper failed: {e}", duration=2400)

    # -------------------- BUTTONS / EVENTS --------------------
    def start_loader(self):
        try:
            # increment active task count
            self._active_tasks = getattr(self, "_active_tasks", 0) + 1
            # show loader when first active task begins
            if self._active_tasks == 1:
                self.loader_frame.pack(side="right", padx=(0, 8))
                self.loader.pack()
                self.loader.start()
        except Exception:
            pass

        disable_buttons = [
            "open_button",
            "save_button",
            "save_as_button",
            "run_button",
            "ai_fill_btn",
            "shell_btn",
            "ideas_btn",
            "settings_btn",
            "clear_chat_btn",
        ]
        for btn_name in disable_buttons:
            try:
                btn = getattr(self, btn_name, None)
                if btn is not None:
                    btn.configure(state="disabled")
            except Exception:
                pass

        for widget in [self.general_card["entry"], self.general_card["ask"], self.coding_card["entry"], self.coding_card["ask"]]:
            try:
                widget.configure(state="disabled")
            except Exception:
                pass

    def stop_loader(self):
        try:
            # decrement active tasks
            self._active_tasks = max(0, getattr(self, "_active_tasks", 0) - 1)
            if self._active_tasks == 0:
                self.loader.stop()
                self.loader_frame.pack_forget()
        except Exception:
            pass

        enable_buttons = [
            "open_button",
            "save_button",
            "save_as_button",
            "run_button",
            "ai_fill_btn",
            "shell_btn",
            "ideas_btn",
            "settings_btn",
            "clear_chat_btn",
        ]
        for btn_name in enable_buttons:
            try:
                btn = getattr(self, btn_name, None)
                if btn is not None:
                    btn.configure(state="normal")
            except Exception:
                pass

        for widget in [self.general_card["entry"], self.general_card["ask"], self.coding_card["entry"], self.coding_card["ask"]]:
            try:
                widget.configure(state="normal")
            except Exception:
                pass

        # Refresh status: if no active tasks and no running process, show Idle
        try:
            self._refresh_status()
        except Exception:
            pass

    def _set_status_temporary(self, msg, duration=3000):
        try:
            prev = self.status_label.cget("text")
            self.status_label.configure(text=msg)
            # after the duration, refresh status (so Idle can be restored rather than previous transient msg)
            self.after(duration, lambda: self._refresh_status())
        except Exception:
            pass

    def _refresh_status(self):
        """Set a sensible status label based on model/load/run state.

        Rules:
        - If the model is loading and not failed, show model loading text.
        - If model failed or not installed, show those messages.
        - If there's a running engine process, show Running engine code...
        - If there are active tasks (loader), keep existing message.
        - Otherwise show Idle.
        """
        try:
            # model not installed
            if not MLX_AVAILABLE:
                self.status_label.configure(text="Model: not installed")
                return
            # model is loading
            if not self.model_ready and not self.model_failed:
                self.status_label.configure(text=f"Model: loading ({DEVICE})")
                return
            if self.model_failed:
                self.status_label.configure(text="Model: failed")
                return
            # if a process is running
            proc = getattr(self, "current_proc", None)
            if proc is not None and proc.poll() is None:
                self.status_label.configure(text="Running engine code...")
                return
            # if there are active tasks, don't force Idle (leave current text)
            if getattr(self, "_active_tasks", 0) > 0:
                return
            # otherwise Idle (show model readiness as well)
            self.status_label.configure(text=f"Idle — Model: ready ({DEVICE})")
        except Exception:
            pass

    # -------------------- SLASH / ATTACH HELPERS --------------------
    def _on_coding_entry_key(self, event):
        """Detect slash trigger and open the attach menu."""
        try:
            ch = getattr(event, "char", "")
            # Trigger only when '/' typed or when user types '/' anywhere resulting in entry ending with '/'
            entry = self.coding_card["entry"]
            if ch == '/' or entry.get().endswith('/'):
                # Post menu under the widget
                x = entry.winfo_rootx()
                y = entry.winfo_rooty() + entry.winfo_height()
                self._show_coding_slash_menu(x, y)
        except Exception:
            pass

    def _stop_response(self, kind=None):
        """Cancel an in-progress AI response for the given kind (general/coding) by bumping its token."""
        try:
            if kind in ("general", "coding"):
                self.abort_tokens[kind] = self.abort_tokens.get(kind, 0) + 1
                self._set_status_temporary(f"Stopped {kind} response", duration=900)
            else:
                # Cancel both
                for k in list(self.abort_tokens.keys()):
                    self.abort_tokens[k] = self.abort_tokens.get(k, 0) + 1
                self._set_status_temporary("Stopped responses", duration=900)
        except Exception:
            pass

    def _show_coding_slash_menu(self, x, y):
        menu = tk.Menu(self, tearoff=0)
        # Insert tag into entry instead of immediate attach
        menu.add_command(label="/Runtime", command=lambda: self._insert_attachment_tag_into_entry("Runtime"))
        menu.add_command(label="/Engine", command=lambda: self._insert_attachment_tag_into_entry("Engine"))
        menu.add_command(label="/Errors", command=lambda: self._insert_attachment_tag_into_entry("Errors"))
        menu.add_command(label="/General", command=lambda: self._insert_attachment_tag_into_entry("General"))
        try:
            menu.post(x, y)
        except Exception:
            pass

    # -------------------- CODING ATTACHMENTS UI --------------------
    def _insert_attachment_tag_into_entry(self, tag: str):
        """Insert a short attachment tag into the coding entry (e.g. '/Errors').
        If the entry currently ends with '/', replace it.
        """
        try:
            if not hasattr(self, "coding_card"):
                return
            var = self.coding_card["var"]
            entry = self.coding_card["entry"]
            cur = var.get()
            # If user typed a slash at the end, replace it with /Tag
            if cur.endswith("/"):
                new = cur[:-1] + f"/{tag} "
            else:
                # append tag
                new = cur + (" " if cur and not cur.endswith(" ") else "") + f"/{tag} "
            var.set(new)
            try:
                entry.focus_set()
            except Exception:
                pass
        except Exception:
            pass

    def _add_coding_attachment(self, key: str, label: str, payload: str):
        """Toggle an attachment for the coding prompt. If added, render highlight; if exists, remove it and update the input label."""
        try:
            if not payload:
                return
            existing = key in self.coding_attachments
            if existing:
                # remove
                del self.coding_attachments[key]
                self._set_status_temporary(f"Detached {label}", duration=1200)
            else:
                self.coding_attachments[key] = payload
                self._set_status_temporary(f"Attached {label}", duration=1200)
            self._render_coding_attachments()
            self._update_coding_entry_attachment_label()
        except Exception:
            pass

    def _remove_coding_attachment(self, key: str):
        try:
            if key in self.coding_attachments:
                del self.coding_attachments[key]
                self._render_coding_attachments()
                self._update_coding_entry_attachment_label()
                self._set_status_temporary(f"Detached {key}", duration=1200)
        except Exception:
            pass

    def _render_coding_attachments(self):
        """Render small clickable labels for each attachment under the coding chat.
        Highlighted/underlined when attached. Clicking removes it. A small Insert button
        beside each label inserts that attachment into the engine editor.
        """
        try:
            frame = self.coding_card.get("attachments_frame") if hasattr(self, "coding_card") else None
            if frame is None:
                return
            # clear existing widgets
            for child in frame.winfo_children():
                try:
                    child.destroy()
                except Exception:
                    pass

            if not self.coding_attachments:
                return

            col = 0
            for k, payload in list(self.coding_attachments.items()):
                lab = tk.Label(frame, text=k, bg=ACCENT, fg="white", cursor="hand2", font=(BASE_FONT[0], 10, "underline"))
                lab.grid(row=0, column=col, padx=(0, 4), pady=4)
                lab.bind("<Button-1>", lambda e, key=k: self._remove_coding_attachment(key))
                # Insert button
                try:
                    btn = ctk.CTkButton(frame, text="Insert", width=64, fg_color=SURFACE_ALT, hover_color=SOFT, text_color=TEXT, command=lambda key=k: self._insert_attachment_into_editor(key))
                    btn.grid(row=0, column=col + 1, padx=(0, 8), pady=2)
                except Exception:
                    pass
                col += 2
        except Exception:
            pass

    def _update_coding_entry_attachment_label(self):
        """Show an explicit label/prefix in the coding entry that lists attached resources.
        The prefix is only visual; it will be stripped when sending the query.
        """
        try:
            if not hasattr(self, "coding_card"):
                return
            var = self.coding_card["var"]
            current = var.get()
            # remove old prefix if present
            old_prefix = getattr(self, "_coding_attach_prefix", "")
            if old_prefix and current.startswith(old_prefix):
                current = current[len(old_prefix):]
            if not self.coding_attachments:
                self._coding_attach_prefix = ""
                var.set(current.lstrip())
                return
            keys = list(self.coding_attachments.keys())
            prefix = "[Attached: " + " | ".join(keys) + "] "
            self._coding_attach_prefix = prefix
            # Preserve user text, but ensure prefix is present
            new_val = prefix + current.lstrip()
            var.set(new_val)
        except Exception:
            pass

    def _insert_attachment_into_editor(self, key: str):
        """Insert the attachment payload into the engine editor. For engine code attachments
        extract code blocks; otherwise insert as commented block.
        """
        try:
            payload = self.coding_attachments.get(key)
            if not payload:
                self._set_status_temporary(f"No payload for {key}", duration=1200)
                return
            # If payload has fenced code, prefer inserting code only
            blocks = self._extract_code_blocks(payload)
            if blocks:
                code_to_insert = blocks[-1]
            else:
                # comment the payload
                commented = "# " + payload.replace("\n", "\n# ")
                code_to_insert = "\n" + commented + "\n"

            # Insert into editor (append)
            current = self.editor.get("1.0", "end-1c")
            if current.strip():
                self.editor.insert("end", "\n\n")
            self.editor.insert("end", code_to_insert)
            self._highlight_syntax()
            self._mark_editor_dirty()
            self._schedule_session_autosave()
            self._set_status_temporary(f"Inserted {key} into editor", duration=1400)
        except Exception:
            pass

    def _insert_into_coding_entry(self, text):
        try:
            var = self.coding_card["var"]
            current = var.get()
            # remove trailing slash if present
            if current.endswith('/'):
                current = current[:-1].rstrip()
            if current and not current.endswith('\n'):
                new = current + "\n\n" + text
            else:
                new = current + text
            var.set(new)
            # focus the entry
            try:
                self.coding_card["entry"].focus_set()
            except Exception:
                pass
        except Exception:
            pass

    def _attach_runtime_output_to_coding(self):
        try:
            out = self.output_text.get("1.0", "end-1c").strip()
            if not out:
                self._set_status_temporary("No runtime output available", duration=1400)
                return
            snippet = out[-1200:]
            payload = f"--- Runtime output (truncated) ---\n{snippet}\n--- end ---"
            # toggle attachment
            self._add_coding_attachment("Runtime output", "Runtime output", payload)
        except Exception:
            pass

    def _attach_editor_to_coding(self):
        try:
            code = self.editor.get("1.0", "end-1c").strip()
            if not code:
                self._set_status_temporary("Engine textbox is empty", duration=1400)
                return
            snippet = code[:1600]
            payload = f"--- Engine code (truncated) ---\n```python\n{snippet}\n```\n--- end ---"
            self._add_coding_attachment("Engine code", "Engine code", payload)
        except Exception:
            pass

    def _attach_errors_to_coding(self):
        try:
            out = self.output_text.get("1.0", "end-1c")
            lines = [l for l in out.splitlines() if l.strip().startswith("ERR:") or "Traceback" in l or "Exception" in l]
            if not lines:
                self._set_status_temporary("No error lines found in runtime output", duration=1400)
                return
            snippet = "\n".join(lines[-80:])
            payload = f"--- Errors (truncated) ---\n{snippet}\n--- end ---"
            self._add_coding_attachment("Errors", "Errors", payload)
        except Exception:
            pass

    def _attach_general_chat_to_coding(self):
        try:
            text = self.general_card["text"].get("1.0", "end-1c").strip()
            if not text:
                self._set_status_temporary("General AI chat is empty", duration=1400)
                return
            snippet = text[-1200:]
            payload = f"--- General AI chat (truncated) ---\n{snippet}\n--- end ---"
            self._add_coding_attachment("General chat", "General chat", payload)
        except Exception:
            pass

    def _on_open_clicked(self):
        self._open_snippet()

    def _on_save_clicked(self):
        self._save_snippet(force_dialog=False)

    def _on_save_as_clicked(self):
        self._save_snippet(force_dialog=True)

    def _on_run_clicked(self):
        self._set_status_temporary("Running engine code...")
        self.start_loader()
        code = self.editor.get("1.0", "end-1c")
        threading.Thread(target=self._run_code, args=(code, True), daemon=True).start()

    def _on_stop_clicked(self):
        self._set_status_temporary("Stopping process...", duration=1800)
        self._kill_current_proc()
        self.stop_loader()

    def _on_ai_fill_clicked(self):
        self._ai_fill()

    def _on_create_shell_clicked(self):
        self._create_shell()

    def _on_clear_clicked(self):
        self._clear_chat_widget(self.general_card["text"])
        self._clear_chat_widget(self.coding_card["text"])
        self._set_status_temporary("Both chats cleared", duration=1500)

    def _toggle_auto_run(self):
        self.auto_run_coding = not self.auto_run_coding
        self._refresh_coding_controls()
        self._save_preferences()
        self._set_status_temporary(
            "Coding auto-run enabled" if self.auto_run_coding else "Coding auto-run disabled",
            duration=1800,
        )

    def _toggle_insert_mode(self):
        self.insert_mode = "append" if self.insert_mode == "replace" else "replace"
        self._refresh_coding_controls()
        self._save_preferences()
        self._set_status_temporary(
            "Insert mode: Append" if self.insert_mode == "append" else "Insert mode: Replace",
            duration=1800,
        )

    def _refresh_coding_controls(self):
        try:
            self.auto_run_btn.configure(text="Auto Run: On" if self.auto_run_coding else "Auto Run: Off")
            self.insert_mode_btn.configure(text="Insert: Replace" if self.insert_mode == "replace" else "Insert: Append")
        except Exception:
            pass

    def _share_project_ideas(self):
        ideas = random.sample(self.project_ideas, k=min(6, len(self.project_ideas)))
        body = "Here are some project upgrade ideas:\n\n" + "\n".join([f"{i + 1}. {idea}" for i, idea in enumerate(ideas)])
        self._append_assistant(self.general_card["text"], body, label="Idea Coach")
        self._set_status_temporary("Shared new project ideas in General AI", duration=1800)

    def _coerce_int(self, value, min_v, max_v, fallback):
        try:
            n = int(str(value).strip())
            return max(min_v, min(max_v, n))
        except Exception:
            return fallback

    def _bind_shortcuts(self):
        self.general_card["entry"].bind("<Return>", self.ask_general_ai)
        self.coding_card["entry"].bind("<Return>", self.ask_coding_ai)
        # detect '/' trigger in coding entry to open attach menu
        try:
            self.coding_card["entry"].bind("<KeyRelease>", self._on_coding_entry_key)
        except Exception:
            pass

        self.bind_all("<Control-s>", self._shortcut_save)
        self.bind_all("<Command-s>", self._shortcut_save)
        self.bind_all("<Control-o>", self._shortcut_open)
        self.bind_all("<Command-o>", self._shortcut_open)

    def _shortcut_save(self, event=None):
        self._on_save_clicked()
        return "break"

    def _shortcut_open(self, event=None):
        self._on_open_clicked()
        return "break"


if __name__ == "__main__":
    app = Code9Claude()
    app.mainloop()
