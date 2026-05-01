import os
from os import path
import random
import sys
import tkinter as tk
from typing import Dict, List, Optional, Tuple, Union

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

SequenceSpec = List[Tuple[str, float]]


class Shinzen:
    """Preference-driven snail sprite animator with interactive transient states."""

    DEFAULT_STATE_PREFERENCES: Dict[str, SequenceSpec] = {
        "idle": [("SnailIdle", 4.8), ("SnailBlinking", 0.16), ("SnailIdle", 4.8)],
        "loading": [
            ("SnailLoading1", 0.20),
            ("SnailLoading2", 0.20),
            ("SnailLoading3", 0.20),
            ("SnailIdle", 0.20),
        ],
        "running": [
            ("SnailLoading1", 0.20),
            ("SnailLoading2", 0.20),
            ("SnailLoading3", 0.20),
            ("SnailIdle", 0.20),
        ],
        "thinking": [
            ("SnailChill:Yawn1", random.uniform(3.0, 5.0)),
            ("SnailPeering", random.uniform(3.0, 5.0)),
            ("SnailChill:Yawn1", random.uniform(3.0, 5.0)),
            ("SnailYawn2:JawDroppedSupprised", random.uniform(1.2, 3.0)),
            ("SnailChill:Yawn1", random.uniform(3.0, 5.0)),
        ],

        "typing": [("SnailPeering", 1.0)],
        "listening": [("SnailPeering", 0.72), ("SnailBlinking", 0.22)],
        "peering": [("SnailPeering", 1.05), ("SnailBlinking", 0.26)],
        "idea": [("SnailSubtleSupprised", 3.0), ("SnailChill:Yawn1", 0.3), ("SnailYawn2:JawDroppedSupprised", 0.5), ("SnailChill:Yawn1", 0.3), ("SnailYawn2:JawDroppedSupprised", 0.5), ("SnailChill:Yawn1", 0.3), ("SnailWink", random.uniform(3, 4.5))],
        "explain": [("SnailPeering", 2.5), ("SnailChill:Yawn1", 1.0), ("SnailYawn2:JawDroppedSupprised", 0.5), ("SnailChill:Yawn1", 1.0)],
        "happy": [("SnailWink", 1.5), ("SnailIdle", random.uniform(1.5,3.5)), ("SnailBlinking", 0.30)],
        "celebrate": [("SnailWink", 0.52), ("SnailSubtleSupprised", 1.5), ("SnailIdle", 4.0)],
        "wink": [("SnailWink", 0.4), ("SnailIdle", 3.0)],
        "concern": [("SnailRetracted", random.uniform(3.0, 4.5)), ("SnailShySad", random.uniform(4.5, 6.0))],
        "alert": [("SnailSubtleSupprised", random.uniform(3.0, 5.0)), ("SnailIdle", random.uniform(2.0, 3.0))],
        "surprised": [("SnailSubtleSupprised", 0.74)],
        "sleepy": [("SnailChill:Yawn1", random.uniform(2.0, 7.0)),
                    ("SnailYawn2:JawDroppedSupprised", random.uniform(1.0, 3.0)), 
                    ("SnailChill:Yawn1", random.uniform(4.0, 8.0)), 
                    ("SnailPeering", random.uniform(2.0, 4.0)), 
                    ("SnailShySad", random.uniform(10.0, 15.0)), 
                    ("SnailPeering", random.uniform(3.0, 6.0)), 
                    ("SnailChill:Yawn1", random.uniform(3.0, 5.0))]
    }

    EVENT_STATE_MAP: Dict[str, Tuple[str, int]] = {
        "hover": ("wink", 900),
        "click": ("concern", 950),
        "typing": ("typing", 900),
        "suggestion": ("explain", 1800),
        "success": ("celebrate", 1700),
        "error": ("concern", 1900),
        "idle": ("idle", 2200),
        "idea": ("idea", 1800),
        "save": ("happy", 1200),
        "open": ("peering", 1200),
        "new": ("surprised", 1200),
    }

    def __init__(
        self,
        parent,
        sprite_paths=None,
        frame_duration=180,
        size=(120, 120),
        on_click=None,
        state_preferences: Optional[Dict[str, Union[SequenceSpec, str]]] = None,
        **kwargs,
    ):
        self.parent = parent
        self.size = size
        self.frame_duration = frame_duration
        self.on_click_callback = on_click

        try:
            bg_color = parent.cget("bg")
        except Exception:
            try:
                bg_color = parent.cget("fg_color")
                if isinstance(bg_color, (list, tuple)):
                    bg_color = bg_color[0]
            except Exception:
                bg_color = "#ffffff"

        self.canvas = tk.Canvas(parent, width=self.size[0], height=self.size[1], highlightthickness=0, bg=bg_color)
        self._job = None
        self._hovering = False
        self._manual_state = "idle"
        self._state = "idle"
        self._state_index = 0
        self._transient_state: Optional[str] = None
        self._transient_job = None

        # Make sure to import sys and os at the top of Shinzen.py first!
        # Reroute path for Mac .app bundles
        try:
            base = sys._MEIPASS
            if sys.platform == "darwin" and base.endswith("Frameworks"):
                base = os.path.join(os.path.dirname(base), "Resources")
        except Exception:
            base = os.path.dirname(__file__)

        self.sp_dir = os.path.join(base, "SnailSprite")

        self._images: Dict[str, object] = {}
        self._load_all_images(sprite_paths)

        self.state_preferences: Dict[str, SequenceSpec] = {
            k: list(v) for k, v in self.DEFAULT_STATE_PREFERENCES.items()
        }
        if state_preferences:
            for state, spec in state_preferences.items():
                self.set_state_preference(state, spec)

        initial = self._resolve_sprite("SnailIdle") or next(iter(self._images.values()), None)
        self.image_id = self.canvas.create_image(self.size[0] // 2, self.size[1] // 2, image=initial)

        self.canvas.bind("<Enter>", lambda _e: self._on_enter())
        self.canvas.bind("<Leave>", lambda _e: self._on_leave())
        self.canvas.bind("<Button-1>", lambda _e: self._on_click())

        self._schedule_next(0)

    # -------------------- Image loading --------------------
    def _load_all_images(self, sprite_paths=None):
        paths = []
        if sprite_paths:
            paths.extend([p for p in sprite_paths if os.path.exists(p)])

        try:
            files = sorted([f for f in os.listdir(self.sp_dir) if f.lower().endswith(".png")])
            for f in files:
                p = os.path.join(self.sp_dir, f)
                if p not in paths:
                    paths.append(p)
        except Exception:
            pass

        for path in paths:
            img = self._load_image(path)
            if img is None:
                continue
            name = os.path.basename(path)
            stem = os.path.splitext(name)[0]
            self._images[name.lower()] = img
            self._images[stem.lower()] = img

    def _load_image(self, path):
        try:
            if not os.path.exists(path):
                return None
            if PIL_AVAILABLE:
                img = Image.open(path).convert("RGBA")
                if img.size != self.size:
                    resampling = getattr(Image, "Resampling", Image)
                    resample = getattr(resampling, "NEAREST", Image.NEAREST)
                    img = img.resize(self.size, resample)
                return ImageTk.PhotoImage(img)
            return tk.PhotoImage(file=path)
        except Exception:
            return None

    def _resolve_sprite(self, key: str):
        if not key:
            return None
        q = key.strip().lower()
        if q in self._images:
            return self._images[q]
        if not q.endswith(".png") and (q + ".png") in self._images:
            return self._images[q + ".png"]
        return None

    # -------------------- Preferences --------------------
    def set_state_preference(self, state: str, spec: Union[SequenceSpec, str]):
        parsed = self._parse_sequence_spec(spec)
        if parsed:
            self.state_preferences[(state or "idle").lower()] = parsed

    def _parse_sequence_spec(self, spec: Union[SequenceSpec, str]) -> SequenceSpec:
        if isinstance(spec, str):
            out: SequenceSpec = []
            chunks = [c.strip() for c in spec.split(",") if c.strip()]
            for chunk in chunks:
                if ":" in chunk:
                    name, secs = chunk.rsplit(":", 1)
                    try:
                        dur = max(0.05, float(secs.strip()))
                    except Exception:
                        dur = 0.5
                    out.append((name.strip(), dur))
                else:
                    out.append((chunk, 0.5))
            return out

        out: SequenceSpec = []
        try:
            for item in spec or []:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    name = str(item[0]).strip()
                    try:
                        dur = max(0.05, float(item[1]))
                    except Exception:
                        dur = 0.5
                    out.append((name, dur))
        except Exception:
            pass
        return out

    # -------------------- Public API --------------------
    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def start(self):
        self.set_state("loading")

    def stop(self):
        self.set_state("idle")

    def set_expression(self, name):
        self.set_state(name)

    def trigger(self, event_or_state: str, hold_ms: Optional[int] = None, force: bool = False):
        key = (event_or_state or "").strip().lower()
        if not key:
            return

        if key in self.EVENT_STATE_MAP:
            state_name, default_ms = self.EVENT_STATE_MAP[key]
            duration = default_ms if hold_ms is None else int(hold_ms)
        else:
            state_name = key
            duration = 1200 if hold_ms is None else int(hold_ms)

        if (not force) and self._manual_state in {"loading", "running"} and state_name not in {"loading", "running"}:
            return

        self._set_transient_state(state_name, duration)

    def set_state(self, state: Optional[str]):
        st = (state or "idle").lower()
        self._manual_state = st
        self._clear_transient_state()
        self._state = st
        self._state_index = 0

    # -------------------- Animation --------------------
    def _effective_state(self) -> str:
        if self._transient_state:
            return self._transient_state
        if self._hovering and self._manual_state not in {"loading", "thinking", "running"}:
            return "listening"
        return self._manual_state or "idle"

    def _current_sequence(self) -> SequenceSpec:
        st = self._effective_state()
        if st != self._state:
            self._state = st
            self._state_index = 0

        seq = self.state_preferences.get(st)
        if seq:
            return seq
        return self.state_preferences.get("idle", [("SnailIdle", 1.0)])

    def _schedule_next(self, delay_ms: int):
        if self._job is not None:
            try:
                self.canvas.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.canvas.after(max(1, int(delay_ms)), self._animate_step)

    def _maybe_mix_sprite(self, state: str, name: str) -> str:
        """Strictly follow the script with zero random mixing."""
        return name

    def _animate_step(self):
        seq = self._current_sequence()
        if not seq:
            seq = [("SnailIdle", 1.0)]

        name, duration_s = seq[self._state_index % len(seq)]
        name = self._maybe_mix_sprite(self._effective_state(), name)
        self._state_index = (self._state_index + 1) % len(seq)

        img = self._resolve_sprite(name) or self._resolve_sprite("SnailIdle") or next(iter(self._images.values()), None)
        if img is not None:
            try:
                self.canvas.itemconfigure(self.image_id, image=img)
            except Exception:
                pass

        self._schedule_next(int(max(0.05, duration_s) * 1000))

    # -------------------- Transient state helpers --------------------
    def _set_transient_state(self, state: str, hold_ms: int):
        self._transient_state = (state or "idle").lower()
        self._state_index = 0

        if self._transient_job is not None:
            try:
                self.canvas.after_cancel(self._transient_job)
            except Exception:
                pass
            self._transient_job = None

        if hold_ms and int(hold_ms) > 0:
            try:
                self._transient_job = self.canvas.after(int(hold_ms), self._clear_transient_state)
            except Exception:
                self._transient_job = None

    def _clear_transient_state(self):
        if self._transient_job is not None:
            try:
                self.canvas.after_cancel(self._transient_job)
            except Exception:
                pass
            self._transient_job = None
        self._transient_state = None
        self._state_index = 0

    # -------------------- Interactions --------------------
    def _on_enter(self):
        self._hovering = True
        self.trigger("hover", hold_ms=700)

    def _on_leave(self):
        self._hovering = False
        self._state_index = 0

    def _on_click(self):
        self.trigger("click", hold_ms=950, force=True)

        if self.on_click_callback:
            try:
                self.on_click_callback()
            except Exception:
                pass

    # compatibility no-ops
    def start_roam(self):
        return

    def stop_roam(self):
        return
