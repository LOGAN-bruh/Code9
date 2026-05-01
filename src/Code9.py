import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
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
from chat_sanitizer import AIResponseCleaner, ChatSanitizer
from attachment_manager import AttachmentManager
from model_wrapper import ModelWrapper
from config import Config
from code_formatter import CodeFormatter
from context_accumulator import ContextAccumulator

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller Mac .app bundles """
    try:
        # PyInstaller stores path in _MEIPASS
        base_path = sys._MEIPASS
        
        # If we are in a Mac .app bundle, _MEIPASS points to Contents/Frameworks, 
        # but our models and sprites are stored in Contents/Resources.
        if sys.platform == "darwin" and base_path.endswith("Frameworks"):
            base_path = os.path.join(os.path.dirname(base_path), "Resources")
            
    except Exception:
        # If not running as an app (like in VS Code), use the current folder
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

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

LIGHT_THEME = {
    "BG": "#F5EFE7",
    "SURFACE": "#FFFDFB",
    "SURFACE_ALT": "#F6F2ED",
    "SOFT": "#E6D8C7",
    "ACCENT": "#C07A5B",
    "ACCENT_HOVER": "#A8674A",
    "TEXT": "#352922",
    "MUTED": "#826D5D",
    "BORDER": "#E4D8CB",
    "OUTPUT_BG": "#FDF9F4",
    "GLASS": "#FFF8F0",
    "EDITOR_BG": "#FFF9F4",
    "CHAT_BG": "#FFFCF8",
}

DARK_THEME = {
    "BG": "#181614",
    "SURFACE": "#211E1B",
    "SURFACE_ALT": "#2A2622",
    "SOFT": "#3A312B",
    "ACCENT": "#D08A66",
    "ACCENT_HOVER": "#B87556",
    "TEXT": "#F4EDE6",
    "MUTED": "#B8A697",
    "BORDER": "#3E342D",
    "OUTPUT_BG": "#1E1B18",
    "GLASS": "#28231F",
    "EDITOR_BG": "#171513",
    "CHAT_BG": "#1F1B18",
}

BG = LIGHT_THEME["BG"]
SURFACE = LIGHT_THEME["SURFACE"]
SURFACE_ALT = LIGHT_THEME["SURFACE_ALT"]
SOFT = LIGHT_THEME["SOFT"]
ACCENT = LIGHT_THEME["ACCENT"]
ACCENT_HOVER = LIGHT_THEME["ACCENT_HOVER"]
TEXT = LIGHT_THEME["TEXT"]
MUTED = LIGHT_THEME["MUTED"]
BORDER = LIGHT_THEME["BORDER"]
OUTPUT_BG = LIGHT_THEME["OUTPUT_BG"]
GLASS = LIGHT_THEME["GLASS"]
EDITOR_BG = LIGHT_THEME["EDITOR_BG"]
CHAT_BG = LIGHT_THEME["CHAT_BG"]


def _theme_should_use_dark(mode: str) -> bool:
    mode = (mode or "auto").lower()
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return datetime.now().hour >= 18


def _read_startup_theme_mode() -> str:
    try:
        path = os.path.join(os.path.expanduser("~"), ".code9", "settings.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            mode = str(raw.get("theme_mode", "auto")).strip().lower()
            if mode in {"auto", "light", "dark"}:
                return mode
    except Exception:
        pass
    return "auto"


def apply_theme_palette(mode: str):
    global BG, SURFACE, SURFACE_ALT, SOFT, ACCENT, ACCENT_HOVER, TEXT, MUTED, BORDER, OUTPUT_BG, GLASS, EDITOR_BG, CHAT_BG
    palette = DARK_THEME if _theme_should_use_dark(mode) else LIGHT_THEME
    BG = palette["BG"]
    SURFACE = palette["SURFACE"]
    SURFACE_ALT = palette["SURFACE_ALT"]
    SOFT = palette["SOFT"]
    ACCENT = palette["ACCENT"]
    ACCENT_HOVER = palette["ACCENT_HOVER"]
    TEXT = palette["TEXT"]
    MUTED = palette["MUTED"]
    BORDER = palette["BORDER"]
    OUTPUT_BG = palette["OUTPUT_BG"]
    GLASS = palette["GLASS"]
    EDITOR_BG = palette["EDITOR_BG"]
    CHAT_BG = palette["CHAT_BG"]
    ctk.set_appearance_mode("dark" if palette is DARK_THEME else "light")


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
        self.theme_mode = _read_startup_theme_mode()
        apply_theme_palette(self.theme_mode)
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
        self.open_file_paths = []
        self.file_buffers = {}
        self.file_dirty = set()
        self.untitled_counter = 0
        self.untitled_name = ""
        self.project_file_index = []
        self.workspace_extra_files = []
        self._last_diff_text = ""
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
        self.context_path = os.path.join(self.config_dir, "context_accumulator.json")
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
        self.last_opened_files = []
        self.auto_format_on_paste = True
        self.show_ai_diff = True
        self.workspace_max_files = 400
        self.context_accumulate_every = 4
        self.auto_install_missing_imports = False
        self.python_exec_path = sys.executable
        self.project_root = os.getcwd()
        # Link Shinzen suggestions automatically into the Coding AI prompts
        self.include_shinzen_in_coding = True
        self.stop_on_bad_response = True
        self.require_code_block_for_injection = True
        self.preferred_coding_model = resource_path("qwen-coder")
        self.preferred_shinzen_model = resource_path("phi-shinzen")
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

        # --- Idle Tracker Setup ---
        self.last_activity_time = time.time()
        self.is_currently_idle = False
        
        # ONLY typing will reset the timer now!
        self.bind("<Any-KeyPress>", self._reset_activity)
        self.bind("<Button>", self._reset_activity)
        
        # Start the background loop that checks the time
        self._check_idle_status()

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
        self._recent_idea_texts = []

        self._load_preferences()
        apply_theme_palette(self.theme_mode)
        self.context_accumulator = ContextAccumulator(
            self.context_path,
            promote_every=self.context_accumulate_every,
            max_memory_items=24,
        )
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
        self.topbar = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, height=104)
        self.topbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.topbar.grid_propagate(False)
        self.topbar.grid_columnconfigure(0, weight=0)
        self.topbar.grid_columnconfigure(1, weight=1)

        title_wrap = tk.Frame(self.topbar, bg=BG)
        title_wrap.grid(row=0, column=0, sticky="w", padx=(20, 8), pady=10)

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
            width=250,
            anchor="w",
        )
        self.file_label.pack(anchor="w", pady=(2, 0))

        # Status text is now fully integrated into the Shinzen speech bubble on the right.
        self.status_label = None

        # Top-right loader removed — Shinzen will be shown in the right column (larger instance)
        self.btn_bar = tk.Frame(self.topbar, bg=BG)
        self.btn_bar.grid(row=0, column=1, sticky="e", padx=(4, 12), pady=8)
        self.btn_bar_top = tk.Frame(self.btn_bar, bg=BG)
        self.btn_bar_bottom = tk.Frame(self.btn_bar, bg=BG)
        self.btn_bar_top.pack(anchor="e")
        self.btn_bar_bottom.pack(anchor="e", pady=(6, 0))

        self.new_button = self._make_toolbar_button(self.btn_bar_top, "New", 58, self._on_new_clicked)
        self.new_button.pack(side="left", padx=3)

        self.open_button = self._make_toolbar_button(self.btn_bar_top, "Open", 62, self._on_open_clicked)
        self.open_button.pack(side="left", padx=3)

        self.open_project_button = self._make_toolbar_button(self.btn_bar_top, "Project", 72, self._on_open_project_clicked)
        self.open_project_button.pack(side="left", padx=3)

        self.save_button = self._make_toolbar_button(self.btn_bar_top, "Save", 62, self._on_save_clicked)
        self.save_button.pack(side="left", padx=3)

        self.save_as_button = self._make_toolbar_button(self.btn_bar_top, "Save As", 74, self._on_save_as_clicked)
        self.save_as_button.pack(side="left", padx=3)

        self.format_button = self._make_toolbar_button(self.btn_bar_top, "Format", 70, self._on_format_clicked)
        self.format_button.pack(side="left", padx=3)

        self.run_button = self._make_toolbar_button(self.btn_bar_top, "Run", 62, self._on_run_clicked, primary=True)
        self.run_button.pack(side="left", padx=3)

        self.stop_button = self._make_toolbar_button(
            self.btn_bar_top,
            "Stop",
            62,
            self._on_stop_clicked,
            fg="#EAC8BD",
            hover="#DEB0A2",
        )
        self.stop_button.pack(side="left", padx=3)

        self.ai_fill_btn = self._make_toolbar_button(self.btn_bar_bottom, "AI Fill", 74, self._on_ai_fill_clicked)
        self.ai_fill_btn.pack(side="left", padx=3)

        self.undo_ai_btn = self._make_toolbar_button(self.btn_bar_bottom, "Undo AI", 76, self._undo_last_ai_injection)
        self.undo_ai_btn.pack(side="left", padx=3)

        self.runtime_btn = self._make_toolbar_button(self.btn_bar_bottom, "Runtime", 76, self._open_runtime_terminal)
        self.runtime_btn.pack(side="left", padx=3)

        self.shell_btn = self._make_toolbar_button(self.btn_bar_bottom, "Shell", 64, self._on_create_shell_clicked)
        self.shell_btn.pack(side="left", padx=3)

        self.ideas_btn = self._make_toolbar_button(self.btn_bar_bottom, "Ideas", 64, self.request_shinzen_ideas)
        self.ideas_btn.pack(side="left", padx=3)

        self.settings_btn = self._make_toolbar_button(self.btn_bar_bottom, "Settings", 78, self._open_settings)
        self.settings_btn.pack(side="left", padx=3)

        self.help_btn = self._make_toolbar_button(self.btn_bar_bottom, "Help", 62, self._open_help)
        self.help_btn.pack(side="left", padx=3)

        self.clear_chat_btn = self._make_toolbar_button(self.btn_bar_bottom, "Clear", 62, self._on_clear_clicked)
        self.clear_chat_btn.pack(side="left", padx=3)

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
        self.left.grid_rowconfigure(2, weight=1)
        self.left.grid_columnconfigure(0, weight=1)

        left_header = tk.Frame(self.left, bg=SURFACE)
        left_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(0, 8))
        left_header.grid_columnconfigure(0, weight=1)

        engine_title = ctk.CTkLabel(
            left_header,
            text="Engine",              # Removed the \n
            font=(BASE_FONT[0], 16, "bold"),
            text_color=TEXT,
            fg_color=SURFACE,
            height=20,                  # Control the box height tightly
            pady=2                      # Add just a tiny bit of internal vertical space
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

        self.file_tabs_frame = tk.Frame(self.left, bg=SURFACE)
        self.file_tabs_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.file_tabs_frame.grid_columnconfigure(99, weight=1)

        editor_holder = tk.Frame(self.left, bg=SURFACE)
        editor_holder.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 10))
        editor_holder.grid_rowconfigure(0, weight=1)
        editor_holder.grid_columnconfigure(0, weight=1)
        editor_holder.grid_columnconfigure(2, weight=0)

        self.editor = tk.Text(
            editor_holder,
            font=(MONO_FONT[0], 13),
            bg=EDITOR_BG,
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
        self.editor.bind("<<Paste>>", self._on_editor_paste)

        self.editor_vsb = tk.Scrollbar(editor_holder, orient="vertical", command=self.editor.yview,
                                        bg=SOFT, troughcolor=SURFACE_ALT, activebackground=ACCENT,
                                        highlightthickness=0, bd=0, relief="flat")
        self.editor_vsb.grid(row=0, column=1, sticky="ns")

        self.editor_hsb = tk.Scrollbar(editor_holder, orient="horizontal", command=self.editor.xview,
                                        bg=SOFT, troughcolor=SURFACE_ALT, activebackground=ACCENT,
                                        highlightthickness=0, bd=0, relief="flat")
        self.editor_hsb.grid(row=1, column=0, sticky="ew")

        self.editor.config(yscrollcommand=self.editor_vsb.set, xscrollcommand=self.editor_hsb.set)

        self.diff_frame = ctk.CTkFrame(editor_holder, fg_color=SURFACE_ALT, corner_radius=10, border_width=1, border_color=BORDER)
        self.diff_frame.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        self.diff_frame.grid_rowconfigure(1, weight=1)
        self.diff_frame.grid_columnconfigure(0, weight=1)
        self.diff_title = ctk.CTkLabel(
            self.diff_frame,
            text="AI Changes",
            font=(BASE_FONT[0], 12, "bold"),
            text_color=TEXT,
            fg_color=SURFACE_ALT,
        )
        self.diff_title.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self.diff_text = tk.Text(
            self.diff_frame,
            font=(MONO_FONT[0], 10),
            bg=OUTPUT_BG,
            fg=TEXT,
            bd=0,
            relief="flat",
            highlightthickness=0,
            wrap="none",
            width=36,
            padx=8,
            pady=8,
            state="disabled",
        )
        self.diff_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._clear_diff_panel()
        if not self.show_ai_diff:
            self.diff_frame.grid_remove()

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
        snail_row.grid_columnconfigure(2, weight=0)

        # Speech bubble lives beside Shinzen, never over the sprite.
        self.shinzen_bubble_outer = tk.Frame(snail_row, bg=BG)
        self.shinzen_bubble_outer.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.shinzen_bubble_outer.grid_remove()
        bubble_row = tk.Frame(self.shinzen_bubble_outer, bg=BG)
        bubble_row.pack(fill="both", expand=True)

        bubble_frame = ctk.CTkFrame(
            bubble_row,
            fg_color=GLASS,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
            width=200,
            height=120,
        )
        bubble_frame.pack(side="left", padx=(0, 0), pady=(0, 0))
        bubble_frame.pack_propagate(False)

        self.shinzen_bubble_text = tk.Text(
            bubble_frame,
            height=6,
            bg=GLASS,
            fg=TEXT,
            bd=0,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            padx=2,
            pady=2,
            state="disabled",
            font=(BASE_FONT[0], 10),
        )

        self.shinzen_bubble_text.pack(fill="both", expand=True, padx=8, pady=7)

        tail = tk.Canvas(bubble_row, width=14, height=22, bg=BG, highlightthickness=0)
        tail.pack(side="left", padx=(0, 0), pady=26)
        tail.create_polygon(1, 11, 13, 5, 13, 17, fill=GLASS, outline=BORDER)

        # --- Snail (right of bubble) ---
        self.shinzen = Shinzen(
            snail_row,
            sprite_paths=None,
            frame_duration=130,
            size=(148, 148),
            on_click=self._on_snail_clicked,
        )
        self.shinzen.canvas.configure(bg=BG)
        self.shinzen.canvas.grid(row=0, column=2, padx=(4, 0), pady=4, sticky="e")

        try:
            self.shinzen.start()
        except Exception:
            pass

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
            bg=CHAT_BG,
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

        chat_vsb = tk.Scrollbar(text_wrap, orient="vertical", command=chat_text.yview,
                                bg=SOFT, troughcolor=SURFACE_ALT, activebackground=ACCENT,
                                highlightthickness=0, bd=0, relief="flat")
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
            height = 30,
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
            self.last_opened_files = list(data.get("last_opened_files", []) or [])
            self.auto_install_missing_imports = bool(data.get("auto_install_missing_imports", self.auto_install_missing_imports))
            self.auto_format_on_paste = bool(data.get("auto_format_on_paste", self.auto_format_on_paste))
            self.show_ai_diff = bool(data.get("show_ai_diff", self.show_ai_diff))
            self.theme_mode = data.get("theme_mode", self.theme_mode) if data.get("theme_mode") in {"auto", "light", "dark"} else self.theme_mode
            self.python_exec_path = (data.get("python_exec_path", self.python_exec_path) or self.python_exec_path).strip()
            self.project_root = (data.get("project_root", self.project_root) or self.project_root).strip() or self.project_root
            self.workspace_max_files = self._coerce_int(data.get("workspace_max_files", self.workspace_max_files), 25, 3000, self.workspace_max_files)
            self.context_accumulate_every = self._coerce_int(data.get("context_accumulate_every", self.context_accumulate_every), 2, 12, self.context_accumulate_every)
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
            "last_opened_files": list(self.open_file_paths or self.last_opened_files or []),
            "auto_install_missing_imports": self.auto_install_missing_imports,
            "auto_format_on_paste": self.auto_format_on_paste,
            "show_ai_diff": self.show_ai_diff,
            "theme_mode": self.theme_mode,
            "python_exec_path": self.python_exec_path,
            "project_root": self.project_root,
            "workspace_max_files": self.workspace_max_files,
            "context_accumulate_every": self.context_accumulate_every,
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

        if self.restore_last_file:
            restore_paths = []
            for p in list(self.last_opened_files or []):
                if p and os.path.exists(p):
                    restore_paths.append(p)
            if self.last_opened_file and os.path.exists(self.last_opened_file) and self.last_opened_file not in restore_paths:
                restore_paths.insert(0, self.last_opened_file)
            if restore_paths:
                loaded = self._open_snippet(path=restore_paths, from_restore=True)

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
        self._refresh_open_files_bar()

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
        auto_format_var = tk.BooleanVar(value=self.auto_format_on_paste)
        show_diff_var = tk.BooleanVar(value=self.show_ai_diff)

        ctk.CTkCheckBox(wrap, text="Auto-run code from Coding AI", variable=auto_run_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Typewriter animation in chat", variable=type_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Persist session draft", variable=persist_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Restore last opened file on launch", variable=restore_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Auto-stop nonsense coding replies", variable=stop_bad_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Require fenced code block before injection", variable=require_block_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Enable idle code ideas", variable=idle_ideas_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Auto-install missing imports before run (e.g., pygame)", variable=auto_install_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Auto-format pasted code", variable=auto_format_var, text_color=TEXT).pack(anchor="w", pady=4)
        ctk.CTkCheckBox(wrap, text="Show AI change summary beside Engine", variable=show_diff_var, text_color=TEXT).pack(anchor="w", pady=4)

        ctk.CTkLabel(wrap, text="Theme", text_color=TEXT, font=(BASE_FONT[0], 13, "bold")).pack(anchor="w", pady=(14, 4))
        theme_map = {
            "Auto (dark after 6 PM)": "auto",
            "Light": "light",
            "Dark": "dark",
        }
        theme_label = next((k for k, v in theme_map.items() if v == self.theme_mode), "Auto (dark after 6 PM)")
        theme_var = tk.StringVar(value=theme_label)
        ctk.CTkOptionMenu(wrap, values=list(theme_map.keys()), variable=theme_var, fg_color=SURFACE_ALT, button_color=SOFT, button_hover_color=ACCENT_HOVER, text_color=TEXT).pack(anchor="w", pady=2)

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

        ctk.CTkLabel(grid, text="Workspace file scan limit", text_color=MUTED).grid(row=8, column=0, sticky="w", pady=6)
        workspace_max_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        workspace_max_entry.grid(row=8, column=1, sticky="ew", padx=(10, 0), pady=6)
        workspace_max_entry.insert(0, str(self.workspace_max_files))

        ctk.CTkLabel(grid, text="Context accumulation steps", text_color=MUTED).grid(row=9, column=0, sticky="w", pady=6)
        accumulate_entry = ctk.CTkEntry(grid, fg_color=SURFACE_ALT)
        accumulate_entry.grid(row=9, column=1, sticky="ew", padx=(10, 0), pady=6)
        accumulate_entry.insert(0, str(self.context_accumulate_every))

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
            self.auto_format_on_paste = bool(auto_format_var.get())
            self.show_ai_diff = bool(show_diff_var.get())
            old_theme = self.theme_mode
            self.theme_mode = theme_map.get(theme_var.get(), self.theme_mode)

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
            self.workspace_max_files = self._coerce_int(workspace_max_entry.get(), 25, 3000, self.workspace_max_files)
            self.context_accumulate_every = self._coerce_int(accumulate_entry.get(), 2, 12, self.context_accumulate_every)
            try:
                self.context_accumulator.promote_every = self.context_accumulate_every
            except Exception:
                pass
            self._index_project_files(self.project_root)
            self._schedule_shinzen_analysis(delay=200, force=True)

            if self.show_ai_diff:
                try:
                    self.diff_frame.grid()
                except Exception:
                    pass
            else:
                try:
                    self.diff_frame.grid_remove()
                except Exception:
                    pass
            if old_theme != self.theme_mode:
                self._apply_theme_runtime()

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
            "- New: starts an unnamed file; choose Save As when you are ready to name it.\n"
            "- Open: open one or many files/assets into the workspace.\n"
            "- Project: choose a project root folder for workspace sandbox runs.\n"
            "- Save / Save As: save current Engine content.\n"
            "- Format: clean up current Engine code with the shared formatter.\n"
            "- Run: execute Engine code in temp sandbox, active file mode, or workspace sandbox mode.\n"
            "- Stop: stop the running Engine process.\n"
            "- AI Fill: rewrite selected code (or full editor) from a natural-language instruction.\n"
            "- Shell: export the current Engine code as a direct runnable Python file.\n"
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
            "- Auto-format pasted code: formats clipboard code before inserting into Engine.\n"
            "- Show AI change summary: displays line-level changes beside the Engine after AI edits.\n"
            "- Theme: Auto switches to dark mode after 6 PM; Light and Dark force a theme.\n"
            "- Run Mode: Temp Sandbox isolates runs; Active File runs the saved file directly; Workspace Sandbox copies your project for multi-file/assets runs.\n"
            "- Code Insert Mode: Replace swaps whole editor; Append adds generated code at end; Preview mode leaves editor unchanged.\n"
            "- Coding Model: primary model for coding chat and AI Fill.\n"
            "- Shinzen Comment Model: lightweight model for Shinzen bubble feedback.\n"
            "- Coding max tokens: max length for coding responses.\n"
            "- Run timeout (sec): maximum runtime before process is stopped.\n"
            "- Run Python interpreter: choose the Python executable used by Run.\n"
            "- Project root: base folder used by workspace sandbox runs.\n"
            "- Workspace file scan limit: maximum number of files to index during a workspace search.\n"
            "- Context accumulation steps: how many past turns of chat history are retained for context.\n"
        )

        panel = tk.Text(
            wrap,
            bg=CHAT_BG,
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

    def _apply_theme_runtime(self):
        apply_theme_palette(self.theme_mode)
        try:
            self.configure(fg_color=BG)
            for widget in (
                getattr(self, "topbar", None),
                getattr(self, "left", None),
                getattr(self, "right", None),
                getattr(self, "coding_card", {}).get("frame") if isinstance(getattr(self, "coding_card", None), dict) else None,
            ):
                if widget is not None:
                    try:
                        use_bg = widget is getattr(self, "topbar", None) or widget is getattr(self, "right", None)
                        widget.configure(fg_color=BG if use_bg else SURFACE)
                    except Exception:
                        pass
            for frame_name in ("btn_bar", "btn_bar_top", "btn_bar_bottom", "file_tabs_frame"):
                frame = getattr(self, frame_name, None)
                if frame is not None:
                    try:
                        frame.configure(bg=BG if frame_name.startswith("btn") else SURFACE)
                    except Exception:
                        pass
            self.title_label.configure(text_color=TEXT, fg_color=BG)
            self.file_label.configure(text_color=MUTED, fg_color=BG)
            self.editor.configure(bg=EDITOR_BG, fg=TEXT, insertbackground=TEXT)
            for sb in (getattr(self, "editor_vsb", None), getattr(self, "editor_hsb", None)):
                if sb is not None:
                    try:
                        sb.configure(bg=SOFT, troughcolor=SURFACE_ALT, activebackground=ACCENT)
                    except Exception:
                        pass
            if getattr(self, "diff_text", None) is not None:
                self.diff_text.configure(bg=OUTPUT_BG, fg=TEXT, insertbackground=TEXT)
            if getattr(self, "shinzen_bubble_text", None) is not None:
                self.shinzen_bubble_text.configure(bg=GLASS, fg=TEXT)
            if hasattr(self, "coding_card"):
                self.coding_card["text"].configure(bg=CHAT_BG, fg=TEXT, insertbackground=TEXT)
                self._setup_chat_tags(self.coding_card["text"])
            self._setup_editor_tags()
            self._highlight_syntax()
            self._refresh_open_files_bar()
        except Exception:
            pass

    # -------------------- CHAT HELPERS --------------------
    def _setup_chat_tags(self, widget):
        try:
            widget.tag_config("role", foreground=MUTED, font=(BASE_FONT[0], 10, "bold"), spacing1=6)
            widget.tag_config("user", foreground=TEXT, background=SURFACE_ALT, lmargin1=8, lmargin2=8, spacing1=2, spacing3=6)
            widget.tag_config("assistant", foreground=TEXT, background=CHAT_BG, lmargin1=8, lmargin2=8, spacing1=2, spacing3=8)
            widget.tag_config("assistant_code_header", foreground=ACCENT, background=OUTPUT_BG, font=(BASE_FONT[0], 10, "bold"), lmargin1=8, lmargin2=8, spacing1=6)
            widget.tag_config("assistant_code", foreground=TEXT, background=OUTPUT_BG, font=(MONO_FONT[0], 10), lmargin1=12, lmargin2=12, spacing1=2, spacing3=8)
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
        target.tag_config("welcome", justify="center", font=(BASE_FONT[0], 26, "bold"), foreground=TEXT)
        
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

    def _insert_assistant_content(self, widget, text):
        safe_text = AIResponseCleaner.clean(text or "")
        pos = 0
        inserted_any = False
        for match in ChatSanitizer.CODE_BLOCK_PATTERN.finditer(safe_text):
            prose = safe_text[pos:match.start()].strip()
            if prose:
                start = widget.index("end-1c")
                # Preserve line breaks for bullet points and numbered lists
                widget.insert("end", prose + "\n")
                widget.tag_add("assistant", start, widget.index("end-1c"))
                inserted_any = True
            lang = (match.group(1) or "code").strip() or "code"
            code = (match.group(2) or "").strip("\n")
            header_start = widget.index("end-1c")
            widget.insert("end", f"\nGenerated Code ({lang}):\n")
            widget.tag_add("assistant_code_header", header_start, widget.index("end-1c"))
            code_start = widget.index("end-1c")
            widget.insert("end", code + "\n")
            widget.tag_add("assistant_code", code_start, widget.index("end-1c"))
            inserted_any = True
            pos = match.end()
        rest = safe_text[pos:].strip()
        if rest:
            start = widget.index("end-1c")
            widget.insert("end", rest + "\n")
            widget.tag_add("assistant", start, widget.index("end-1c"))
            inserted_any = True
        if not inserted_any:
            start = widget.index("end-1c")
            widget.insert("end", safe_text + "\n")
            widget.tag_add("assistant", start, widget.index("end-1c"))

    def _append_assistant(self, widget, text, label="Assistant", kind=None, request_id=None):
        """Append assistant text to a chat widget. If request_id is provided, this append is cancelled
        when self.abort_tokens[kind] changes.
        """
        self._clear_chat_welcome_if_needed(widget)
        safe_text = self._sanitize_text(AIResponseCleaner.clean(text or ""))

        # If a request id is provided and doesn't match current, skip appending
        try:
            if kind and request_id is not None:
                if request_id != self.abort_tokens.get(kind):
                    # cancelled before append started
                    return
        except Exception:
            pass

        has_code = bool(ChatSanitizer.CODE_BLOCK_PATTERN.search(safe_text or ""))
        if (not self.enable_typewriter) or has_code:
            try:
                widget.config(state="normal")
                widget.insert("end", f"\n{label}:\n", ("role",))
                self._insert_assistant_content(widget, safe_text)
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
        idea_prompt = "Give me fresh, specific upgrade ideas for this current project."
        if not self.model_ready:
            self._share_project_ideas()
            return
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
            cleaned = AIResponseCleaner.clean(cleaned)
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

    def _classify_coding_intent(self, query):
        try:
            return ChatSanitizer.classify_intent(query or "")
        except Exception:
            return "code"

    def _build_project_context(self):
        try:
            self._capture_active_file_buffer()
        except Exception:
            pass

        root = self._resolve_project_root()
        parts = []
        active = self.current_file_path or ""
        if active:
            try:
                parts.append(f"Active file: {os.path.relpath(active, root)}")
            except Exception:
                parts.append(f"Active file: {os.path.basename(active)}")
        if root:
            parts.append(f"Project root: {root}")

        try:
            memory = self.context_accumulator.prompt_context("coding", max_items=5)
            if memory:
                parts.append(memory)
        except Exception:
            pass

        inventory_paths = []
        for rel in list(getattr(self, "project_file_index", []) or [])[:80]:
            inventory_paths.append(os.path.join(root, rel))
        if not inventory_paths:
            inventory_paths = list(getattr(self, "open_file_paths", []) or [])

        inventory = AttachmentManager.prepare_file_inventory(
            inventory_paths,
            root=root,
            max_files=min(80, int(getattr(self, "workspace_max_files", 400))),
            label="Workspace files",
        )
        if inventory:
            parts.append(inventory)

        open_text_files = [
            p for p in list(getattr(self, "open_file_paths", []) or [])
            if p != active and os.path.isfile(p) and CodeFormatter.is_text_file(p)
        ][:4]
        for path in open_text_files:
            snippet = AttachmentManager.prepare_file_snippet(path, root=root, max_chars=1000)
            if snippet:
                parts.append(snippet)

        return "\n\n".join(part for part in parts if part).strip()

    def _build_coding_prompt(self, query, editor_snapshot, attachments_text="", intent="code"):
        project_context = self._build_project_context()
        active_name = os.path.basename(self.current_file_path or "session_draft.py")
        shared = (
            f"User request:\n{query}\n\n"
            f"Current active file ({active_name}):\n```python\n{editor_snapshot}\n```\n\n"
        )
        if project_context:
            shared += f"{project_context}\n\n"
        if attachments_text:
            shared += f"{attachments_text}\n\n"

        if intent == "idea":
            return (
                "You are an IDE project coach. Give fresh, specific, non-repeating project ideas.\n"
                "Rules:\n"
                "- Do not output replacement code.\n"
                "- Mention concrete files, workflows, tests, UI, or architecture when useful.\n"
                "- Return 5 concise numbered ideas.\n"
                "- Avoid generic advice like 'add comments' unless tied to this project.\n\n"
                + shared
                + "Project ideas:"
            )

        if intent in {"question", "chat"}:
            return (
                "You are answering a coding question inside an IDE.\n"
                "Rules:\n"
                "- Answer the question directly and concisely.\n"
                "- Do not replace the Engine editor content.\n"
                "- Use short code snippets only when they clarify the answer.\n"
                "- You may use bullet points (- item) for lists of steps or options.\n"
                "- Do not repeat yourself. Each sentence must add new information.\n"
                "- If the user asks whether something should change, explain the tradeoff.\n\n"
                + shared
                + "Answer:"
            )

        return (
            "You are the Code9 Coding AI editing a Python active file.\n"
            "Rules:\n"
            "- Return exactly one fenced ```python code block containing the full updated active file.\n"
            "- The code must parse in Python.\n"
            "- Use sibling modules and assets from the workspace when appropriate.\n"
            "- If the user gives a partial code block, complete it into one full runnable active file.\n"
            "- Do not wrap the user's code in launcher/temp-file boilerplate unless explicitly requested.\n"
            "- No role labels, no markdown outside the code block except one optional short note after it.\n"
            "- Do not repeat sentences or restate what you already said.\n"
            "- If the request is not asking for code, answer with a short note and no code block.\n\n"
            + shared
            + "Updated active file:"
        )

    def _local_idea_response(self, query=""):
        ideas = self._build_contextual_project_ideas(count=6)
        if not ideas:
            ideas = random.sample(self.project_ideas, k=min(6, len(self.project_ideas)))
        body = "Fresh project ideas:\n\n" + "\n".join(
            f"{i + 1}. {idea}" for i, idea in enumerate(ideas)
        )
        return body

    def _idea_response_is_generic(self, text):
        s = (text or "").strip()
        if len(s) < 40:
            return True
        if self._is_nonsense_response(s, mode="general"):
            return True
        low = s.lower()
        generic_hits = sum(
            1
            for phrase in (
                "add more comments",
                "improve the ui",
                "write tests",
                "make it better",
                "optimize performance",
            )
            if phrase in low
        )
        return generic_hits >= 3

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

        # 2. Check for intent commands and classify natural-language requests.
        if not intent:
            lower_q = raw_query.lower()
            if lower_q.startswith("/ask ") or lower_q.startswith("/chat ") or lower_q.startswith("/question ") or lower_q in ("/ask", "/chat", "/question"):
                intent = "question"
                raw_query = re.sub(r"^/(ask|chat|question)\s*", "", raw_query, flags=re.IGNORECASE)
            elif lower_q.startswith("/idea"):
                intent = "idea"
                raw_query = re.sub(r"^/idea\s*", "", raw_query, flags=re.IGNORECASE)
                if not raw_query:
                    raw_query = "Give me fresh, specific upgrade ideas for this current project."
            else:
                intent = self._classify_coding_intent(raw_query)

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
            
        self._set_presence_message("Thinking..." if intent in ["question", "chat", "idea"] else "Coding AI is crafting code...", mood="thinking")

        try:
            self._pause_shinzen()
        except Exception:
            pass

        threading.Thread(target=self._coding_worker, args=(query, req_id, intent), daemon=True).start()

    def _coding_worker(self, query, reqid=None, intent="code"):
        try:
            self.after(0, self._lock_ui)
            editor = getattr(self, "editor", None)
            if editor is None:
                return

            try:
                editorsnapshot = editor.get("1.0", "end-1c")
            except Exception:
                editorsnapshot = ""

            attachmentstext = ""
            try:
                attachments = getattr(self, "coding_attachments", {}) or {}
                if attachments:
                    attachmentstext = "Attached resources:\n" + "\n\n".join(
                        str(v) for v in attachments.values() if v
                    )
            except Exception:
                attachmentstext = ""

            if intent == "code" and (not self.model_ready):
                self.after(
                    0,
                    lambda rid=reqid: self._append_assistant(
                        self.coding_card["text"],
                        "Coding model is not ready yet, so I left the Engine unchanged.",
                        label="Coding AI",
                        kind="coding",
                        request_id=rid,
                    ),
                )
                self.after(0, lambda: self._set_presence_message("Coding model is still loading; Engine stayed unchanged.", mood="concern", duration=2400))
                return

            try:
                self.context_accumulator.add("coding", editorsnapshot[:1800], source="active editor")
                if attachmentstext:
                    self.context_accumulator.add("coding", attachmentstext[:1800], source="attachments")
            except Exception:
                pass

            if intent == "idea" and (not self.model_ready):
                response = self._local_idea_response(query)
            else:
                prompt = self._build_coding_prompt(query, editorsnapshot, attachmentstext, intent)
                response_mode = "coding" if intent == "code" else "general"
                response = self._generate_text(
                    prompt,
                    self.coding_max_tokens,
                    mode=response_mode,
                )

            if reqid is not None and reqid != getattr(self, "abort_tokens", {}).get("coding", reqid):
                return

            if not response:
                return

            if intent in {"question", "chat", "idea"}:
                display = self._sanitize_response(response, mode="general")
                if intent == "idea" and self._idea_response_is_generic(display):
                    display = self._local_idea_response(query)
                label = "Idea" if intent == "idea" else "Shinzen"
                self.after(
                    0,
                    lambda d=display, l=label, rid=reqid: self._append_assistant(
                        self.coding_card["text"],
                        d,
                        label=l,
                        kind="coding",
                        request_id=rid,
                    ),
                )
                self.after(0, lambda: self._set_presence_message("Shared a response without changing Engine.", mood="listening", duration=2200))
                return

            normalized = self._normalize_coding_response(response)
            if normalized.get("needs_retry"):
                repair_prompt = self._build_coding_repair_prompt(query, response, normalized.get("issue"))
                repaired = self._generate_text(repair_prompt, self.coding_max_tokens, mode="coding")
                normalized = self._normalize_coding_response(repaired)

            display_text = normalized.get("response_text") or response
            self.after(
                0,
                lambda d=display_text, rid=reqid: self._append_assistant(
                    self.coding_card["text"],
                    d,
                    label="Coding AI",
                    kind="coding",
                    request_id=rid,
                ),
            )
            if normalized.get("code"):
                self.after(0, lambda c=normalized["code"]: self._inject_code_into_engine(c))
            else:
                self.after(0, lambda: self._set_status_temporary("Coding response did not include valid injectable Python.", duration=2600))
        except Exception:
            self.after(0, lambda tb=traceback.format_exc(): self._append_output(tb))
        finally:
            try:
                self.after(0, self.stop_loader)
                self.after(0, self._resume_shinzen)
                self.after(0, self._refresh_status)
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
        normalized = CodeFormatter.format_code(
            code,
            filename=self.current_file_path or "session_draft.py",
            language="python",
        )
        if not normalized.endswith("\n"):
            normalized += "\n"
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
        self._render_ai_diff(before, normalized)

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

    def _line_change_summary(self, before, after, max_items=80):
        before_lines = before.splitlines()
        after_lines = after.splitlines()
        sm = difflib.SequenceMatcher(None, before_lines, after_lines)
        lines = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            old_span = f"{i1 + 1}-{i2}" if i2 > i1 + 1 else str(i1 + 1)
            new_span = f"{j1 + 1}-{j2}" if j2 > j1 + 1 else str(j1 + 1)
            if tag == "replace":
                lines.append(f"Changed old line(s) {old_span} -> new line(s) {new_span}")
            elif tag == "delete":
                lines.append(f"Deleted old line(s) {old_span}")
            elif tag == "insert":
                lines.append(f"Inserted new line(s) {new_span} after old line {i1}")
            preview = after_lines[j1:j2][:3] if tag != "delete" else before_lines[i1:i2][:3]
            for item in preview:
                marker = "+" if tag != "delete" else "-"
                lines.append(f"  {marker} {item[:120]}")
            if len(lines) >= max_items:
                lines.append("  ...diff summary truncated")
                break
        return "\n".join(lines).strip() or "No visible line changes."

    def _clear_diff_panel(self, message="No AI changes yet."):
        self._last_diff_text = message
        try:
            if getattr(self, "diff_text", None) is None:
                return
            self.diff_text.config(state="normal")
            self.diff_text.delete("1.0", "end")
            self.diff_text.insert("1.0", message)
            self.diff_text.config(state="disabled")
        except Exception:
            pass

    def _render_ai_diff(self, before, after):
        try:
            summary = self._line_change_summary(before or "", after or "")
            self._last_diff_text = summary
            if not self.show_ai_diff:
                return
            if getattr(self, "diff_frame", None) is not None:
                self.diff_frame.grid()
            self.diff_text.config(state="normal")
            self.diff_text.delete("1.0", "end")
            self.diff_text.insert("1.0", summary)
            self.diff_text.config(state="disabled")
        except Exception:
            pass

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
            "dist",
            "build",
            ".idea",
            ".vscode",
            ".DS_Store",
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

        self._copy_open_files_into_sandbox(src_root, copied_root, run_path)

        run_cwd = os.path.dirname(run_path) or copied_root
        return temp_ctx, run_path, run_cwd, copied_root

    def _copy_open_files_into_sandbox(self, src_root, copied_root, run_path):
        try:
            self._capture_active_file_buffer()
        except Exception:
            pass

        open_paths = list(getattr(self, "open_file_paths", []) or [])
        buffers = dict(getattr(self, "file_buffers", {}) or {})
        used_names = set()

        for path in open_paths:
            try:
                if not path or not os.path.exists(path):
                    continue
                abs_path = os.path.abspath(path)
                try:
                    rel = os.path.relpath(abs_path, src_root)
                except Exception:
                    rel = ""
                if rel and not rel.startswith("..") and not os.path.isabs(rel):
                    target = os.path.join(copied_root, rel)
                else:
                    base = os.path.basename(abs_path)
                    target = os.path.join(copied_root, base)
                    if base in used_names and os.path.abspath(target) != os.path.abspath(run_path):
                        target = os.path.join(copied_root, "external_files", base)
                    used_names.add(base)

                if os.path.abspath(target) == os.path.abspath(run_path):
                    continue

                os.makedirs(os.path.dirname(target), exist_ok=True)
                if abs_path in buffers and CodeFormatter.is_text_file(abs_path):
                    with open(target, "w", encoding="utf-8") as f:
                        f.write(buffers[abs_path])
                elif os.path.isfile(abs_path):
                    shutil.copy2(abs_path, target)
            except Exception:
                continue

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
        try:
            self._capture_active_file_buffer()
        except Exception:
            pass
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
                fg_color=SURFACE_ALT,
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
        if s and (sum(1 for ch in s if ord(ch) > 127) / max(1, len(s))) > 0.04:
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
        # Block fake meta-comments: instructions disguised as observations
        # e.g. "Add docstrings to hex_to_rgb, rgb_to_hex, and generate_gradient functions."
        meta_patterns = [
            r"add docstrings? to\b",
            r"add (type hints?|annotations?|comments?) to\b",
            r"consider adding\b",
            r"you (should|could|might) add\b",
            r"missing docstrings?\b",
            r"^```",  # raw fenced block leaked into bubble
        ]
        for pat in meta_patterns:
            if re.search(pat, low):
                return True
        return False

    def _run_shinzen_analysis_bg(self, code, digest, idle_hint=False):
        """Background Shinzen analysis — uses Phi model if ready, else static checks."""
        try:
            if getattr(self, '_shinzen_paused', False):
                return

            diagnostics = self._collect_engine_diagnostics(code)
            try:
                self.context_accumulator.add("shinzen", diagnostics.get("summary", "") + " " + " ".join(diagnostics.get("issues", [])), source="diagnostics")
            except Exception:
                pass
            fallback = self._fallback_shinzen_message(diagnostics, idle_hint=idle_hint)
            final = fallback

            if self.phi_ready:
                try:
                    mode_text = "idle idea mode" if idle_hint else "live coding feedback mode"
                    issues = diagnostics.get("issues", [])
                    ideas = diagnostics.get("ideas", [])
                    short_code = code[:2600]
                    memory = ""
                    try:
                        memory = self.context_accumulator.prompt_context("shinzen", max_items=3)
                    except Exception:
                        memory = ""
                    phi_prompt = (
                        "You are Shinzen, an expert and friendly Python coding coach inside an IDE.\n"
                        f"Mode: {mode_text}.\n"
                        "Rules:\n"
                        "- Be specific and useful. Comment on what you actually SEE in the code.\n"
                        "- Exactly one short sentence.\n"
                        "- Keep it under 16 words.\n"
                        "- English only.\n"
                        "- No role labels, no disclaimers, no repeating phrases.\n"
                        "- If syntax error exists, prioritize the fix.\n"
                        "- NEVER write task instructions like 'Add docstrings to X' or 'Consider adding Y'.\n"
                        "- Make a real observation: e.g. 'Your gradient loop could exit early on identical colors.'\n\n"
                        f"Engine summary: {diagnostics.get('summary', '')}\n"
                        f"Issues: {' | '.join(issues) if issues else 'none'}\n"
                        f"Ideas: {' | '.join(ideas) if ideas else 'none'}\n\n"
                        f"{memory}\n\n"
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
            if show:
                self._bubble_visible = True
                try:
                    bubble.grid()
                except Exception:
                    pass
            else:
                self._bubble_visible = False
                try:
                    bubble.grid_remove()
                except Exception:
                    pass
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
    def _relative_project_path(self, path):
        try:
            root = self._resolve_project_root()
            rel = os.path.relpath(path, root)
            if rel and not rel.startswith(".."):
                return rel
        except Exception:
            pass
        return os.path.basename(path or "")

    def _capture_active_file_buffer(self):
        try:
            path = self.current_file_path
            if not path:
                if self.untitled_name:
                    self.file_buffers[self.untitled_name] = self.editor.get("1.0", "end-1c")
                return
            text = self.editor.get("1.0", "end-1c")
            self.file_buffers[os.path.abspath(path)] = text
            if self.editor_dirty:
                self.file_dirty.add(os.path.abspath(path))
        except Exception:
            pass

    def _choose_project_root_for_paths(self, paths):
        dirs = []
        for path in paths or []:
            try:
                if os.path.isdir(path):
                    dirs.append(os.path.abspath(path))
                elif os.path.isfile(path):
                    dirs.append(os.path.abspath(os.path.dirname(path)))
            except Exception:
                continue
        if not dirs:
            return self.project_root
        if len(dirs) == 1:
            return dirs[0]
        try:
            common = os.path.commonpath(dirs)
            home = os.path.expanduser("~")
            unsafe = {os.path.abspath(os.sep), os.path.abspath(home), os.path.abspath(os.path.dirname(home))}
            abs_common = os.path.abspath(common)
            common_is_selected_or_parent = any(os.path.abspath(d) == abs_common for d in dirs)
            project_markers = (".git", "pyproject.toml", "requirements.txt", "setup.py", "README.md")
            common_has_project_marker = any(os.path.exists(os.path.join(abs_common, marker)) for marker in project_markers)
            if common and abs_common not in unsafe and (common_is_selected_or_parent or common_has_project_marker):
                return common
        except Exception:
            pass
        return dirs[0]

    def _index_project_files(self, root=None):
        root = os.path.abspath(root or self.project_root or "")
        if not root or not os.path.isdir(root):
            self.project_file_index = []
            return []

        ignored_dirs = {
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
            "dist",
            "build",
        }
        max_files = max(25, int(getattr(self, "workspace_max_files", 400)))
        indexed = []
        try:
            for cur, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
                for name in sorted(files):
                    if name.endswith((".pyc", ".pyo")) or name == ".DS_Store":
                        continue
                    path = os.path.join(cur, name)
                    try:
                        rel = os.path.relpath(path, root)
                    except Exception:
                        rel = name
                    indexed.append(rel)
                    if len(indexed) >= max_files:
                        self.project_file_index = indexed
                        return indexed
        except Exception:
            pass
        self.project_file_index = indexed
        return indexed

    def _is_editable_file(self, path):
        try:
            return os.path.isfile(path) and CodeFormatter.is_text_file(path)
        except Exception:
            return False

    def _read_text_file(self, path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _register_open_file(self, path):
        try:
            abs_path = os.path.abspath(path)
            if not os.path.isfile(abs_path):
                return False
            if abs_path not in self.open_file_paths:
                self.open_file_paths.append(abs_path)
            if self._is_editable_file(abs_path) and abs_path not in self.file_buffers:
                self.file_buffers[abs_path] = self._read_text_file(abs_path)
            return True
        except Exception:
            return False

    def _switch_active_file(self, path):
        try:
            abs_path = os.path.abspath(path)
            if not self._is_editable_file(abs_path):
                self._set_status_temporary(f"Registered asset: {os.path.basename(abs_path)}", duration=1500)
                return False
            self._capture_active_file_buffer()
            if abs_path not in self.open_file_paths:
                self.open_file_paths.append(abs_path)
            data = self.file_buffers.get(abs_path)
            if data is None:
                data = self._read_text_file(abs_path)
                self.file_buffers[abs_path] = data
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", data)
            self.current_file_path = abs_path
            self.last_opened_file = abs_path
            if abs_path not in self.last_opened_files:
                self.last_opened_files.append(abs_path)
            self.editor_dirty = abs_path in self.file_dirty
            self.editor.edit_modified(False)
            self._highlight_syntax()
            self._update_file_label()
            self._refresh_open_files_bar()
            self._schedule_shinzen_analysis(delay=120, force=True)
            return True
        except Exception as e:
            self._set_status_temporary(f"Switch file failed: {e}", duration=2200)
            return False

    def _new_file(self):
        try:
            self._capture_active_file_buffer()
            self.untitled_counter += 1
            self.untitled_name = f"Untitled {self.untitled_counter}"
            self.current_file_path = None
            self.editor.delete("1.0", "end")
            self.editor_dirty = True
            self.editor.edit_modified(False)
            self._last_ai_injection = None
            self._clear_diff_panel("New unnamed file. Save when you are ready to name it.")
            self._update_file_label()
            self._refresh_open_files_bar()
            self._set_status_temporary(f"Created {self.untitled_name}", duration=1600)
            try:
                self.shinzen.trigger("new", hold_ms=1100, force=True)
            except Exception:
                pass
            return True
        except Exception as e:
            self._set_status_temporary(f"New file failed: {e}", duration=2200)
            return False

    def _switch_untitled(self):
        try:
            if not self.untitled_name:
                return
            self._capture_active_file_buffer()
            self.current_file_path = None
            data = self.file_buffers.get(self.untitled_name, "")
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", data)
            self.editor_dirty = True
            self.editor.edit_modified(False)
            self._highlight_syntax()
            self._update_file_label()
            self._refresh_open_files_bar()
        except Exception:
            pass

    def _close_open_file(self, path):
        try:
            abs_path = os.path.abspath(path)
            if abs_path == os.path.abspath(self.current_file_path or ""):
                self._capture_active_file_buffer()
            if abs_path in self.file_dirty:
                try:
                    ok = messagebox.askyesno(
                        "Close file",
                        f"Close {os.path.basename(abs_path)} without saving changes?",
                    )
                    if not ok:
                        return
                except Exception:
                    pass
            self.open_file_paths = [p for p in self.open_file_paths if os.path.abspath(p) != abs_path]
            self.file_buffers.pop(abs_path, None)
            self.file_dirty.discard(abs_path)
            if abs_path == os.path.abspath(self.current_file_path or ""):
                next_file = next((p for p in self.open_file_paths if self._is_editable_file(p)), None)
                if next_file:
                    self.current_file_path = None
                    self._switch_active_file(next_file)
                else:
                    self.current_file_path = None
                    self.editor.delete("1.0", "end")
                    self.editor_dirty = False
                    self.untitled_name = ""
                    self._update_file_label()
            self.last_opened_files = list(self.open_file_paths)
            self._refresh_open_files_bar()
            self._save_preferences()
            self._set_status_temporary(f"Closed {os.path.basename(abs_path)}", duration=1200)
        except Exception as e:
            self._set_status_temporary(f"Close file failed: {e}", duration=1800)

    def _open_paths(self, paths, from_restore=False):
        if isinstance(paths, str):
            paths = [paths]
        clean_paths = []
        for path in paths or []:
            try:
                if path and os.path.exists(path):
                    clean_paths.append(os.path.abspath(path))
            except Exception:
                continue
        if not clean_paths:
            return False

        self._capture_active_file_buffer()
        directories = [p for p in clean_paths if os.path.isdir(p)]
        files = [p for p in clean_paths if os.path.isfile(p)]

        if directories:
            self.project_root = directories[0]
        elif files:
            self.project_root = self._choose_project_root_for_paths(files) or self.project_root

        opened_count = 0
        editable = []
        assets = []
        for path in files:
            if self._register_open_file(path):
                opened_count += 1
                if self._is_editable_file(path):
                    editable.append(path)
                else:
                    assets.append(path)

        self._index_project_files(self.project_root)
        if directories and not editable:
            for rel in self.project_file_index:
                candidate = os.path.join(self.project_root, rel)
                if self._is_editable_file(candidate):
                    self._register_open_file(candidate)
                    editable.append(candidate)
                    break

        active_target = editable[0] if editable else None
        if active_target:
            self._switch_active_file(active_target)
        else:
            self._update_file_label()
            self._refresh_open_files_bar()

        self.last_opened_files = list(self.open_file_paths)
        self._save_preferences()

        if not from_restore:
            if directories and not files:
                msg = f"Project opened: {os.path.basename(self.project_root)}"
            else:
                msg = f"Opened {opened_count} file(s)"
                if assets:
                    msg += f", {len(assets)} asset(s) registered"
            self._set_status_temporary(msg, duration=2200)
        return bool(active_target or opened_count or directories)

    def _refresh_open_files_bar(self):
        try:
            frame = getattr(self, "file_tabs_frame", None)
            if frame is None:
                return
            for child in frame.winfo_children():
                try:
                    child.destroy()
                except Exception:
                    pass

            editable = [p for p in self.open_file_paths if self._is_editable_file(p)]
            assets = [p for p in self.open_file_paths if p not in editable]
            if not editable and not assets and not self.untitled_name:
                return

            col = 0
            if self.untitled_name:
                active = self.current_file_path is None
                name = self.untitled_name + (" *" if self.editor_dirty else "")
                tab = tk.Frame(frame, bg=SURFACE)
                tab.grid(row=0, column=col, padx=(0, 5), pady=0, sticky="w")
                ctk.CTkButton(
                    tab,
                    text=name,
                    width=min(140, max(78, len(name) * 8)),
                    height=26,
                    corner_radius=9,
                    fg_color=ACCENT if active else SURFACE_ALT,
                    hover_color=ACCENT_HOVER if active else SOFT,
                    text_color="white" if active else TEXT,
                    font=(BASE_FONT[0], 10, "bold"),
                    command=self._switch_untitled,
                ).pack(side="left")
                col += 1

            shown = editable[:8]
            for path in shown:
                active = os.path.abspath(path) == os.path.abspath(self.current_file_path or "")
                name = os.path.basename(path)
                if path in self.file_dirty:
                    name += " *"
                tab = tk.Frame(frame, bg=SURFACE)
                tab.grid(row=0, column=col, padx=(0, 5), pady=0, sticky="w")
                ctk.CTkButton(
                    tab,
                    text=name,
                    width=min(132, max(72, len(name) * 7)),
                    height=26,
                    corner_radius=9,
                    fg_color=ACCENT if active else SURFACE_ALT,
                    hover_color=ACCENT_HOVER if active else SOFT,
                    text_color="white" if active else TEXT,
                    font=(BASE_FONT[0], 10, "bold"),
                    command=lambda p=path: self._switch_active_file(p),
                ).pack(side="left")
                ctk.CTkButton(
                    tab,
                    text="x",
                    width=24,
                    height=26,
                    corner_radius=9,
                    fg_color=SURFACE_ALT,
                    hover_color=SOFT,
                    text_color=MUTED,
                    font=(BASE_FONT[0], 10, "bold"),
                    command=lambda p=path: self._close_open_file(p),
                ).pack(side="left", padx=(2, 0))
                col += 1

            if len(editable) > len(shown):
                more = ctk.CTkLabel(
                    frame,
                    text=f"+{len(editable) - len(shown)} files",
                    font=(BASE_FONT[0], 10),
                    text_color=MUTED,
                    fg_color=SURFACE,
                )
                more.grid(row=0, column=col, padx=(2, 6), sticky="w")
                col += 1
            if assets:
                for asset in assets[:3]:
                    asset_tab = tk.Frame(frame, bg=SURFACE)
                    asset_tab.grid(row=0, column=col, padx=(0, 5), pady=0, sticky="w")
                    ctk.CTkLabel(
                        asset_tab,
                        text=os.path.basename(asset),
                        width=min(110, max(62, len(os.path.basename(asset)) * 6)),
                        height=26,
                        corner_radius=9,
                        fg_color=SURFACE_ALT,
                        text_color=MUTED,
                        font=(BASE_FONT[0], 10),
                    ).pack(side="left")
                    ctk.CTkButton(
                        asset_tab,
                        text="x",
                        width=24,
                        height=26,
                        corner_radius=9,
                        fg_color=SURFACE_ALT,
                        hover_color=SOFT,
                        text_color=MUTED,
                        font=(BASE_FONT[0], 10, "bold"),
                        command=lambda p=asset: self._close_open_file(p),
                    ).pack(side="left", padx=(2, 0))
                    col += 1
                if len(assets) > 3:
                    asset_label = ctk.CTkLabel(
                        frame,
                        text=f"+{len(assets) - 3} asset(s)",
                        font=(BASE_FONT[0], 10),
                        text_color=MUTED,
                        fg_color=SURFACE,
                    )
                    asset_label.grid(row=0, column=col, padx=(2, 6), sticky="w")
        except Exception:
            pass

    def _set_project_root(self, path):
        try:
            if not path:
                return False
            abs_path = os.path.abspath(path)
            if not os.path.isdir(abs_path):
                return False
            self.project_root = abs_path
            self._index_project_files(abs_path)
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
                self._open_paths([path], from_restore=True)
                self._set_status_temporary(f"Project root set: {os.path.basename(path)}", duration=2200)
                return True
            self._set_status_temporary("Could not set project root", duration=2000)
            return False
        except Exception as e:
            self._set_status_temporary(f"Open project failed: {e}", duration=2200)
            return False

    def _open_snippet(self, path=None, from_restore=False):
        selected = path
        if not selected:
            selected = filedialog.askopenfilenames(
                title="Open files or assets",
                filetypes=[
                    ("Common code/assets", "*.py *.txt *.md *.json *.csv *.yaml *.yml *.toml *.png *.jpg *.jpeg *.gif *.svg"),
                    ("Python files", "*.py"),
                    ("Text files", "*.txt *.md *.json *.csv *.yaml *.yml *.toml"),
                    ("Images/assets", "*.png *.jpg *.jpeg *.gif *.svg *.ico"),
                    ("All files", "*.*"),
                ],
            )
        if not selected:
            return False
        try:
            return self._open_paths(list(selected) if not isinstance(selected, str) else [selected], from_restore=from_restore)
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
            self.current_file_path = os.path.abspath(fn)
            self.last_opened_file = self.current_file_path
            self.untitled_name = ""
            if self.current_file_path not in self.open_file_paths:
                self.open_file_paths.append(self.current_file_path)
            self.file_buffers[self.current_file_path] = content
            self.file_dirty.discard(self.current_file_path)
            self.last_opened_files = list(self.open_file_paths)
            self.project_root = os.path.dirname(self.current_file_path) or self.project_root
            self._index_project_files(self.project_root)
            self.editor_dirty = False
            self.editor.edit_modified(False)
            self._update_file_label()
            self._refresh_open_files_bar()
            self._save_preferences()
            self._schedule_shinzen_analysis(delay=180, force=True)
            self._set_status_temporary(f"Saved {os.path.basename(fn)}", duration=1800)
            return True
        except Exception as e:
            self._set_status_temporary(f"Save failed: {e}", duration=2400)
            return False

    def _update_file_label(self):
        if self.current_file_path:
            name = self._relative_project_path(self.current_file_path)
            if len(name) > 42:
                name = "..." + name[-39:]
            suffix = " *" if self.editor_dirty else ""
            count = len([p for p in self.open_file_paths if self._is_editable_file(p)])
            count_txt = f" ({count} open)" if count > 1 else ""
            self.file_label.configure(text=f"Engine file: {name}{suffix}{count_txt}")
        else:
            suffix = " *" if self.editor_dirty else ""
            name = self.untitled_name or "session draft"
            self.file_label.configure(text=f"Engine file: {name}{suffix}")

    def _mark_editor_dirty(self):
        if self.current_file_path:
            self.file_dirty.add(os.path.abspath(self.current_file_path))
        if not self.editor_dirty:
            self.editor_dirty = True
            self._update_file_label()
        self._refresh_open_files_bar()

    def _mark_editor_saved(self):
        if self.current_file_path:
            self.file_dirty.discard(os.path.abspath(self.current_file_path))
        self.editor_dirty = False
        self._update_file_label()
        self._refresh_open_files_bar()

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
            dark = _theme_should_use_dark(self.theme_mode)
            self.editor.tag_config("kw", foreground="#F0A15D" if dark else "#B25A2A")
            self.editor.tag_config("str", foreground="#7BCFA8" if dark else "#0D7A5A")
            self.editor.tag_config("comment", foreground=MUTED)
            self.editor.tag_config("builtin", foreground="#F2C66D" if dark else "#9A4E1D")
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

    def _format_editor_content(self):
        try:
            content = self.editor.get("1.0", "end-1c")
            if not content.strip():
                self._set_status_temporary("Nothing to format", duration=1400)
                return False
            formatted = CodeFormatter.format_code(
                content,
                filename=self.current_file_path or "session_draft.py",
            )
            if formatted == content or formatted.rstrip("\n") == content.rstrip("\n"):
                self._set_status_temporary("Engine code already looks formatted", duration=1500)
                return True
            self._apply_minimal_edits_to_editor(formatted)
            self._highlight_syntax()
            self._mark_editor_dirty()
            self._schedule_session_autosave()
            self._capture_active_file_buffer()
            self._set_status_temporary("Formatted Engine code", duration=1600)
            return True
        except Exception as e:
            self._set_status_temporary(f"Format failed: {e}", duration=2200)
            return False

    def _on_editor_paste(self, event=None):
        try:
            text = self.clipboard_get()
        except Exception:
            return None
        if not text:
            return "break"

        try:
            if self.auto_format_on_paste and CodeFormatter.looks_like_code(text, filename=self.current_file_path):
                insert_text = CodeFormatter.format_code(
                    text,
                    filename=self.current_file_path or "session_draft.py",
                )
            else:
                insert_text = CodeFormatter.normalize_line_endings(text)

            try:
                self.editor.delete("sel.first", "sel.last")
            except Exception:
                pass
            self.editor.insert("insert", insert_text)
            self._highlight_syntax()
            self._mark_editor_dirty()
            self._schedule_session_autosave()
            self._capture_active_file_buffer()
            return "break"
        except Exception:
            return None

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
        if not self.model_ready:
            self._append_assistant(
                self.coding_card["text"],
                "AI Fill needs the coding model to finish loading. I left the Engine unchanged.",
                label="Coding AI",
            )
            self._set_status_temporary("AI Fill skipped: coding model is not ready", duration=2200)
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
                before = self.editor.get("1.0", "end-1c")
                if selection_ranges:
                    self.editor.delete(selection_ranges[0], selection_ranges[1])
                    self.editor.insert(selection_ranges[0], new_code)
                else:
                    self._apply_minimal_edits_to_editor(new_code)
                after = self.editor.get("1.0", "end-1c")
                self._render_ai_diff(before, after)
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
        if not code.strip():
            self._set_status_temporary("Shell export skipped: Engine is empty", duration=1600)
            return
        fn = filedialog.asksaveasfilename(
            defaultextension=".py",
            initialfile=os.path.basename(self.current_file_path or "run_script.py"),
            filetypes=[("Python files", "*.py"), ("All files", "*.*")],
            title="Export runnable Python file",
        )
        if not fn:
            return
        try:
            final_code = CodeFormatter.format_code(code, filename=fn, language="python")
            with open(fn, "w", encoding="utf-8") as f:
                f.write(final_code)
            try:
                os.chmod(fn, os.stat(fn).st_mode | 0o111)
            except Exception:
                pass
            self._set_status_temporary(f"Exported runnable file: {os.path.basename(fn)}", duration=2000)
        except Exception as e:
            self._set_status_temporary(f"Shell export failed: {e}", duration=2400)

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
            "new_button",
            "open_button",
            "open_project_button",
            "save_button",
            "save_as_button",
            "format_button",
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
            "new_button",
            "open_button",
            "open_project_button",
            "save_button",
            "save_as_button",
            "format_button",
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

    def _on_new_clicked(self):
        self._new_file()

    def _on_open_clicked(self):
        self._open_snippet()

    def _on_open_project_clicked(self):
        self._open_project()

    def _on_save_clicked(self):
        self._save_snippet(force_dialog=False)

    def _on_save_as_clicked(self):
        self._save_snippet(force_dialog=True)

    def _on_format_clicked(self):
        self._format_editor_content()

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
        ideas = self._build_contextual_project_ideas(count=6)
        if not ideas:
            ideas = random.sample(self.project_ideas, k=min(6, len(self.project_ideas)))
        body = "Here are some project upgrade ideas:\n\n" + "\n".join([f"{i + 1}. {idea}" for i, idea in enumerate(ideas)])
        self._append_assistant(self.coding_card["text"], body, label="Idea Coach")
        self._set_presence_message("Shared new project ideas", mood="idea", duration=2400)

    def _build_contextual_project_ideas(self, count=6):
        ideas = []
        try:
            code = self.editor.get("1.0", "end-1c")
            diagnostics = self._collect_engine_diagnostics(code) if code.strip() else {}
            project_files = list(getattr(self, "project_file_index", []) or [])
            open_files = list(getattr(self, "open_file_paths", []) or [])
            file_names = {os.path.basename(p).lower() for p in project_files}
            text = code.lower()

            if len(open_files) > 1 or len(project_files) > 1:
                ideas.append("Add a project navigator command palette that jumps between open files, assets, and recent runs.")
            if not any(name.startswith("test_") or "/tests/" in f.replace("\\", "/") for name in file_names for f in project_files):
                ideas.append("Add a lightweight test runner panel with pass/fail output linked to the active file.")
            if "customtkinter" in text or "tkinter" in text:
                ideas.append("Add editor tabs with close buttons, dirty badges, and a save-all command for multi-file sessions.")
            if "subprocess" in text:
                ideas.append("Capture run history as searchable sessions with command, exit code, duration, and traceback filters.")
            if "mlx" in text or "generate(" in text:
                ideas.append("Create prompt profiles for code, questions, refactors, and ideas so model output routes safely.")
            if diagnostics.get("issues"):
                ideas.append("Turn Shinzen diagnostics into clickable quick-fixes for the top issue in the active file.")
            if diagnostics.get("line_count", 0) > 350:
                ideas.append("Add a symbol outline for functions/classes so large Engine files are easier to scan.")
            if not any(name == "readme.md" for name in file_names):
                ideas.append("Generate a project README from open files, run modes, settings, and common workflows.")

            ideas.extend(self.project_ideas)
            filtered = []
            recent = set(getattr(self, "_recent_idea_texts", []) or [])
            for idea in ideas:
                if idea in filtered or idea in recent:
                    continue
                filtered.append(idea)
            if len(filtered) < count:
                for idea in ideas:
                    if idea not in filtered:
                        filtered.append(idea)

            random.shuffle(filtered)
            selected = filtered[:max(1, int(count))]
            self._recent_idea_texts = (list(getattr(self, "_recent_idea_texts", []) or []) + selected)[-18:]
            return selected
        except Exception:
            return random.sample(self.project_ideas, k=min(count, len(self.project_ideas)))

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
        self.bind_all("<Control-Shift-F>", self._shortcut_format)
        self.bind_all("<Command-Shift-F>", self._shortcut_format)
        self.bind_all("<Control-Return>", lambda _e: self._on_run_clicked())
        self.bind_all("<Command-Return>", lambda _e: self._on_run_clicked())
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
    
    def _reset_activity(self, event=None):
        """Resets the idle timer whenever the user does something."""
        self.last_activity_time = time.time()
        
        # If the snail was asleep, wake it back up!
        if self.is_currently_idle:
            self.is_currently_idle = False
            if hasattr(self, 'shinzen') and self.shinzen:
                # Returns to standard idle animation when they move the mouse
                self.shinzen.set_state("idle") 

    def _check_idle_status(self):
        """Checks how many seconds have passed since the last action."""
        idle_seconds = time.time() - self.last_activity_time
        
        # If 60 seconds have passed, trigger the idle/sleepy state!
        if idle_seconds > 60 and not self.is_currently_idle:
            self.is_currently_idle = True
            if hasattr(self, 'shinzen') and self.shinzen:
                # This triggers the "sleepy" state from your EVENT_STATE_MAP
                self.shinzen.trigger("sleepy") 
                
        # Schedule this function to run again in 1000 milliseconds (1 second)
        self.after(1000, self._check_idle_status)

    def _shortcut_save(self, event=None):
        self._on_save_clicked()
        return "break"

    def _shortcut_open(self, event=None):
        self._on_open_clicked()
        return "break"

    def _shortcut_open_project(self, event=None):
        self._on_open_project_clicked()
        return "break"

    def _shortcut_format(self, event=None):
        self._on_format_clicked()
        return "break"


if __name__ == "__main__":
    app = Code9()
    app.mainloop()