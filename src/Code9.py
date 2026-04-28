import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, simpledialog
import subprocess
import tempfile
import os
import shutil
import threading
import sys
import traceback
import re
from datetime import datetime
import time
import difflib
import json
import random
import inspect
import ast
import importlib.util
from Shinzen import Shinzen
from chat_sanitizer import ChatSanitizer
from attachment_manager import AttachmentManager
from model_wrapper import ModelWrapper
from config import Config

currentTime = datetime.now()

timedGreeting = ""

# Reduce tokenizer worker/process side effects and noisy startup behavior.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Optional MLX integration
try:
    from mlx_lm import load, generate
    try:
        from mlx_lm import stream_generate
    except Exception:
        stream_generate = None
    try:
        from mlx_lm.sample_utils import make_sampler, make_logits_processors
    except Exception:
        make_sampler = None
        make_logits_processors = None
    MLX_AVAILABLE = True
except Exception:
    MLX_AVAILABLE = False

    def load(model_name, **kwargs):
        return None, None

    def generate(model, tokenizer, prompt, max_tokens=200):
        return ""

    stream_generate = None
    make_sampler = None
    make_logits_processors = None

if MLX_AVAILABLE:
    try:
        import mlx.core as mx
        MLX_CORE_AVAILABLE = True
    except Exception:
        mx = None
        MLX_CORE_AVAILABLE = False
else:
    mx = None
    MLX_CORE_AVAILABLE = False


# Detect device for model loading (MPS if available)
def detect_device():
    if MLX_AVAILABLE:
        return "mlx-metal"
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

# Warm minimalist + soft glass palette
BG = "#F5EFE7"
SURFACE = "#FFFDFB"
SURFACE_ALT = "#F6F2ED"
SOFT = "#E6D8C7"
ACCENT = "#C07A5B"
ACCENT_HOVER = "#A8674A"
TEXT = "#352922"
MUTED = "#826D5D"
BORDER = "#E4D8CB"
OUTPUT_BG = "#FDF9F4"
GLASS = "#FFF8F0"

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


def choose_font(fallback_size=13):
    import tkinter.font as tkfont
    candidates = [
        "Tiempos Text",
        "SF Pro Text",
        "San Francisco",
        "New York",
        "Avenir Next",
        "Helvetica Neue",
        "Helvetica",
        "Times New Roman",
    ]
    try:
        available = set(tkfont.families())
        for name in candidates:
            if name in available:
                return (name, fallback_size)
    except Exception:
        pass
    return ("Times New Roman", fallback_size)


BASE_FONT = choose_font(13)
MONO_FONT = (choose_font(13)[0], 13)

WELCOME_VARIANTS = [
    "Welcome back, {Username}.",
    "Shinzen is happy to see you, {Username}!",
    "Ready to code, {Username}?",
    "Let's build something great today, {Username}.",
    "{Username}, your coding companion is here.",
    "Good to see you, {Username}. Let's get coding!",
    "How are you {Username}?",
    "{timedGreeting}, {Username}.",
]

CODING_MODEL_CANDIDATES = [
    "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    "mlx-community/DeepSeek-Coder-V2-Lite-Instruct-4bit-mlx",
    "mlx-community/starcoder2-7b-4bit",
]

SHINZEN_MODEL_CANDIDATES = [
    "mlx-community/Phi-3.5-mini-instruct-4bit",
    "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
]


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


class Code9(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Code9 - AI-Powered Python Engine")
        self.geometry("1360x860")
        self.minsize(1120, 740)
        self.configure(fg_color=BG)

        # Model/runtime state — dual model: coding model + fast Phi for Shinzen
        self.model = None
        self.tokenizer = None
        self.model_ready = False
        self.model_failed = False
        # Phi (fast) model for Shinzen bubble comments
        self.phi_model = None
        self.phi_tokenizer = None
        self.phi_ready = False
        self.current_proc = None
        self.current_out_text = None
        self.current_file_path = None
        self.editor_dirty = False
        self._autosave_job = None
        self._settings_window = None
        self._help_window = None
        self._presence_reset_job = None
        self._welcome_pool = []
        self._chat_welcome_state = {}
        self._chat_widget_kind = {}
        self._typing_reset_job = None
        self._bubble_hide_job = None
        self._bubble_anim_job = None
        self._bubble_visible = False
        self._runtime_popup_only = True
        self._runtime_win = None
        self._runtime_text = None
        self._runtime_entry = None
        self._mlx_load_lock = threading.Lock()

        # Persistent paths
        self.config_dir = os.path.join(os.path.expanduser("~"), ".code9")
        self.settings_path = os.path.join(self.config_dir, "settings.json")
        self.session_path = os.path.join(self.config_dir, "session_draft.py")
        os.makedirs(self.config_dir, exist_ok=True)
        self.config = Config(self.settings_path)

        # Defaults (overridden by settings)
        self.username = os.getenv("USER") or os.getenv("USERNAME") or "Coder"
        self.auto_run_coding = True
        self.insert_mode = "replace"          # replace | append | noop
        self.run_mode = "workspace"                # temp | active_file | workspace
        self.enable_typewriter = True
        self.coding_max_tokens = 900
        self.run_timeout_sec = 60
        self.persist_session = True
        self.restore_last_file = False
        self.last_opened_file = ""
        self.auto_install_missing_imports = False
        self.python_exec_path = sys.executable
        self.project_root = os.getcwd()
        # Link Shinzen suggestions automatically into the Coding AI prompts
        self.include_shinzen_in_coding = True
        self.stop_on_bad_response = True
        self.require_code_block_for_injection = True
        self.preferred_coding_model = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
        self.preferred_shinzen_model = "mlx-community/Phi-3.5-mini-instruct-4bit"
        self.loaded_coding_model_name = "Qwen2.5-Coder-7B-Instruct-4bit"
        self.loaded_shinzen_model_name = "Phi-3.5-mini-instruct-4bit"
        self._last_ai_injection = None
        self.shinzen_feedback_cooldown_sec = 20
        self.shinzen_refresh_timer_sec = 30
        self.shinzen_idle_suggestions_enabled = True
        self.shinzen_idle_interval_sec = 60
        self.shinzen_idle_threshold_sec = 18
        self._shinzen_analysis_inflight = False
        self._shinzen_job = None
        self._shinzen_periodic_job = None
        self._shinzen_force_refresh = False
        self._shinzen_idle_hint = False
        self._last_shinzen_digest = ""
        self._last_shinzen_comment = ""
        self._last_shinzen_comment_ts = 0.0
        self._last_shinzen_issue_count = 0
        self._last_typing_ts = time.time()
        self._last_idle_suggestion_ts = 0.0

        # Safety and performance controls
        # Verifier adds an extra full model pass, so keep it off by default for speed.
        self.enable_verifier = False
        self.safe_defaults = {
            "temperature": 0.0,
            "top_p": 0.0,
            "top_k": 0,
            "repetition_penalty": 1.0,
            "max_kv_size": 8192,
            "prefill_step_size": 1024,
            "kv_bits": 8,
            "kv_group_size": 64,
            "quantized_kv_start": 1024,
        }
        #Ideas for coding
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
        self.model_wrapper = ModelWrapper(load_fn=load, generate_fn=generate)

        # Tokens used to cancel in-progress AI responses (increment to cancel)
        self.abort_tokens = {"coding": 0}
        # Active tasks counter used to determine Idle status
        self._active_tasks = 0
        self._ui_busy = False
        # Attachments for coding prompts: key -> payload
        self.coding_attachments = {}

        # Engine-heavy split: left ~75%, right ~25%
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1, minsize=260)
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
        self._refresh_status()
        self._start_shinzen_loop()

        if MLX_AVAILABLE:
            self._set_presence_message(f"Loading models on {DEVICE}...", mood="thinking")
            threading.Thread(target=self._load_models_serial, daemon=True).start()
        else:
            self._set_presence_message("MLX model runtime not found. You can still run local Python code.", mood="concern")
    
    def _on_editor_typing(self, event=None):
        # 1. Put Shinzen into a short interactive typing expression.
        try:
            if hasattr(self, "shinzen") and self.shinzen is not None:
                if hasattr(self.shinzen, "trigger"):
                    self.shinzen.trigger("typing", hold_ms=900)
                else:
                    self.shinzen.set_state("peering")
        except Exception:
            pass
        self._last_typing_ts = time.time()
        self._schedule_shinzen_analysis(delay=950, force=False)

        # 2. Reset the presence message to normal after 1.5 seconds of no typing
        if self._typing_reset_job is not None:
            self.after_cancel(self._typing_reset_job)
        self._typing_reset_job = self.after(1500, self._stop_peering)

    def _stop_peering(self):
        self._typing_reset_job = None
        try:
            self._refresh_status()
        except Exception:
            if hasattr(self, "shinzen"):
                self.shinzen.set_state("idle")
    # -------------------- UI BUILDERS --------------------
    def _build_topbar(self):
        self.topbar = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, height=88)
        self.topbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.topbar.grid_propagate(False)

        title_wrap = tk.Frame(self.topbar, bg=BG)
        title_wrap.pack(side="left", padx=24, pady=12)

        self.title_label = ctk.CTkLabel(
            title_wrap,
            text="Code9",
            font=(BASE_FONT[0], 60, "bold"),
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

        # Status text is now fully integrated into the Shinzen speech bubble on the right.
        self.status_label = None

        # Top-right loader removed — Shinzen will be shown in the right column (larger instance)
        self.btn_bar = tk.Frame(self.topbar, bg=BG)
        self.btn_bar.pack(side="right", padx=10, pady=12)

        self.open_button = self._make_toolbar_button(self.btn_bar, "Open", 70, self._on_open_clicked)
        self.open_button.pack(side="left", padx=4)

        self.open_project_button = self._make_toolbar_button(self.btn_bar, "Project", 84, self._on_open_project_clicked)
        self.open_project_button.pack(side="left", padx=4)

        self.save_button = self._make_toolbar_button(self.btn_bar, "Save", 70, self._on_save_clicked)
        self.save_button.pack(side="left", padx=4)

        self.save_as_button = self._make_toolbar_button(self.btn_bar, "Save As", 84, self._on_save_as_clicked)
        self.save_as_button.pack(side="left", padx=4)

        self.run_button = self._make_toolbar_button(self.btn_bar, "Run", 72, self._on_run_clicked, primary=True)
        self.run_button.pack(side="left", padx=4)

        self.stop_button = self._make_toolbar_button(
            self.btn_bar,
            "Stop",
            72,
            self._on_stop_clicked,
            fg="#EAC8BD",
            hover="#DEB0A2",
        )
        self.stop_button.pack(side="left", padx=4)

        self.ai_fill_btn = self._make_toolbar_button(self.btn_bar, "AI Fill", 84, self._on_ai_fill_clicked)
        self.ai_fill_btn.pack(side="left", padx=4)

        self.undo_ai_btn = self._make_toolbar_button(self.btn_bar, "Undo AI", 84, self._undo_last_ai_injection)
        self.undo_ai_btn.pack(side="left", padx=4)

        self.runtime_btn = self._make_toolbar_button(self.btn_bar, "Runtime", 84, self._open_runtime_terminal)
        self.runtime_btn.pack(side="left", padx=4)

        self.shell_btn = self._make_toolbar_button(self.btn_bar, "Shell", 72, self._on_create_shell_clicked)
        self.shell_btn.pack(side="left", padx=4)

        self.ideas_btn = self._make_toolbar_button(self.btn_bar, "Ideas", 70, self.request_shinzen_ideas)
        self.ideas_btn.pack(side="left", padx=4)

        self.settings_btn = self._make_toolbar_button(self.btn_bar, "Settings", 86, self._open_settings)
        self.settings_btn.pack(side="left", padx=4)

        self.help_btn = self._make_toolbar_button(self.btn_bar, "Help", 72, self._open_help)
        self.help_btn.pack(side="left", padx=4)

        self.clear_chat_btn = self._make_toolbar_button(self.btn_bar, "Clear", 70, self._on_clear_clicked)
        self.clear_chat_btn.pack(side="left", padx=4)

    def _make_toolbar_button(self, parent, text, width, command, primary=False, fg=None, hover=None):
        base_fg = ACCENT if primary else SURFACE_ALT
        base_hover = ACCENT_HOVER if primary else SOFT
        text_color = "white" if primary else TEXT
        return ctk.CTkButton(
            parent,
            text=text,
            width=width,
            height=34,
            corner_radius=16,
            fg_color=fg or base_fg,
            hover_color=hover or base_hover,
            text_color=text_color,
            font=(BASE_FONT[0], 12, "bold"),
            command=command,
        )

    def _build_engine_panel(self):
        self.left = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=18)
        self.left.grid(row=1, column=0, padx=(20, 10), pady=18, sticky="nsew")
        self.left.grid_rowconfigure(1, weight=1)
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
        self.editor.bind("<KeyPress>", self._on_editor_typing)  

        self.editor_vsb = tk.Scrollbar(editor_holder, orient="vertical", command=self.editor.yview)
        self.editor_vsb.grid(row=0, column=1, sticky="ns")

        self.editor_hsb = tk.Scrollbar(editor_holder, orient="horizontal", command=self.editor.xview)
        self.editor_hsb.grid(row=1, column=0, sticky="ew")

        self.editor.config(yscrollcommand=self.editor_vsb.set, xscrollcommand=self.editor_hsb.set)

        # Runtime I/O is intentionally not shown inline; it opens in a separate runtime window.
        self.output_text = None
        self.terminal_input = None
        self.inline_output_text = None
        self.inline_terminal_input = None

    def _build_right_panel(self):
        self.right = ctk.CTkFrame(self, fg_color=BG, corner_radius=18, width=290)
        self.right.grid(row=1, column=1, padx=(8, 18), pady=18, sticky="nsew")
        self.right.grid_propagate(False)

        # Row 0: Shinzen; Row 1: coding AI card
        self.right.grid_rowconfigure(0, weight=0)
        self.right.grid_rowconfigure(1, weight=1, minsize=220)
        self.right.grid_columnconfigure(0, weight=1)

        # --- Shinzen row ---
        snail_row = tk.Frame(self.right, bg=BG)
        snail_row.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        snail_row.grid_columnconfigure(0, weight=1)

        # --- Snail (right of bubble) ---
        self.shinzen = Shinzen(
            snail_row,
            sprite_paths=None,
            frame_duration=130,
            size=(148, 148),
            on_click=self._on_snail_clicked,
        )
        self.shinzen.canvas.configure(bg=BG)
        self.shinzen.canvas.grid(row=0, column=0, padx=(4, 0), pady=4, sticky="e")

        try:
            self.shinzen.start()
        except Exception:
            pass

        # Speech bubble overlays the right panel so it never affects Engine width.
        self.shinzen_bubble_outer = tk.Frame(self.right, bg=BG)
        bubble_row = tk.Frame(self.shinzen_bubble_outer, bg=BG)
        bubble_row.pack(fill="both", expand=True)

        bubble_frame = ctk.CTkFrame(
            bubble_row,
            fg_color=GLASS,
            corner_radius=16,
            border_width=1,
            border_color=BORDER,
            width=180,
            height=210,
            )
        bubble_frame.pack(side="left", padx=(0, 0), pady=(0, 0))
        bubble_frame.pack_propagate(False)

        self.shinzen_bubble_text = tk.Text(
            bubble_frame,
            height=4,
            bg=GLASS,
            fg=TEXT,
            bd=0,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            padx=2, # slightly reduced internal padding 
            pady=2,
            state="disabled",
            font=(BASE_FONT[0], 11),
            )
        
        self.shinzen_bubble_text.pack(fill="both", expand=True, padx=8, pady=8) 

        tail = tk.Canvas(bubble_row, width=16, height=24, bg=BG, highlightthickness=0)
        tail.pack(side="left", padx=(0, 0), pady=22)
        tail.create_polygon(1, 12, 14, 5, 14, 19, fill=GLASS, outline=BORDER)

        # --- Coding AI card (below snail+bubble row) ---
        self.coding_card = self._build_chat_card(
            parent=self.right,
            row=1,
            title="AI",
            placeholder="Ask for code, fixes, or refactors...",
            ask_cmd=self._on_coding_ask_clicked,
            kind="coding",
        )

    def _build_chat_card(self, parent, row, title, placeholder, ask_cmd, kind="coding"):
        card = ctk.CTkFrame(parent, fg_color=GLASS, corner_radius=20)
        card.grid(row=row, column=0, sticky="nsew", pady=(0, 10) if row == 0 else (8, 0))
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        header = tk.Frame(card, bg=GLASS)
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 8))
        header.grid_columnconfigure(0, weight=1)

        lbl = ctk.CTkLabel(header, text=title, font=(BASE_FONT[0], 15, "bold"), text_color=TEXT, fg_color=GLASS)
        lbl.grid(row=0, column=0, sticky="w")

        if kind == "coding":
            self.auto_run_btn = ctk.CTkButton(
                header,
                text="Auto Run: On" if self.auto_run_coding else "Auto Run: Off",
                width=104,
                corner_radius=14,
                fg_color=SURFACE_ALT,
                hover_color=SOFT,
                text_color=TEXT,
                command=self._toggle_auto_run,
            )
            self.auto_run_btn.grid(row=0, column=1, padx=(6, 4), sticky="e")

            self.insert_mode_btn = ctk.CTkButton(
                header,
                text=self._insert_mode_button_text(),
                width=112,
                corner_radius=14,
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
            corner_radius=14,
            fg_color=SURFACE_ALT,
            hover_color=SOFT,
            text_color=TEXT,
            command=lambda k=kind: self._stop_response(k),
        )
        stop_btn.grid(row=0, column=3, padx=(6, 0), sticky="e")
        # keep a reference so tests or other code can access it
        if kind == "coding":
            self.coding_stop_btn = stop_btn

        text_wrap = tk.Frame(card, bg=GLASS)
        text_wrap.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        text_wrap.grid_rowconfigure(0, weight=1)
        text_wrap.grid_columnconfigure(0, weight=1)

        chat_text = tk.Text(
            text_wrap,
            bg="#FFFCF8",
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
        self._chat_widget_kind[chat_text] = kind
        self._set_chat_welcome(chat_text, kind=kind)

        # Attachments row (visible only for coding card)
        attachments_frame = tk.Frame(card, bg=GLASS)
        attachments_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        attachments_frame.grid_columnconfigure(0, weight=1)

        input_row = tk.Frame(card, bg=GLASS)
        input_row.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        input_row.grid_columnconfigure(0, weight=1)

        input_var = tk.StringVar()
        input_entry = ctk.CTkEntry(
            input_row,
            placeholder_text=placeholder,
            textvariable=input_var,
            fg_color=SURFACE_ALT,
            corner_radius=15,
            text_color=TEXT,
        )
        input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ask_btn = ctk.CTkButton(
            input_row,
            text="Ask",
            width=70,
            corner_radius=14,
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
            corner_radius=14,
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
            self.config.load()
            data = dict(getattr(self.config, "data", {}) or {})
            self.username = data.get("username", self.username)
            self.auto_run_coding = bool(data.get("auto_run_coding", self.auto_run_coding))
            self.insert_mode = data.get("insert_mode", self.insert_mode) if data.get("insert_mode") in {"replace", "append", "noop"} else self.insert_mode
            self.run_mode = data.get("run_mode", self.run_mode) if data.get("run_mode") in {"temp", "active_file", "workspace"} else self.run_mode
            self.enable_typewriter = bool(data.get("enable_typewriter", self.enable_typewriter))
            self.coding_max_tokens = self._coerce_int(data.get("coding_max_tokens", self.coding_max_tokens), 120, 4000, self.coding_max_tokens)
            self.run_timeout_sec = self._coerce_int(data.get("run_timeout_sec", self.run_timeout_sec), 5, 600, self.run_timeout_sec)
            self.persist_session = bool(data.get("persist_session", self.persist_session))
            self.restore_last_file = bool(data.get("restore_last_file", self.restore_last_file))
            self.last_opened_file = data.get("last_opened_file", "")
            self.auto_install_missing_imports = bool(data.get("auto_install_missing_imports", self.auto_install_missing_imports))
            self.python_exec_path = (data.get("python_exec_path", self.python_exec_path) or self.python_exec_path).strip()
            self.project_root = (data.get("project_root", self.project_root) or self.project_root).strip() or self.project_root
            self.include_shinzen_in_coding = bool(data.get("include_shinzen_in_coding", self.include_shinzen_in_coding))
            self.stop_on_bad_response = bool(data.get("stop_on_bad_response", self.stop_on_bad_response))
            self.require_code_block_for_injection = bool(data.get("require_code_block_for_injection", self.require_code_block_for_injection))
            self.preferred_coding_model = data.get("preferred_coding_model", self.preferred_coding_model)
            self.preferred_shinzen_model = data.get("preferred_shinzen_model", self.preferred_shinzen_model)
            self.shinzen_feedback_cooldown_sec = self._coerce_int(data.get("shinzen_feedback_cooldown_sec", self.shinzen_feedback_cooldown_sec), 5, 300, self.shinzen_feedback_cooldown_sec)
            self.shinzen_refresh_timer_sec = self._coerce_int(data.get("shinzen_refresh_timer_sec", self.shinzen_refresh_timer_sec), 10, 300, self.shinzen_refresh_timer_sec)
            self.shinzen_idle_suggestions_enabled = bool(data.get("shinzen_idle_suggestions_enabled", self.shinzen_idle_suggestions_enabled))
            self.shinzen_idle_interval_sec = self._coerce_int(data.get("shinzen_idle_interval_sec", self.shinzen_idle_interval_sec), 20, 600, self.shinzen_idle_interval_sec)
        except Exception:
            pass

    def _save_preferences(self):
        payload = {
            "username": self.username,
            "auto_run_coding": self.auto_run_coding,
            "insert_mode": self.insert_mode,
            "run_mode": self.run_mode,
            "enable_typewriter": self.enable_typewriter,
            "coding_max_tokens": self.coding_max_tokens,
            "run_timeout_sec": self.run_timeout_sec,
            "persist_session": self.persist_session,
            "restore_last_file": self.restore_last_file,
            "last_opened_file": self.current_file_path or self.last_opened_file,
            "auto_install_missing_imports": self.auto_install_missing_imports,
            "python_exec_path": self.python_exec_path,
            "project_root": self.project_root,
            "include_shinzen_in_coding": self.include_shinzen_in_coding,
            "stop_on_bad_response": self.stop_on_bad_response,
            "require_code_block_for_injection": self.require_code_block_for_injection,
            "preferred_coding_model": self.preferred_coding_model,
            "preferred_shinzen_model": self.preferred_shinzen_model,
            "shinzen_feedback_cooldown_sec": self.shinzen_feedback_cooldown_sec,
            "shinzen_refresh_timer_sec": self.shinzen_refresh_timer_sec,
            "shinzen_idle_suggestions_enabled": self.shinzen_idle_suggestions_enabled,
            "shinzen_idle_interval_sec": self.shinzen_idle_interval_sec,
        }
        try:
            self.config.data = payload
            self.config.save()
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
        win.geometry("560x660")
        win.configure(fg_color=SURFACE)
        win.resizable(True, True)
        win.minsize(560, 620)
        self._settings_window = win

        wrap = ctk.CTkScrollableFrame(win, fg_color=SURFACE, corner_radius=16)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(wrap, text="Behavior", text_color=TEXT, font=(BASE_FONT[0], 16, "bold")).pack(anchor="w", pady=(0, 8))

        auto_run_var = tk.BooleanVar(value=self.auto_run_coding)
        type_var = tk.BooleanVar(value=self.enable_typewriter)
        persist_var = tk.BooleanVar(value=self.persist_session)
        restore_var = tk.BooleanVar(value=self.restore_last_file)
        stop_bad_var = tk.BooleanVar(value=self.stop_on_bad_response)
        require_block_var = tk.BooleanVar(value=self.require_code_block_for_injection)
        idle_ideas_var = tk.BooleanVar(value=self.shinzen_idle_suggestions_enabled)
        auto_install_var = tk.BooleanVar(value=self.auto_install_missing_imports)

        ctk.CTkCheckBox(wrap, text="Auto-run code from Coding AI", variable=auto_run_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Typewriter animation in chat", variable=type_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Persist session draft", variable=persist_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Restore last opened file on launch", variable=restore_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Auto-stop nonsense coding replies", variable=stop_bad_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Require fenced code block before injection", variable=require_block_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Enable idle code ideas", variable=idle_ideas_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Auto-install missing imports before run (e.g., pygame)", variable=auto_install_var, text_color=TEXT).pack(anchor="w", pady=4)

        ctk.CTkLabel(wrap, text="Run Mode", text_color=TEXT, font=(BASE_FONT[0], 13, "bold")).pack(anchor="w", pady=(14, 4))
        run_mode_map = {
            "Temp Sandbox (isolated)": "temp",
            "Active File (save + run)": "active_file",
            "Workspace Sandbox (multi-file + assets)": "workspace",
        }
        run_mode_label = next((k for k, v in run_mode_map.items() if v == self.run_mode), "Temp Sandbox (isolated)")
        run_mode_var = tk.StringVar(value=run_mode_label)
        ctk.CTkOptionMenu(wrap, values=list(run_mode_map.keys()), variable=run_mode_var, fg_color=SURFACE_ALT, button_color=SOFT, button_hover_color=ACCENT_HOVER, text_color=TEXT).pack(anchor="w", pady=2)

        ctk.CTkLabel(wrap, text="Code Insert Mode", text_color=TEXT, font=(BASE_FONT[0], 13, "bold")).pack(anchor="w", pady=(12, 4))
        insert_map = {
            "Replace Engine Content": "replace",
            "Append to Engine Content": "append",
            "Do Not Inject (preview only)": "noop",
        }
        insert_label = next((k for k, v in insert_map.items() if v == self.insert_mode), "Replace Engine Content")
        insert_var = tk.StringVar(value=insert_label)
        ctk.CTkOptionMenu(wrap, values=list(insert_map.keys()), variable=insert_var, fg_color=SURFACE_ALT, button_color=SOFT, button_hover_color=ACCENT_HOVER, text_color=TEXT).pack(anchor="w", pady=2)


        grid = ctk.CTkFrame(wrap, fg_color=SURFACE, corner_radius=12)
        grid.pack(fill="x", pady=(14, 2))
        grid.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(grid, text="Coding max tokens", text_color=MUTED).grid(row=0, column=0, sticky="w", pady=6)
        coding_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        coding_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=6)
        coding_entry.insert(0, str(self.coding_max_tokens))

        ctk.CTkLabel(grid, text="Username", text_color=MUTED).grid(row=1, column=0, sticky="w", pady=6)
        username_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        username_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=6)
        username_entry.insert(0, str(self.username))

        ctk.CTkLabel(grid, text="Run timeout (sec)", text_color=MUTED).grid(row=2, column=0, sticky="w", pady=6)
        timeout_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        timeout_entry.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=6)
        timeout_entry.insert(0, str(self.run_timeout_sec))

        ctk.CTkLabel(grid, text="Shinzen cooldown (sec)", text_color=MUTED).grid(row=3, column=0, sticky="w", pady=6)
        shinzen_cooldown_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        shinzen_cooldown_entry.grid(row=3, column=1, sticky="ew", padx=(10, 0), pady=6)
        shinzen_cooldown_entry.insert(0, str(self.shinzen_feedback_cooldown_sec))

        ctk.CTkLabel(grid, text="Shinzen refresh timer (sec)", text_color=MUTED).grid(row=4, column=0, sticky="w", pady=6)
        shinzen_refresh_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        shinzen_refresh_entry.grid(row=4, column=1, sticky="ew", padx=(10, 0), pady=6)
        shinzen_refresh_entry.insert(0, str(self.shinzen_refresh_timer_sec))

        ctk.CTkLabel(grid, text="Idle suggestion interval (sec)", text_color=MUTED).grid(row=5, column=0, sticky="w", pady=6)
        shinzen_idle_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        shinzen_idle_entry.grid(row=5, column=1, sticky="ew", padx=(10, 0), pady=6)
        shinzen_idle_entry.insert(0, str(self.shinzen_idle_interval_sec))

        ctk.CTkLabel(grid, text="Run Python interpreter", text_color=MUTED).grid(row=6, column=0, sticky="w", pady=6)
        py_exec_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        py_exec_entry.grid(row=6, column=1, sticky="ew", padx=(10, 0), pady=6)
        py_exec_entry.insert(0, str(self.python_exec_path))

        ctk.CTkLabel(grid, text="Project root (optional)", text_color=MUTED).grid(row=7, column=0, sticky="w", pady=6)
        project_root_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        project_root_entry.grid(row=7, column=1, sticky="ew", padx=(10, 0), pady=6)
        project_root_entry.insert(0, str(self.project_root))

        btns = ctk.CTkFrame(wrap, fg_color=SURFACE, corner_radius=12)
        btns.pack(fill="x", pady=(16, 2))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=0)
        btns.grid_columnconfigure(2, weight=0)
        btns.grid_columnconfigure(3, weight=0)

        def apply_settings(close_after=False):
            self.auto_run_coding = bool(auto_run_var.get())
            self.enable_typewriter = bool(type_var.get())
            self.persist_session = bool(persist_var.get())
            self.restore_last_file = bool(restore_var.get())
            self.stop_on_bad_response = bool(stop_bad_var.get())
            self.require_code_block_for_injection = bool(require_block_var.get())
            self.shinzen_idle_suggestions_enabled = bool(idle_ideas_var.get())
            self.auto_install_missing_imports = bool(auto_install_var.get())

            self.run_mode = run_mode_map.get(run_mode_var.get(), self.run_mode)
            self.insert_mode = insert_map.get(insert_var.get(), self.insert_mode)
            self.coding_max_tokens = self._coerce_int(coding_entry.get(), 120, 4000, self.coding_max_tokens)
            self.username = username_entry.get().strip() or "Coder"
            self.run_timeout_sec = self._coerce_int(timeout_entry.get(), 5, 600, self.run_timeout_sec)
            self.shinzen_feedback_cooldown_sec = self._coerce_int(shinzen_cooldown_entry.get(), 5, 300, self.shinzen_feedback_cooldown_sec)
            self.shinzen_refresh_timer_sec = self._coerce_int(shinzen_refresh_entry.get(), 10, 300, self.shinzen_refresh_timer_sec)
            self.shinzen_idle_interval_sec = self._coerce_int(shinzen_idle_entry.get(), 20, 600, self.shinzen_idle_interval_sec)
            py_exec = py_exec_entry.get().strip()
            self.python_exec_path = py_exec if py_exec else sys.executable
            self.project_root = project_root_entry.get().strip() or self.project_root
            self._schedule_shinzen_analysis(delay=200, force=True)

            self._refresh_coding_controls()
            self._update_run_mode_badge()
            self._save_preferences()
            self._set_status_temporary("Settings saved", duration=1800)
            if close_after:
                try:
                    win.destroy()
                except Exception:
                    pass

        ctk.CTkButton(
            btns,
            text="Save",
            width=92,
            height=40,
            corner_radius=14,
            fg_color="#EAD9CB",
            hover_color=SOFT,
            text_color=TEXT,
            command=lambda: apply_settings(False),
        ).grid(row=0, column=1, padx=(0, 8), pady=2, sticky="e")

        ctk.CTkButton(
            btns,
            text="Save & Close",
            width=118,
            height=40,
            corner_radius=14,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="white",
            command=lambda: apply_settings(True),
        ).grid(row=0, column=2, padx=(0, 8), pady=2, sticky="e")

        ctk.CTkButton(
            btns,
            text="Cancel",
            width=92,
            height=40,
            corner_radius=14,
            fg_color=SURFACE_ALT,
            hover_color=SOFT,
            text_color=TEXT,
            command=win.destroy,
        ).grid(row=0, column=3, pady=2, sticky="e")

    def _open_help(self):
        if self._help_window is not None and self._help_window.winfo_exists():
            self._help_window.lift()
            self._help_window.focus_force()
            return

        win = ctk.CTkToplevel(self)
        win.title("Code9 Help")
        win.geometry("760x620")
        win.configure(fg_color=SURFACE)
        self._help_window = win

        wrap = ctk.CTkFrame(win, fg_color=SURFACE, corner_radius=0)
        wrap.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            wrap,
            text="How Code9 Works",
            text_color=TEXT,
            font=(BASE_FONT[0], 20, "bold"),
        ).pack(anchor="w", pady=(0, 10))

        help_text = (
            "AI Assistants\n"
            "- Coding AI: generates runnable Python, fixes bugs, and can auto-inject code into Engine.\n\n"
            "- Engine injection guard: malformed Python from AI is blocked before editor updates.\n\n"
            "Top Buttons\n"
            "- Open: open a local file into the Engine editor.\n"
            "- Project: choose a project root folder for workspace sandbox runs.\n"
            "- Save / Save As: save current Engine content.\n"
            "- Run: execute Engine code in temp sandbox, active file mode, or workspace sandbox mode.\n"
            "- Stop: stop the running Engine process.\n"
            "- AI Fill: rewrite selected code (or full editor) from a natural-language instruction.\n"
            "- Shell: export a launcher script for the current Engine code.\n"
            "- Ideas: posts project upgrade ideas in the Coding AI chat.\n"
            "- Settings: controls AI behavior, model choices, and Shinzen timing.\n"
            "- Help: this guide.\n"
            "- Clear: clears the chat and restores the welcome prompt.\n\n"
            "Settings Guide\n"
            "- Auto-run code from Coding AI: when ON, code gets injected and can run automatically.\n"
            "- Typewriter animation in chat: cosmetic typing effect in chat responses.\n"
            "- Persist session draft: auto-saves unsaved editor text to recover on restart.\n"
            "- Restore last opened file on launch: reopens your previous file path.\n"
            "- Auto-stop nonsense coding replies: cancels repetitive/low-quality coding output.\n"
            "- Require fenced code block before injection: safer code insertion from coding replies.\n"
            "- Enable idle code ideas: Shinzen gives project ideas while you are idle.\n"
            "- Auto-install missing imports: installs unresolved packages (like pygame) before run.\n"
            "- Run Mode: Temp Sandbox isolates runs; Active File runs the saved file directly; Workspace Sandbox copies your project for multi-file/assets runs.\n"
            "- Code Insert Mode: Replace swaps whole editor; Append adds generated code at end; Preview mode leaves editor unchanged.\n"
            "- Coding Model: primary model for coding chat and AI Fill.\n"
            "- Shinzen Comment Model: lightweight model for Shinzen bubble feedback.\n"
            "- Coding max tokens: max length for coding responses.\n"
            "- Run timeout (sec): maximum runtime before process is stopped.\n"
            "- Run Python interpreter: choose the Python executable used by Run.\n"
            "- Project root: base folder used by workspace sandbox runs.\n"
            "- Shinzen cooldown (sec): minimum time between Shinzen comments.\n"
            "- Shinzen refresh timer (sec): periodic refresh cadence while actively coding.\n"
            "- Idle suggestion interval (sec): idea cadence while idle.\n\n"
            "Recommended Settings\n"
            "- Safe default profile: Auto-run OFF, Require code block ON, Auto-stop nonsense ON, Run Mode Temp Sandbox.\n"
            "- Fast iteration profile: Auto-run ON, Insert Mode Replace, Run timeout 60, Coding max tokens 700-1000.\n"
            "- Shinzen profile (balanced): cooldown 20, refresh 30, idle ideas ON, idle interval 60.\n\n"
            "Coding Card Controls\n"
            "- Auto Run: run generated coding output immediately after injection.\n"
            "- Insert mode: replace, append, or preview-only (no injection).\n"
            "- Stop: cancels an in-progress assistant response.\n"
            "- /Runtime /Engine /Errors /Shinzen: attach context shortcuts for coding prompts.\n\n"
            "Shinzen Mascot\n"
            "- Main Shinzen uses the speech bubble as the status indicator.\n"
            "- Bubble appears for new statuses/comments and hides when idle.\n"
            "- Peeks while you type, uses slower running animation during code execution.\n\n"
            "Coding Models (Public)\n"
            "- Default fallback order: Qwen2.5-Coder-7B, DeepSeek-Coder-V2-Lite, StarCoder2.\n"
            "- Install runtime: `pip install -U mlx-lm`\n"
            "- Download by running once in app, or prefetch via: `python -m mlx_lm.generate --model <model-repo> --prompt \"ready\" --max-tokens 1`\n"
            "- Set preferred model in Settings -> Coding Model."
        )

        panel = tk.Text(
            wrap,
            bg="#FFFCF8",
            fg=TEXT,
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            wrap="word",
            padx=14,
            pady=12,
            font=(BASE_FONT[0], 12),
        )
        panel.pack(fill="both", expand=True)
        panel.insert("1.0", help_text)
        panel.config(state="disabled")

        foot = ctk.CTkFrame(wrap, fg_color=SURFACE, corner_radius=0)
        foot.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(
            foot,
            text="Close",
            width=92,
            corner_radius=14,
            fg_color=SURFACE_ALT,
            hover_color=SOFT,
            text_color=TEXT,
            command=win.destroy,
        ).pack(side="right")
    def _lock_ui(self):
        self._ui_busy = True
        self.after(120, self._unlock_ui)

    def _unlock_ui(self):
        self._ui_busy = False

    # -------------------- CHAT HELPERS --------------------
    def _setup_chat_tags(self, widget):
        try:
            widget.tag_config("role", foreground=MUTED, font=(BASE_FONT[0], 10, "bold"), spacing1=6)
            widget.tag_config("user", foreground=TEXT, background="#FCEEE1", lmargin1=8, lmargin2=8, spacing1=2, spacing3=6)
            widget.tag_config("assistant", foreground=TEXT, background="#FFF9F3", lmargin1=8, lmargin2=8, spacing1=2, spacing3=8)
            widget.tag_config(
                "welcome",
                foreground="#AA8F7B" ,
                justify="center",
                font=(BASE_FONT[0], 18, "bold"),
                spacing3=8,
            )
        except Exception:
            pass

    def _next_welcome_message(self):
        try:
            if not self._welcome_pool:
                self._welcome_pool = random.sample(WELCOME_VARIANTS, k=len(WELCOME_VARIANTS))
            template = self._welcome_pool.pop()

            # Dynamic time check
            hour = datetime.now().hour
            if hour < 12:
                current_greet = "Good morning"
            elif hour < 18:
                current_greet = "Good afternoon"
            else:
                current_greet = "Good evening"

            # We use 'Username' (Capital U) to match your WELCOME_VARIANTS list
            return template.format(
                Username=getattr(self, "username", "Coder"),
                timedGreeting=current_greet
            )
        except Exception as e:
            print(f"Greeting Error: {e}")
            return "Welcome back!"

    def _set_chat_welcome(self, widget, kind="coding"):
        if not widget: return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        
        # SAFE CHECK: Determine if we are dealing with a CTk wrapper or a raw Text widget
        target = widget._textbox if hasattr(widget, "_textbox") else widget
        
        # Now we can safely configure the font and center the text
        target.tag_config("welcome", justify="center", font=(BASE_FONT[0], 26, "bold"), foreground="#352922")
        
        msg = self._next_welcome_message()
        
        # This adds the 5 empty lines to push the text down
        widget.insert("end", "\n\n\n\n" + msg, "welcome")
        widget.configure(state="disabled")
        self._chat_welcome_state[widget] = True

    def _clear_chat_welcome_if_needed(self, widget):
        try:
            if self._chat_welcome_state.get(widget):
                widget.config(state="normal")
                widget.delete("1.0", "end")
                widget.config(state="disabled")
                self._chat_welcome_state[widget] = False
        except Exception:
            pass

    def _append_user(self, widget, text):
        try:
            self._clear_chat_welcome_if_needed(widget)
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
        self._clear_chat_welcome_if_needed(widget)
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
            self._chat_welcome_state[widget] = False
            kind = self._chat_widget_kind.get(widget, "general")
            self._set_chat_welcome(widget, kind=kind)
        except Exception:
            pass
    
    def request_shinzen_ideas(self):
        # We explicitly set the text and pass the intent="idea" flag
        idea_prompt = "Give me some high-level architectural ideas or project upgrades."
        self.coding_card["var"].set(idea_prompt)
        self.ask_coding_ai(intent="idea")

    def _copy_from_widget(self, widget):
        """Copy selection if present, else copy the entire widget content to clipboard."""
        try:
            if self._chat_welcome_state.get(widget):
                self._set_status_temporary("Nothing to copy", duration=1400)
                return
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

    def _configure_mlx_runtime(self):
        """Tune MLX Metal runtime limits for steadier throughput when available."""
        if not (MLX_AVAILABLE and MLX_CORE_AVAILABLE and mx is not None):
            return
        try:
            if hasattr(mx, "metal") and mx.metal.is_available():
                if hasattr(mx, "device_info"):
                    info = mx.device_info()
                elif hasattr(mx.metal, "device_info"):
                    info = mx.metal.device_info()
                else:
                    info = {}
                rec = int(info.get("max_recommended_working_set_size", 0) or 0)
                if rec > 0 and hasattr(mx, "set_wired_limit"):
                    mx.set_wired_limit(int(rec * 0.92))
        except Exception:
            pass

    def _load_models_serial(self):
        """Load coding then Shinzen model sequentially to avoid Metal command-buffer races."""
        try:
            self._load_model()
        except Exception:
            pass
        try:
            self._load_phi_model()
        except Exception:
            pass

    def _load_model(self):
        try:
            with self._mlx_load_lock:
                self.after(0, lambda: self._set_presence_message(f"Loading Coding AI on {DEVICE}...", mood="thinking"))
                sig = inspect.signature(load)
                kwargs = {}
                if "lazy" in sig.parameters:
                    kwargs["lazy"] = True
                if "device" in sig.parameters:
                    kwargs["device"] = DEVICE
                candidates = []
                if self.preferred_coding_model:
                    candidates.append(self.preferred_coding_model)
                for name in CODING_MODEL_CANDIDATES:
                    if name not in candidates:
                        candidates.append(name)

                model, tokenizer, picked, errors = self.model_wrapper.load_first_available(candidates, base_kwargs=kwargs)
                if model is None or tokenizer is None:
                    attempts = "; ".join([f"{k}: {v}" for k, v in errors.items()])
                    raise RuntimeError("No coding model could be loaded. Attempts: " + attempts)

                self.model = model
                self.tokenizer = tokenizer
                self.loaded_coding_model_name = picked or ""
                self.model_ready = True
                self.model_failed = False
                self._configure_mlx_runtime()

                short_name = (self.loaded_coding_model_name or "coding model").split("/")[-1]
                self.after(0, lambda: self._set_presence_message(f"Coding AI loaded: {short_name}. Warming up...", mood="thinking"))
                try:
                    self._safe_generate("Reply with exactly: ready", max_tokens=6, temperature=0.0)
                except Exception:
                    pass
                self.after(0, self._refresh_status)
        except Exception as e:
            self.model_ready = False
            self.model_failed = True
            self.after(0, self._refresh_status)
            print("Coding model load error:", e)

    def _load_phi_model(self):
        """Load the fast Phi-3.5-mini model for Shinzen bubble comments."""
        try:
            with self._mlx_load_lock:
                sig = inspect.signature(load)
                kwargs = {}
                if "lazy" in sig.parameters:
                    kwargs["lazy"] = True
                if "device" in sig.parameters:
                    kwargs["device"] = DEVICE
                candidates = []
                if self.preferred_shinzen_model:
                    candidates.append(self.preferred_shinzen_model)
                for name in SHINZEN_MODEL_CANDIDATES:
                    if name not in candidates:
                        candidates.append(name)
                phi_model, phi_tokenizer, picked, _errors = self.model_wrapper.load_first_available(candidates, base_kwargs=kwargs)
                if phi_model is None or phi_tokenizer is None:
                    raise RuntimeError("No Shinzen comment model could be loaded.")
                self.phi_model = phi_model
                self.phi_tokenizer = phi_tokenizer
                self.loaded_shinzen_model_name = picked or ""
                self.phi_ready = True
                print("Shinzen model ready:", self.loaded_shinzen_model_name)
        except Exception as e:
            self.phi_ready = False
            print("Phi model load error:", e)

    def _sanitize_response(self, text, mode=None):
        try:
            return ChatSanitizer.sanitize_response(text or "", mode=mode)
        except Exception:
            return text

    def _safe_generate_mlx(self, prompt, max_tokens, temperature=None):
        call_kwargs = {"prompt": prompt, "max_tokens": max_tokens}
        temp = self.safe_defaults.get("temperature", 0.0) if temperature is None else temperature

        if make_sampler is not None:
            call_kwargs["sampler"] = make_sampler(
                temp=float(temp),
                top_p=float(self.safe_defaults.get("top_p", 0.0)),
                top_k=int(self.safe_defaults.get("top_k", 0)),
            )

        if make_logits_processors is not None:
            rep = float(self.safe_defaults.get("repetition_penalty", 1.0))
            if rep > 1.0:
                logits_processors = make_logits_processors(
                    repetition_penalty=rep,
                    repetition_context_size=24,
                )
                if logits_processors:
                    call_kwargs["logits_processors"] = logits_processors

        for key in ("prefill_step_size", "max_kv_size", "kv_bits", "kv_group_size", "quantized_kv_start"):
            value = self.safe_defaults.get(key)
            if value is not None:
                call_kwargs[key] = value

        return generate(self.model, self.tokenizer, **call_kwargs)

    def _safe_generate(self, prompt, max_tokens, temperature=None):
        """Call generation with backend-aware defaults and robust fallbacks."""
        try:
            if getattr(generate, "__module__", "").startswith("mlx_lm"):
                return self._safe_generate_mlx(prompt, max_tokens, temperature=temperature)

            sig = inspect.signature(generate)
            params = sig.parameters
            accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            call_kwargs = {}

            # Prompt/input naming
            if "prompt" in params or accepts_kwargs:
                call_kwargs["prompt"] = prompt
            elif "inputs" in params:
                call_kwargs["inputs"] = prompt
            else:
                call_kwargs["prompt"] = prompt

            # Max tokens naming
            if "max_tokens" in params or accepts_kwargs:
                call_kwargs["max_tokens"] = max_tokens
            elif "max_new_tokens" in params:
                call_kwargs["max_new_tokens"] = max_tokens
            elif "max_output_tokens" in params:
                call_kwargs["max_output_tokens"] = max_tokens

            # Decoding defaults (favor deterministic/stable outputs)
            # Allow an override temperature to be passed explicitly
            if temperature is None:
                if "temperature" in params or accepts_kwargs:
                    call_kwargs["temperature"] = 0.0
            else:
                if "temperature" in params or accepts_kwargs:
                    call_kwargs["temperature"] = temperature

            if "top_p" in params or accepts_kwargs:
                call_kwargs["top_p"] = 0.2
            if "repetition_penalty" in params or accepts_kwargs:
                call_kwargs["repetition_penalty"] = 1.2

            # Add stop sequences if supported to reduce run-on replies
            if "stop" in params or accepts_kwargs:
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
            if (not MLX_AVAILABLE) or (not self.model_ready) or (not getattr(self, "enable_verifier", False)):
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

    def _is_nonsense_response(self, text, mode="coding"):
        try:
            return ChatSanitizer.is_nonsense(text or "", mode=mode)
        except Exception:
            return False

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
                if getattr(self, "enable_verifier", False):
                    note = self._run_verifier(raw, mode)
            except Exception:
                note = ""

            cleaned = self._sanitize_response((raw or "") + (note or ""), mode=mode)

            if mode == "coding" and self.stop_on_bad_response and self._is_nonsense_response(cleaned, mode="coding"):
                retry_prompt = (
                    prompt
                    + "\n\nSTRICT OUTPUT FIX:\n"
                    "- No repeated lines.\n"
                    "- Reply with one fenced ```python block only.\n"
                    "- No role labels, no repeated commentary.\n"
                )
                retry_raw = self._safe_generate(retry_prompt, max_tokens=min(max_tokens, 900), temperature=0.0)
                retry_clean = self._sanitize_response(retry_raw or "", mode=mode)
                if self._is_nonsense_response(retry_clean, mode="coding"):
                    return (
                        "```python\n"
                        "# Coding AI stopped: response looked invalid or repetitive.\n"
                        "print('Coding AI stopped due to low-quality output. Please retry.')\n"
                        "```"
                    )
                return retry_clean

            return cleaned
        except Exception as e:
            if mode == "coding":
                return f"```python\n# Generation error\nprint({repr(str(e))})\n```"
            return f"Generation error: {e}"

    def _build_coding_repair_prompt(self, query, raw_response, issue):
        issue_text = issue or "Output format did not pass validation."
        return (
            "You are repairing a Python coding assistant response.\n"
            "Return one fenced ```python block only.\n"
            "Rules:\n"
            "- The code must parse in Python.\n"
            "- Keep behavior aligned to the request.\n"
            "- No role labels and no extra markdown.\n\n"
            f"User request:\n{query}\n\n"
            f"Validation issue:\n{issue_text}\n\n"
            "Original response:\n"
            f"{raw_response}\n\n"
            "Repaired response:"
        )

    def _normalize_coding_response(self, text):
        try:
            return ChatSanitizer.normalize_coding_reply(
                text or "",
                require_code_block=bool(self.require_code_block_for_injection),
            )
        except Exception:
            return {
                "response_text": (text or "").strip(),
                "code": "",
                "syntax_ok": False,
                "had_code_block": False,
                "needs_retry": True,
                "issue": "Could not normalize coding output.",
                "quality_score": 0,
            }

    # -------------------- ASK HANDLERS --------------------
    def _on_coding_ask_clicked(self):
        self.ask_coding_ai()

    def ask_coding_ai(self, event=None, intent=None):
        var = self.coding_card["var"]
        val = var.get()
        prefix = getattr(self, "_coding_attach_prefix", "")

        # 1. Strip the visual attachment prefix if present
        if prefix and val.startswith(prefix):
            raw_query = val[len(prefix):].strip()
        else:
            raw_query = val.strip()

        # 2. Check for Intent commands (so the AI knows if it's a question or code)
        if not intent:
            intent = "code" # Default to writing code
            lower_q = raw_query.lower()
            if lower_q.startswith("/ask ") or lower_q.startswith("/chat ") or lower_q in ("/ask", "/chat"):
                intent = "chat"
                raw_query = re.sub(r"^/(ask|chat)\s*", "", raw_query, flags=re.IGNORECASE)
            elif lower_q.startswith("/idea"):
                intent = "idea"
                raw_query = re.sub(r"^/idea\s*", "", raw_query, flags=re.IGNORECASE)
                if not raw_query:
                    raw_query = "Give me some high-level architectural ideas or project upgrades."

        if not raw_query and intent != "idea":
            return

        # 3. Process Context Attachments
        try:
            tags = [t.strip('/') for t in re.findall(r"/(\w+)", raw_query)]
            if tags:
                for t in tags:
                    tl = t.lower()
                    if tl.startswith("err"): self._attach_errors_to_coding()
                    elif tl.startswith("run") or tl == "runtime": self._attach_runtime_output_to_coding()
                    elif tl.startswith("eng"): self._attach_editor_to_coding()
                    elif tl.startswith("gen"): self._attach_general_chat_to_coding()
                    elif tl.startswith("shin"): self._attach_shinzen_to_coding()
                # Remove attachment tags, but KEEP regular text
                raw_query = re.sub(r"/(err|run|runtime|eng|gen|shin)\w*", "", raw_query, flags=re.IGNORECASE).strip()
            
            query = raw_query.strip()
        except Exception:
            query = raw_query.strip()

        if not query and intent != "idea":
            return

        try:
            self.abort_tokens['coding'] = self.abort_tokens.get('coding', 0) + 1
            req_id = self.abort_tokens['coding']
        except Exception:
            req_id = None

        self._append_user(self.coding_card["text"], query)
        
        if prefix:
            var.set(prefix)
        else:
            var.set("")
            
        if self.model_ready:
            self.start_loader()
            
        self._set_presence_message("Thinking..." if intent in ["chat", "idea"] else "Coding AI is crafting code...", mood="thinking")

        try:
            self._pause_shinzen()
        except Exception:
            pass

        threading.Thread(target=self._coding_worker, args=(query, req_id, intent), daemon=True).start()

    def _coding_worker(self, query, reqid=None, intent="code"):
    try:
        self.after0(self.lockui)
        editor = getattr(self, "editor", None)
        if editor is None:
            return

        try:
            editorsnapshot = editor.get("1.0", "end-1c")
        except Exception:
            editorsnapshot = ""

        attachmentstext = ""
        try:
            attachments = getattr(self, "codingattachments", {}) or {}
            if attachments:
                attachmentstext = "Attached resources:\n" + "\n\n".join(
                    str(v) for v in attachments.values() if v
                )
        except Exception:
            attachmentstext = ""

        prompt = self.buildcodingprompt(query, editorsnapshot, attachmentstext, intent)
        response = self.generatetext(prompt, self.codingmaxtokens, mode=intent)

        if reqid is not None and reqid != getattr(self, "aborttokens", {}).get("coding", reqid):
            return

        if not response:
            return

        normalized = self.normalizecodingresponses(response)
        if normalized.get("needsretry"):
            repair_prompt = self.buildcodingrepairprompt(query, response, normalized.get("issue"))
            repaired = self.generatetext(repair_prompt, self.codingmaxtokens, mode="coding")
            normalized = self.normalizecodingresponses(repaired)

        if normalized.get("code"):
            self.after0(self.injectcodeintoengine, normalized["code"])
        else:
            self.after0(self.appendassistant, self.codingcardtext, response, label="Code AI")
    except Exception:
        self.after0(self.appendoutput, traceback.format_exc())
    finally:
        try:
            self.after0(self.refreshstatus)
        except Exception:
            pass

    def _extract_code_blocks(self, text):
        try:
            return ChatSanitizer.extract_code_blocks(text or "")
        except Exception:
            return []

    def _looks_like_python(self, text):
        if "\n" not in text:
            return False
        markers = ["def ", "import ", "print(", "if __name__", "class ", "return ", "for ", "while "]
        score = sum(1 for m in markers if m in text)
        return score >= 2

    def _inject_code_into_engine(self, code):
        normalized = code if code.endswith("\n") else (code + "\n")
        try:
            compile(normalized, "<ai_injection>", "exec")
        except Exception as e:
            self._set_status_temporary(f"Injection skipped: invalid Python ({e})", duration=2600)
            self._set_presence_message("I blocked malformed code before it reached Engine.", mood="alert", duration=2500)
            return False

        if self.insert_mode == "noop":
            self._set_status_temporary("Preview only mode: AI code was not injected", duration=2200)
            self._set_presence_message("Preview mode is on. Your engine code is unchanged.", mood="listening", duration=2200)
            return False

        before = self.editor.get("1.0", "end-1c")
        self._last_ai_injection = before

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
        self._schedule_shinzen_analysis(delay=140, force=True)

        if self.auto_run_coding:
            self.after(0, self._open_runtime_terminal)
            code_to_run = self.editor.get("1.0", "end-1c")
            threading.Thread(target=self._run_code, args=(code_to_run, False), daemon=True).start()
            self._set_status_temporary("Injected code into engine and started run", duration=2200)
        else:
            self._set_status_temporary("Injected code into engine", duration=1800)
        return True

    # -------------------- RUN / ENGINE --------------------
    def _resolve_python_exec(self):
        candidate = (self.python_exec_path or "").strip()
        if candidate:
            if os.path.isabs(candidate) and os.path.exists(candidate):
                return candidate
            found = shutil.which(candidate)
            if found:
                return found
        return sys.executable

    def _resolve_project_root(self):
        if self.project_root and os.path.isdir(self.project_root):
            return os.path.abspath(self.project_root)
        if self.current_file_path:
            return os.path.abspath(os.path.dirname(self.current_file_path) or os.getcwd())
        if self.last_opened_file and os.path.exists(self.last_opened_file):
            return os.path.abspath(os.path.dirname(self.last_opened_file) or os.getcwd())
        return os.getcwd()

    def _workspace_copy_ignore(self, _src, names):
        ignored = {
            ".git",
            ".hg",
            ".svn",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "venv",
            "node_modules",
        }
        out = []
        for name in names:
            if name in ignored:
                out.append(name)
            elif name.endswith(".pyc") or name.endswith(".pyo"):
                out.append(name)
        return out

    def _build_workspace_sandbox(self, code_to_write):
        temp_ctx = tempfile.TemporaryDirectory()
        sandbox_root = temp_ctx.name
        src_root = self._resolve_project_root()
        copied_root = os.path.join(sandbox_root, "workspace")

        if os.path.isdir(src_root):
            try:
                shutil.copytree(
                    src_root,
                    copied_root,
                    dirs_exist_ok=True,
                    ignore=self._workspace_copy_ignore,
                )
            except Exception:
                copied_root = sandbox_root
        else:
            copied_root = sandbox_root

        run_name = "snippet.py"
        if self.current_file_path:
            run_name = os.path.basename(self.current_file_path) or run_name

        run_path = os.path.join(copied_root, run_name)
        if self.current_file_path and os.path.isdir(src_root):
            try:
                rel = os.path.relpath(self.current_file_path, src_root)
                if rel and not rel.startswith(".."):
                    run_path = os.path.join(copied_root, rel)
            except Exception:
                pass

        os.makedirs(os.path.dirname(run_path), exist_ok=True)
        with open(run_path, "w", encoding="utf-8") as f:
            f.write(code_to_write)

        run_cwd = os.path.dirname(run_path) or copied_root
        return temp_ctx, run_path, run_cwd, copied_root

    def _collect_top_level_imports(self, code):
        names = set()
        try:
            tree = ast.parse(code or "")
        except Exception:
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = (alias.name or "").split(".")[0].strip()
                    if root:
                        names.add(root)
            elif isinstance(node, ast.ImportFrom):
                if getattr(node, "level", 0):
                    continue
                module = (node.module or "").split(".")[0].strip()
                if module:
                    names.add(module)
        return sorted(names)

    def _is_local_module(self, module_name, project_root):
        if not module_name or not project_root:
            return False
        try:
            candidate_file = os.path.join(project_root, f"{module_name}.py")
            candidate_dir = os.path.join(project_root, module_name)
            candidate_pkg = os.path.join(project_root, module_name, "__init__.py")
            return os.path.exists(candidate_file) or os.path.exists(candidate_pkg) or os.path.isdir(candidate_dir)
        except Exception:
            return False

    def _find_missing_modules(self, imports, project_root, python_exec=None):
        stdlib = getattr(sys, "stdlib_module_names", set())
        candidates = []
        for name in imports:
            if not name:
                continue
            if name in stdlib or name in sys.builtin_module_names:
                continue
            if self._is_local_module(name, project_root):
                continue
            candidates.append(name)

        if not candidates:
            return []

        if python_exec and os.path.abspath(python_exec) != os.path.abspath(sys.executable):
            try:
                probe_cmd = [
                    python_exec,
                    "-c",
                    "import importlib.util,sys;mods=sys.argv[1:];missing=[m for m in mods if importlib.util.find_spec(m) is None];print('\\n'.join(missing))",
                    *candidates,
                ]
                res = subprocess.run(
                    probe_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15,
                )
                if res.returncode == 0:
                    return sorted({ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()})
            except Exception:
                pass

        missing = []
        for name in candidates:
            try:
                spec = importlib.util.find_spec(name)
            except Exception:
                spec = None
            if spec is None:
                missing.append(name)
        return sorted(set(missing))

    def _install_missing_modules(self, python_exec, modules):
        if not modules:
            return True
        cmd = [python_exec, "-m", "pip", "install", *modules]
        self.after(0, lambda: self._append_output(f"[Dependency install]\n$ {' '.join(cmd)}\n"))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                safe_line = self._sanitize_text(line)
                self.after(0, lambda ln=safe_line: self._append_output("[pip] " + ln))
            rc = proc.wait()
            self.after(0, lambda: self._append_output(f"[Dependency install exited with code {rc}]\n\n"))
            return rc == 0
        except Exception as e:
            self.after(0, lambda err=str(e): self._append_output(f"[Dependency install failed] {err}\n\n"))
            return False

    def _run_code(self, code, manage_loader=False):
        code_to_write = code if code.endswith("\n") else code + "\n"

        try:
            compile(code_to_write, "<engine>", "exec")
        except Exception as e:
            self.after(0, self._clear_output_panel)
            self.after(0, lambda: self._append_output(f"Syntax error:\n{e}\n"))
            self.after(0, lambda: self._set_presence_message("Syntax error found before run.", mood="alert", duration=2400))
            self.after(0, lambda: self._schedule_shinzen_analysis(delay=80, force=True))
            if manage_loader:
                self.after(0, self.stop_loader)
            return

        temp_ctx = None
        run_path = None
        run_cwd = None
        project_context_root = None

        if self.run_mode == "active_file" and self.current_file_path:
            try:
                run_path = self.current_file_path
                run_cwd = os.path.dirname(run_path) or os.getcwd()
                with open(run_path, "w", encoding="utf-8") as f:
                    f.write(code_to_write)
                project_context_root = run_cwd
                self.after(0, self._mark_editor_saved)
            except Exception as e:
                self.after(0, lambda err=str(e): self._append_output(f"Could not save active file, falling back to temp run: {err}\n"))
                run_path = None
                run_cwd = None

        if run_path is None and self.run_mode == "workspace":
            try:
                temp_ctx, run_path, run_cwd, project_context_root = self._build_workspace_sandbox(code_to_write)
            except Exception as e:
                self.after(0, lambda err=str(e): self._append_output(f"Workspace sandbox setup failed, falling back to temp run: {err}\n"))
                run_path = None
                run_cwd = None
                if temp_ctx is not None:
                    try:
                        temp_ctx.cleanup()
                    except Exception:
                        pass
                temp_ctx = None

        if run_path is None:
            temp_ctx = tempfile.TemporaryDirectory()
            run_cwd = temp_ctx.name
            run_path = os.path.join(temp_ctx.name, "snippet.py")
            with open(run_path, "w", encoding="utf-8") as f:
                f.write(code_to_write)
            project_context_root = run_cwd

        python_exec = self._resolve_python_exec()
        imports = self._collect_top_level_imports(code_to_write)
        missing = self._find_missing_modules(imports, project_context_root or run_cwd, python_exec=python_exec)

        self.after(0, self._open_runtime_terminal)
        self.after(0, self._clear_output_panel)

        if missing:
            if self.auto_install_missing_imports:
                ok = self._install_missing_modules(python_exec, missing)
                if not ok:
                    self.after(0, lambda mods=", ".join(missing): self._append_output(f"Warning: some imports may still be missing: {mods}\n"))
            else:
                pretty = ", ".join(missing)
                pip_cmd = f"{python_exec} -m pip install {pretty}"
                self.after(0, lambda p=pretty, pcmd=pip_cmd: self._append_output(
                    f"Missing imports detected: {p}\nAuto-install is disabled. Install with:\n$ {pcmd}\n\n"
                ))

        cmd = [python_exec, "-u", run_path]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

        python_paths = [run_cwd, project_context_root]
        existing_py_path = env.get("PYTHONPATH", "")
        if existing_py_path:
            python_paths.append(existing_py_path)
        env["PYTHONPATH"] = os.pathsep.join([p for p in python_paths if p])

        self.after(0, lambda: self._append_output(f"[Run started {time.strftime('%H:%M:%S')}]\n$ {' '.join(cmd)}\n\n"))
        self.after(0, lambda: self._set_presence_message("Running engine code...", mood="running"))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
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
            if rc == 0:
                self.after(0, lambda: self._set_presence_message("Run finished cleanly.", mood="happy", duration=1800))
            else:
                self.after(0, lambda: self._set_presence_message("Run finished with errors.", mood="concern", duration=2200))
            self.after(0, lambda: self._schedule_shinzen_analysis(delay=120, force=True))
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
            if getattr(self, "output_text", None) is None:
                return
            self.output_text.insert("end", text)
            self.output_text.see("end")
        except Exception:
            pass

    def _clear_output_panel(self):
        try:
            if getattr(self, "output_text", None) is not None:
                self.output_text.delete("1.0", "end")
        except Exception:
            pass

    def _on_terminal_input(self, event):
        try:
            if getattr(self, "terminal_input", None) is None:
                return
            user_input = self.terminal_input.get()
            if user_input.strip():
                self._append_output(f"$ {user_input}\n")
                self.terminal_input.delete(0, "end")
                self._set_presence_message("Sent input to the running process.", mood="listening", duration=1600)
                if self.current_proc and self.current_proc.poll() is None:
                    try:
                        self.current_proc.stdin.write(user_input + "\n")
                        self.current_proc.stdin.flush()
                    except Exception:
                        pass
        except Exception:
            pass

    def _open_runtime_terminal(self):
        # Create or focus a non-modal runtime terminal popup and wire input/output
        try:
            if getattr(self, "_runtime_win", None) is not None and self._runtime_win.winfo_exists():
                try:
                    self._runtime_win.lift()
                    self._runtime_win.focus_force()
                    if getattr(self, "_runtime_text", None) is not None:
                        self.output_text = self._runtime_text
                    if getattr(self, "_runtime_entry", None) is not None:
                        self.terminal_input = self._runtime_entry
                    return
                except Exception:
                    pass

            win = ctk.CTkToplevel(self)
            win.title("Runtime Terminal")
            win.geometry("780x420")
            win.configure(fg_color=OUTPUT_BG)
            win.resizable(True, True)
            self._runtime_win = win

            frame = ctk.CTkFrame(win, fg_color=OUTPUT_BG, corner_radius=16, border_width=1, border_color=BORDER)
            frame.pack(fill="both", expand=True, padx=8, pady=8)

            text = tk.Text(
                frame,
                font=(MONO_FONT[0], 11),
                bg=OUTPUT_BG,
                fg=TEXT,
                insertbackground=TEXT,
                bd=0,
                relief="flat",
                highlightthickness=0,
                wrap="word",
                padx=12,
                pady=10,
                state="normal",
            )
            text.pack(fill="both", expand=True, padx=8, pady=(8, 4))

            input_frame = ctk.CTkFrame(frame, fg_color=OUTPUT_BG, corner_radius=12)
            input_frame.pack(fill="x", pady=(6, 6), padx=8)

            prompt_label = ctk.CTkLabel(
                input_frame,
                text="$ ",
                font=(MONO_FONT[0], 11),
                text_color=ACCENT,
                fg_color=OUTPUT_BG,
            )
            prompt_label.pack(side="left", padx=(6, 4))

            entry = ctk.CTkEntry(
                input_frame,
                font=(MONO_FONT[0], 11),
                fg_color="#FFF7F0",
                border_width=0,
                corner_radius=12,
                text_color=TEXT,
            )
            entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
            entry.bind("<Return>", self._on_terminal_input)

            # Keep references so other methods can write to them
            self._runtime_text = text
            self._runtime_entry = entry
            self.output_text = self._runtime_text
            self.terminal_input = self._runtime_entry

            def on_close():
                try:
                    win.destroy()
                except Exception:
                    pass
                self._runtime_win = None
                self._runtime_text = None
                self._runtime_entry = None
                # fallback to inline widgets so attachment actions still work
                self.output_text = getattr(self, "inline_output_text", self.output_text)
                self.terminal_input = getattr(self, "inline_terminal_input", self.terminal_input)

            win.protocol("WM_DELETE_WINDOW", on_close)
            return
        except Exception:
            return

    def _kill_current_proc(self):
        proc = getattr(self, "current_proc", None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # -------------------- Shinzen analysis --------------------
    def _schedule_shinzen_analysis(self, delay=800, force=False, idle_hint=False):
        try:
            # do not schedule while paused
            if getattr(self, '_shinzen_paused', False):
                return
            if hasattr(self, "_shinzen_job") and self._shinzen_job is not None:
                try:
                    self.after_cancel(self._shinzen_job)
                except Exception:
                    pass
            self._shinzen_force_refresh = bool(force)
            self._shinzen_idle_hint = bool(idle_hint)
            self._shinzen_job = self.after(delay, self._run_shinzen_analysis)
        except Exception:
            pass

    def _start_shinzen_loop(self):
        try:
            if self._shinzen_periodic_job is not None:
                try:
                    self.after_cancel(self._shinzen_periodic_job)
                except Exception:
                    pass
                self._shinzen_periodic_job = None
            self._shinzen_periodic_job = self.after(1000, self._shinzen_periodic_tick)
        except Exception:
            pass

    def _shinzen_periodic_tick(self):
        try:
            self._shinzen_periodic_job = None
            if getattr(self, "_shinzen_paused", False):
                self._shinzen_periodic_job = self.after(1000, self._shinzen_periodic_tick)
                return
            now = time.time()
            is_idle = self._shinzen_is_idle()
            since_comment = now - float(getattr(self, "_last_shinzen_comment_ts", 0.0) or 0.0)
            if is_idle and self.shinzen_idle_suggestions_enabled:
                if (now - self._last_idle_suggestion_ts) >= max(20, int(self.shinzen_idle_interval_sec)):
                    self._last_idle_suggestion_ts = now
                    self._schedule_shinzen_analysis(delay=10, force=True, idle_hint=True)
            elif (not is_idle) and since_comment >= max(10, int(self.shinzen_refresh_timer_sec)):
                self._schedule_shinzen_analysis(delay=10, force=False, idle_hint=False)
        except Exception:
            pass
        finally:
            try:
                if self._shinzen_periodic_job is None:
                    self._shinzen_periodic_job = self.after(1000, self._shinzen_periodic_tick)
            except Exception:
                pass

    def _shinzen_is_idle(self):
        try:
            return (time.time() - float(getattr(self, "_last_typing_ts", 0.0) or 0.0)) >= float(self.shinzen_idle_threshold_sec)
        except Exception:
            return False

    def _safe_generate_phi(self, prompt, max_tokens=80):
        """Generate a short comment using the Phi model (Shinzen only)."""
        try:
            if not self.phi_ready or self.phi_model is None:
                return ""
            call_kwargs = {"prompt": prompt, "max_tokens": max_tokens}
            if make_sampler is not None:
                call_kwargs["sampler"] = make_sampler(temp=0.45, top_p=0.85, top_k=0)
            return generate(self.phi_model, self.phi_tokenizer, **call_kwargs)
        except Exception:
            return ""

    def _run_shinzen_analysis(self):
        try:
            if getattr(self, '_shinzen_paused', False):
                return
            if getattr(self, "_shinzen_analysis_inflight", False):
                return

            code = self.editor.get("1.0", "end-1c").strip()
            if not code:
                self._set_shinzen_suggestion("Engine is empty. Add code and I will review it.", mood="listening", duration=6200)
                return

            now = time.time()
            force = bool(getattr(self, "_shinzen_force_refresh", False))
            idle_hint = bool(getattr(self, "_shinzen_idle_hint", False))
            digest = str(hash(code))
            cooldown = max(5, int(getattr(self, "shinzen_feedback_cooldown_sec", 20)))
            since_comment = now - float(getattr(self, "_last_shinzen_comment_ts", 0.0) or 0.0)
            if since_comment < cooldown:
                return
            if (not force) and (not idle_hint) and digest == self._last_shinzen_digest:
                return

            self._shinzen_analysis_inflight = True
            self._shinzen_force_refresh = False
            self._shinzen_idle_hint = False

            # Run on a background thread so we don't block the UI
            threading.Thread(
                target=self._run_shinzen_analysis_bg,
                args=(code, digest, idle_hint),
                daemon=True,
            ).start()
        except Exception:
            pass

    def _collect_engine_diagnostics(self, code):
        issues = []
        ideas = []
        summary = []
        lines = code.splitlines()
        line_count = len(lines)
        long_lines = sum(1 for ln in lines if len(ln) > 110)
        todo_count = len(re.findall(r"\b(?:todo|fixme)\b", code, flags=re.IGNORECASE))
        bare_except_count = len(re.findall(r"except\s*:", code))
        wildcard_import_count = len(re.findall(r"from\s+\S+\s+import\s+\*", code))
        print_count = len(re.findall(r"\bprint\s*\(", code))
        has_main_guard = bool(re.search(r'if\s+__name__\s*==\s*["\']__main__["\']\s*:', code))
        summary.append(f"{line_count} lines")
        summary.append(f"{print_count} print call(s)")

        syntax_error = ""
        function_count = 0
        class_count = 0
        missing_docstrings = 0
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_count += 1
                    if ast.get_docstring(node) is None:
                        missing_docstrings += 1
                elif isinstance(node, ast.ClassDef):
                    class_count += 1
                    if ast.get_docstring(node) is None:
                        missing_docstrings += 1
            summary.append(f"{function_count} function(s), {class_count} class(es)")
        except SyntaxError as e:
            syntax_error = f"Syntax error at line {getattr(e, 'lineno', '?')}: {getattr(e, 'msg', str(e))}"
            issues.append(syntax_error)

        if long_lines:
            issues.append(f"{long_lines} long line(s) over 110 characters.")
        if todo_count:
            issues.append(f"{todo_count} TODO/FIXME note(s) still in the file.")
        if bare_except_count:
            issues.append("Bare `except:` found; use specific exceptions.")
        if wildcard_import_count:
            issues.append("Wildcard import detected; prefer explicit imports.")
        if missing_docstrings >= 2:
            ideas.append("Add brief docstrings to functions/classes to improve maintainability.")
        if print_count >= 6:
            ideas.append("Consider switching repeated print statements to logging.")
        if (not has_main_guard) and function_count > 0:
            ideas.append("Add an `if __name__ == '__main__':` runner entry for clearer execution.")
        if not issues and not ideas:
            ideas.append("Code is stable right now; next step could be adding small tests for key paths.")

        return {
            "summary": ", ".join(summary),
            "issues": issues[:4],
            "ideas": ideas[:4],
            "syntax_error": syntax_error,
            "line_count": line_count,
        }

    def _fallback_shinzen_message(self, diagnostics, idle_hint=False):
        issues = diagnostics.get("issues", [])
        ideas = diagnostics.get("ideas", [])
        syntax_error = diagnostics.get("syntax_error", "")
        if idle_hint:
            seed = ideas or self.project_ideas
            return random.choice(seed)
        if syntax_error:
            return f"{syntax_error}. Fix that first."
        if issues:
            return "Focus now: " + issues[0]
        if ideas:
            return "Next upgrade: " + ideas[0]
        return "Code looks healthy. Next step: add one targeted test."

    def _shorten_shinzen_tip(self, text, max_chars=96):
        val = (text or "").strip()
        if not val:
            return ""

        val = re.sub(r"\s+", " ", val).strip()
        parts = re.split(r"(?<=[.!?])\s+", val)
        short = parts[0].strip() if parts else val

        if len(short) > max_chars:
            short = short[:max_chars].rstrip()
            if " " in short:
                short = short.rsplit(" ", 1)[0]
            short = short.rstrip(",;:-") + "..."
        return short

    def _shinzen_feedback_mood(self, diagnostics, idle_hint=False):
        if idle_hint:
            return "idea"
        if diagnostics.get("syntax_error"):
            return "alert"
        if diagnostics.get("issues"):
            return "concern"
        if diagnostics.get("ideas"):
            return "explain"
        return "happy"

    def _low_quality_shinzen_text(self, text):
        s = (text or "").strip()
        if len(s) < 12:
            return True
        low = s.lower()
        if low.count("shinzen") > 2:
            return True
        # repeated lines or loops are typically low quality in the bubble
        lines = [ln.strip().lower() for ln in s.splitlines() if ln.strip()]
        if len(lines) >= 2 and len(set(lines)) <= max(1, len(lines) // 2):
            return True
        words = re.findall(r"[a-zA-Z_]{3,}", low)
        if words:
            top = max(words.count(w) for w in set(words))
            if top >= 7:
                return True
        return False

    def _run_shinzen_analysis_bg(self, code, digest, idle_hint=False):
        """Background Shinzen analysis — uses Phi model if ready, else static checks."""
        try:
            if getattr(self, '_shinzen_paused', False):
                return

            diagnostics = self._collect_engine_diagnostics(code)
            fallback = self._fallback_shinzen_message(diagnostics, idle_hint=idle_hint)
            final = fallback

            if self.phi_ready:
                try:
                    mode_text = "idle idea mode" if idle_hint else "live coding feedback mode"
                    issues = diagnostics.get("issues", [])
                    ideas = diagnostics.get("ideas", [])
                    short_code = code[:2600]
                    phi_prompt = (
                        "You are Shinzen, an expert and friendly Python coding coach inside an IDE.\n"
                        f"Mode: {mode_text}.\n"
                        "Rules:\n"
                        "- Be specific and useful.\n"
                        "- Exactly one short sentence.\n"
                        "- Keep it under 16 words.\n"
                        "- No role labels, no disclaimers, no repeating phrases.\n"
                        "- If syntax error exists, prioritize the fix.\n\n"
                        f"Engine summary: {diagnostics.get('summary', '')}\n"
                        f"Issues: {' | '.join(issues) if issues else 'none'}\n"
                        f"Ideas: {' | '.join(ideas) if ideas else 'none'}\n\n"
                        f"Code:\n```python\n{short_code}\n```\n\n"
                        "Shinzen response:"
                    )
                    ai_comment = self._safe_generate_phi(phi_prompt, max_tokens=90)
                    ai_comment = self._sanitize_response(ai_comment, mode="general").strip()
                    ai_comment = re.sub(r"^Shinzen(?: response)?:\s*", "", ai_comment, flags=re.IGNORECASE).strip()
                    if ai_comment and (not self._low_quality_shinzen_text(ai_comment)):
                        final = ai_comment
                except Exception:
                    final = fallback

            final = self._shorten_shinzen_tip(final, max_chars=96)
            final = self._sanitize_text(final.strip(), limit=120, keep=70)
            if not final:
                final = self._shorten_shinzen_tip(fallback, max_chars=96)

            mood = self._shinzen_feedback_mood(diagnostics, idle_hint=idle_hint)
            issue_count = len(diagnostics.get("issues", []))

            def apply_shinzen_result():
                self._set_shinzen_suggestion(final, mood=mood, duration=8200)
                self._last_shinzen_comment = final
                self._last_shinzen_comment_ts = time.time()
                self._last_shinzen_issue_count = issue_count
                if not idle_hint:
                    self._last_shinzen_digest = digest

            self.after(0, apply_shinzen_result)
        except Exception:
            pass
        finally:
            try:
                self.after(0, lambda: setattr(self, "_shinzen_analysis_inflight", False))
            except Exception:
                self._shinzen_analysis_inflight = False

    def _animate_shinzen_bubble(self, show=True):
        try:
            bubble = getattr(self, "shinzen_bubble_outer", None)
            if bubble is None:
                return

            if self._bubble_anim_job is not None:
                try:
                    self.after_cancel(self._bubble_anim_job)
                except Exception:
                    pass
                self._bubble_anim_job = None

            steps = 6
            delay = 24
            start_y = 0.078 if show else 0.02
            end_y = 0.02 if show else 0.078

            if show:
                self._bubble_visible = True
                bubble.place(relx=0.02, rely=start_y, width=210, height=126)

            def step(i):
                t = float(i) / float(steps)
                y = start_y + ((end_y - start_y) * t)
                try:
                    bubble.place(relx=0.02, rely=y, width=210, height=126)
                except Exception:
                    return

                if i < steps:
                    self._bubble_anim_job = self.after(delay, lambda: step(i + 1))
                    return

                self._bubble_anim_job = None
                self._bubble_visible = bool(show)
                if not show:
                    try:
                        bubble.place_forget()
                    except Exception:
                        pass

            step(0)
        except Exception:
            pass

    def _show_shinzen_bubble(self, text, duration=None):
        try:
            widget = getattr(self, "shinzen_bubble_text", None)
            if widget is None:
                return
            widget.config(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", self._sanitize_text(str(text), limit=140, keep=70))
            widget.config(state="disabled")

            self._animate_shinzen_bubble(show=True)

            if self._bubble_hide_job is not None:
                try:
                    self.after_cancel(self._bubble_hide_job)
                except Exception:
                    pass
                self._bubble_hide_job = None

            if duration and int(duration) > 0:
                self._bubble_hide_job = self.after(int(duration), self._hide_shinzen_bubble)
        except Exception:
            pass

    def _hide_shinzen_bubble(self):
        try:
            should_animate = True
            bubble = getattr(self, "shinzen_bubble_outer", None)
            if bubble is not None and (not self._bubble_visible):
                try:
                    if not bubble.winfo_ismapped():
                        should_animate = False
                except Exception:
                    should_animate = False
            if should_animate:
                self._animate_shinzen_bubble(show=False)
            if self._bubble_hide_job is not None:
                try:
                    self.after_cancel(self._bubble_hide_job)
                except Exception:
                    pass
                self._bubble_hide_job = None
        except Exception:
            pass

    def _set_shinzen_suggestion(self, text, mood="explain", duration=8000):
        """Update the Shinzen speech bubble text widget with AI-generated short guidance."""
        try:
            self._show_shinzen_bubble(text, duration=duration)
            if hasattr(self, "shinzen") and self.shinzen is not None:
                if hasattr(self.shinzen, "trigger"):
                    self.shinzen.trigger("suggestion", hold_ms=min(2600, int(duration)))
                    if mood and mood != "suggestion":
                        self.shinzen.trigger(mood, hold_ms=min(2400, int(duration)))
                else:
                    self.shinzen.set_state(mood or "idea")
        except Exception:
            pass

    def _pause_shinzen(self):
        """Pause scheduled Shinzen analysis (e.g. while Coding AI is responding)."""
        try:
            self._shinzen_paused = True
            if hasattr(self, "_shinzen_job") and self._shinzen_job is not None:
                try:
                    self.after_cancel(self._shinzen_job)
                except Exception:
                    pass
                self._shinzen_job = None
        except Exception:
            pass

    def _resume_shinzen(self):
        """Resume Shinzen analysis after Coding AI finishes."""
        try:
            self._shinzen_paused = False
            self._schedule_shinzen_analysis(delay=500, force=True)
        except Exception:
            pass

    # -------------------- FILE OPS --------------------
    def _set_project_root(self, path):
        try:
            if not path:
                return False
            abs_path = os.path.abspath(path)
            if not os.path.isdir(abs_path):
                return False
            self.project_root = abs_path
            self._save_preferences()
            return True
        except Exception:
            return False

    def _open_project(self):
        try:
            path = filedialog.askdirectory(title="Open project folder")
            if not path:
                return False
            if self._set_project_root(path):
                self._set_status_temporary(f"Project root set: {os.path.basename(path)}", duration=2200)
                return True
            self._set_status_temporary("Could not set project root", duration=2000)
            return False
        except Exception as e:
            self._set_status_temporary(f"Open project failed: {e}", duration=2200)
            return False

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
            self.project_root = os.path.dirname(fn) or self.project_root
            self.editor_dirty = False
            self.editor.edit_modified(False)
            self._highlight_syntax()
            self._update_file_label()
            self._save_preferences()
            self._schedule_shinzen_analysis(delay=120, force=True)
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
            self.project_root = os.path.dirname(fn) or self.project_root
            self.editor_dirty = False
            self.editor.edit_modified(False)
            self._update_file_label()
            self._save_preferences()
            self._schedule_shinzen_analysis(delay=180, force=True)
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
        if self.run_mode == "active_file":
            txt = "Run: Active File"
        elif self.run_mode == "workspace":
            txt = "Run: Workspace Sandbox"
        else:
            txt = "Run: Temp Sandbox"
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
                # Schedule Shinzen analysis for suggestions
                try:
                    if hasattr(self, "shinzen") and self.shinzen is not None and hasattr(self.shinzen, "trigger"):
                        self.shinzen.trigger("typing", hold_ms=700)
                    self._schedule_shinzen_analysis()
                except Exception:
                    pass
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
            "Double check that it works before giving the user it.\n"
            "Return only the updated code in a fenced Python block.\n\n"
            f"Current code:\n```python\n{code}\n```\n\n"
            f"Instruction:\n{instr}\n"
        )

        if self.model_ready:
            self.start_loader()
        self._set_presence_message("AI Fill is rewriting your code...", mood="thinking")
        threading.Thread(target=self._generate_and_insert, args=(prompt, sel), daemon=True).start()

    def _generate_and_insert(self, prompt, selection_ranges=None):
        try:
            resp = self._generate_text(prompt=prompt, max_tokens=self.coding_max_tokens, mode="coding")
            normalized = self._normalize_coding_response(resp)
            new_code = normalized.get("code") or ""
            display_text = normalized.get("response_text") or resp

            if not new_code:
                self.after(0, lambda: self._append_assistant(self.coding_card["text"], display_text, label="Coding AI"))
                self.after(0, lambda: self._set_status_temporary("AI Fill skipped: output was not valid Python.", duration=2400))
                return

            def apply_changes():
                if selection_ranges:
                    self.editor.delete(selection_ranges[0], selection_ranges[1])
                    self.editor.insert(selection_ranges[0], new_code)
                else:
                    self._apply_minimal_edits_to_editor(new_code)
                self._highlight_syntax()
                self._mark_editor_dirty()
                self._schedule_session_autosave()
                self._append_assistant(self.coding_card["text"], display_text, label="Coding AI")
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
    def _on_snail_clicked(self):
        lines = [
            "I am cheering for your next prompt.",
            "Need help? Tap Help and I can guide the controls.",
            "You are doing great. Keep going.",
            "Let us make this session smooth and fast.",
            "I can watch while you run code too.",
        ]
        self._set_presence_message(random.choice(lines), mood="wink", duration=2200)

    def _set_presence_message(self, msg, mood="idle", duration=None, show_bubble=True):
        try:
            safe_msg = self._sanitize_text(str(msg), limit=120, keep=60)
            try:
                if hasattr(self, "shinzen") and self.shinzen is not None:
                    if hasattr(self.shinzen, "trigger") and mood not in {"idle", "loading", "running", "thinking"}:
                        hold = min(int(duration or 1800), 2800)
                        self.shinzen.trigger(mood, hold_ms=hold)
                    else:
                        self.shinzen.set_state(mood)
            except Exception:
                pass

            # Bubble is the unified status indicator.
            if not show_bubble:
                pass
            elif (mood or "").lower() == "idle":
                if self._bubble_hide_job is None and self._bubble_visible:
                    self._hide_shinzen_bubble()
            else:
                bubble_duration = duration if duration else 4200
                self._show_shinzen_bubble(safe_msg, duration=bubble_duration)

            if self._presence_reset_job is not None:
                try:
                    self.after_cancel(self._presence_reset_job)
                except Exception:
                    pass
                self._presence_reset_job = None

            if duration and int(duration) > 0:
                self._presence_reset_job = self.after(int(duration), self._refresh_status)
        except Exception:
            pass

    def start_loader(self):
        try:
            # increment active task count
            self._active_tasks = getattr(self, "_active_tasks", 0) + 1
            if self._active_tasks == 1:
                # Prefer shinzen animation if available
                if hasattr(self, "shinzen") and self.shinzen is not None:
                    self.shinzen.start()
                elif hasattr(self, "loader") and self.loader is not None:
                    self.loader.start()
                self._set_presence_message("Thinking through this with care...", mood="thinking")
        except Exception:
            pass

        disable_buttons = [
            "open_button",
            "save_button",
            "save_as_button",
            "run_button",
            "ai_fill_btn",
            "undo_ai_btn",
            "runtime_btn",
            "shell_btn",
            "ideas_btn",
            "settings_btn",
            "help_btn",
            "clear_chat_btn",
        ]
        for btn_name in disable_buttons:
            try:
                btn = getattr(self, btn_name, None)
                if btn is not None:
                    btn.configure(state="disabled")
            except Exception:
                pass

        for widget in [self.coding_card["entry"], self.coding_card["ask"]]:
            try:
                widget.configure(state="disabled")
            except Exception:
                pass

    def stop_loader(self):
        try:
            # decrement active tasks
            self._active_tasks = max(0, getattr(self, "_active_tasks", 0) - 1)
            if self._active_tasks == 0:
                if hasattr(self, "shinzen") and self.shinzen is not None:
                    self.shinzen.stop()
                elif hasattr(self, "loader") and self.loader is not None:
                    self.loader.stop()
        except Exception:
            pass

        enable_buttons = [
            "open_button",
            "save_button",
            "save_as_button",
            "run_button",
            "ai_fill_btn",
            "undo_ai_btn",
            "runtime_btn",
            "shell_btn",
            "ideas_btn",
            "settings_btn",
            "help_btn",
            "clear_chat_btn",
        ]
        for btn_name in enable_buttons:
            try:
                btn = getattr(self, btn_name, None)
                if btn is not None:
                    btn.configure(state="normal")
            except Exception:
                pass

        for widget in [self.coding_card["entry"], self.coding_card["ask"]]:
            try:
                widget.configure(state="normal")
            except Exception:
                pass

        try:
            self._refresh_status()
        except Exception:
            pass

    def _set_status_temporary(self, msg, duration=3000):
        try:
            lowered = str(msg).lower()
            mood = "idle"
            if any(x in lowered for x in ("error", "failed", "timeout", "killed")):
                mood = "alert"
            elif any(x in lowered for x in ("stopped", "cancelled", "skipped", "blocked")):
                mood = "concern"
            elif any(x in lowered for x in ("running", "executing")):
                mood = "running"
            elif any(x in lowered for x in ("attached", "detached", "copied")):
                mood = "listening"
            elif any(x in lowered for x in ("saved", "opened", "created", "copied", "enabled", "shared", "injected")):
                mood = "celebrate"
            self._set_presence_message(msg, mood=mood, duration=duration)
        except Exception:
            pass

    def _refresh_status(self):
        """Keep Shinzen's message in sync with model/run/task state."""
        try:
            if not MLX_AVAILABLE:
                self._set_presence_message("Model runtime not installed. Engine tools are still ready.", mood="concern")
                return
            if not self.model_ready and not self.model_failed:
                self._set_presence_message(f"Loading model on {DEVICE}...", mood="thinking")
                return
            if self.model_failed:
                self._set_presence_message("Model load failed. You can still run code and retry.", mood="concern")
                return
            proc = getattr(self, "current_proc", None)
            if proc is not None and proc.poll() is None:
                self._set_presence_message("Running your engine code now...", mood="running")
                return
            if getattr(self, "_active_tasks", 0) > 0:
                self._set_presence_message("I am working on your request...", mood="thinking")
                return
            if self._shinzen_is_idle():
                self._set_presence_message(f"Ready on {DEVICE}. I can suggest the next tweak when you are ready.", mood="sleepy")
            else:
                self._set_presence_message(f"Ready on {DEVICE}. Ask anything when you are.", mood="idle")
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
        """Cancel an in-progress AI response for the given kind (coding) by bumping its token."""
        try:
            if kind == "coding":
                self.abort_tokens[kind] = self.abort_tokens.get(kind, 0) + 1
                self._set_status_temporary(f"Stopped {kind} response", duration=900)
                self.stop_loader()
            else:
                # Cancel coding
                for k in list(self.abort_tokens.keys()):
                    self.abort_tokens[k] = self.abort_tokens.get(k, 0) + 1
                self._set_status_temporary("Stopped responses", duration=900)
                self.stop_loader()
        except Exception:
            pass

    def _show_coding_slash_menu(self, x, y):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="/Runtime", command=lambda: self._insert_attachment_tag_into_entry("Runtime"))
        menu.add_command(label="/Engine", command=lambda: self._insert_attachment_tag_into_entry("Engine"))
        menu.add_command(label="/Errors", command=lambda: self._insert_attachment_tag_into_entry("Errors"))
        menu.add_command(label="/Shinzen", command=lambda: self._insert_attachment_tag_into_entry("Shinzen"))
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
            if getattr(self, "output_text", None) is None:
                self._set_status_temporary("Runtime window has no output yet", duration=1400)
                return
            out = self.output_text.get("1.0", "end-1c").strip()
            if not out:
                self._set_status_temporary("No runtime output available", duration=1400)
                return
            payload = AttachmentManager.prepare_runtime_snippet(out, max_chars=1200)
            if not payload:
                self._set_status_temporary("No runtime output available", duration=1400)
                return
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
            payload = AttachmentManager.prepare_engine_snippet(code, max_chars=1600)
            if not payload:
                self._set_status_temporary("Engine textbox is empty", duration=1400)
                return
            self._add_coding_attachment("Engine code", "Engine code", payload)
        except Exception:
            pass

    def _attach_errors_to_coding(self):
        try:
            if getattr(self, "output_text", None) is None:
                self._set_status_temporary("Runtime window has no output yet", duration=1400)
                return
            out = self.output_text.get("1.0", "end-1c")
            payload = AttachmentManager.prepare_error_snippet(out, max_lines=80)
            if not payload:
                self._set_status_temporary("No error lines found in runtime output", duration=1400)
                return
            self._add_coding_attachment("Errors", "Errors", payload)
        except Exception:
            pass

    def _attach_general_chat_to_coding(self):
        try:
            self._set_status_temporary("General AI chat not available", duration=1400)
        except Exception:
            pass

    def _attach_shinzen_to_coding(self):
        try:
            txt = (getattr(self, "_last_shinzen_comment", "") or "").strip()
            if not txt:
                target = getattr(self, 'shinzen_bubble_text', None) or getattr(self, 'shinzen_suggestions', None)
                if target is not None:
                    txt = target.get('1.0', 'end-1c').strip()
            if not txt:
                self._set_status_temporary('No Shinzen suggestions to attach', duration=1400)
                return
            payload = AttachmentManager.prepare_shinzen_snippet(txt, max_chars=320)
            if not payload:
                self._set_status_temporary('No Shinzen suggestions to attach', duration=1400)
                return
            self._add_coding_attachment('Shinzen', 'Shinzen suggestions', payload)
            self._set_status_temporary('Shinzen suggestions attached to Coding AI', duration=1400)
        except Exception:
            pass

    def _insert_shinzen_into_engine(self):
        try:
            txt = (getattr(self, "_last_shinzen_comment", "") or "").strip()
            if not txt:
                target = getattr(self, 'shinzen_bubble_text', None) or getattr(self, 'shinzen_suggestions', None)
                if target is not None:
                    txt = target.get('1.0', 'end-1c').strip()
            if not txt:
                self._set_status_temporary('No Shinzen suggestions to insert', duration=1400)
                return
            commented = '# Shinzen suggestions:\n' + '\n'.join('# ' + ln for ln in txt.splitlines()) + '\n\n'
            current = self.editor.get('1.0', 'end-1c')
            if current.strip():
                self.editor.insert('end', '\n' + commented)
            else:
                self.editor.insert('1.0', commented)
            self._highlight_syntax()
            self._mark_editor_dirty()
            self._schedule_session_autosave()
            self._set_status_temporary('Inserted Shinzen suggestions into Engine', duration=1400)
        except Exception:
            pass

    def _undo_last_ai_injection(self):
        try:
            if self._last_ai_injection is None:
                self._set_status_temporary("No AI injection snapshot to undo", duration=1400)
                return
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", self._last_ai_injection)
            self._highlight_syntax()
            self._mark_editor_dirty()
            self._schedule_session_autosave()
            self._set_status_temporary("Reverted last AI code injection", duration=1800)
            self._last_ai_injection = None
        except Exception:
            pass

    def _on_open_clicked(self):
        self._open_snippet()

    def _on_open_project_clicked(self):
        self._open_project()

    def _on_save_clicked(self):
        self._save_snippet(force_dialog=False)

    def _on_save_as_clicked(self):
        self._save_snippet(force_dialog=True)

    def _on_run_clicked(self):
        self._set_status_temporary("Running engine code...")
        self._open_runtime_terminal()
        if self.model_ready:
            self.start_loader()
        code = self.editor.get("1.0", "end-1c")
        threading.Thread(target=self._run_code, args=(code, True), daemon=True).start()

    def _on_stop_clicked(self):
        self._set_status_temporary("Stopping process...", duration=1800)
        self._stop_response("coding")
        self._kill_current_proc()
        self.stop_loader()

    def _on_ai_fill_clicked(self):
        self._ai_fill()

    def _on_create_shell_clicked(self):
        self._create_shell()

    def _on_clear_clicked(self):
        self._clear_chat_widget(self.coding_card["text"])
        self._set_status_temporary("Chat cleared", duration=1500)

    def _toggle_auto_run(self):
        self.auto_run_coding = not self.auto_run_coding
        self._refresh_coding_controls()
        self._save_preferences()
        self._set_status_temporary(
            "Coding auto-run enabled" if self.auto_run_coding else "Coding auto-run disabled",
            duration=1800,
        )

    def _insert_mode_button_text(self):
        if self.insert_mode == "append":
            return "Insert: Append"
        if self.insert_mode == "noop":
            return "Insert: Off"
        return "Insert: Replace"

    def _insert_mode_status_text(self):
        if self.insert_mode == "append":
            return "Insert mode: Append"
        if self.insert_mode == "noop":
            return "Insert mode: Preview only"
        return "Insert mode: Replace"

    def _toggle_insert_mode(self):
        cycle = ["replace", "append", "noop"]
        try:
            idx = cycle.index(self.insert_mode)
        except ValueError:
            idx = 0
        self.insert_mode = cycle[(idx + 1) % len(cycle)]
        self._refresh_coding_controls()
        self._save_preferences()
        self._set_status_temporary(
            self._insert_mode_status_text(),
            duration=1800,
        )

    def _refresh_coding_controls(self):
        try:
            self.auto_run_btn.configure(text="Auto Run: On" if self.auto_run_coding else "Auto Run: Off")
            self.insert_mode_btn.configure(text=self._insert_mode_button_text())
        except Exception:
            pass

    def _share_project_ideas(self):
        ideas = random.sample(self.project_ideas, k=min(6, len(self.project_ideas)))
        body = "Here are some project upgrade ideas:\n\n" + "\n".join([f"{i + 1}. {idea}" for i, idea in enumerate(ideas)])
        self._append_assistant(self.coding_card["text"], body, label="Idea Coach")
        self._set_presence_message("Shared new project ideas", mood="idea", duration=2400)

    def _coerce_int(self, value, min_v, max_v, fallback):
        try:
            n = int(str(value).strip())
            return max(min_v, min(max_v, n))
        except Exception:
            return fallback

    def _bind_shortcuts(self):
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
        self.bind_all("<Control-Shift-O>", self._shortcut_open_project)
        self.bind_all("<Command-Shift-O>", self._shortcut_open_project)
        self.bind_all("<F1>", lambda _e: self._open_help())

    # -------------------- Layout helpers --------------------
    def _on_root_configure(self, event=None):
        # Debounce rapid resize events
        try:
            if getattr(self, "_right_resize_job", None):
                try:
                    self.after_cancel(self._right_resize_job)
                except Exception:
                    pass
            self._right_resize_job = self.after(120, self._enforce_right_panel_height)
        except Exception:
            pass

    def _enforce_right_panel_height(self):
        try:
            total_h = self.winfo_height()
            if not total_h or total_h <= 0:
                return
            max_allowed = int(total_h * getattr(self, "_right_max_frac", 1.0 / 3.0))
            # allow some minimal height
            try:
                min_h = 180
                override = getattr(self, '_right_min_height_required', 0) or 0
                # choose the largest of min, max_allowed, and any explicit required minimum (e.g., when coding card is placed lower)
                desired = max(min_h, max_allowed, override)
                self.right.configure(height=desired)
            except Exception:
                pass
        except Exception:
            pass

    def _shortcut_save(self, event=None):
        self._on_save_clicked()
        return "break"

    def _shortcut_open(self, event=None):
        self._on_open_clicked()
        return "break"

    def _shortcut_open_project(self, event=None):
        self._on_open_project_clicked()
        return "break"


if __name__ == "__main__":
    app = Code9()
    app.mainloop()
