import os
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
        "idle": [("SnailIdle", 8), ("SnailBlinking", 0.12)],
        "loading": [
            ("SnailLoading1", 0.24),
            ("SnailLoading2", 0.24),
            ("SnailLoading3", 0.24),
            ("SnailSubtleSupprised", 0.24),
        ],
        "running": [
            ("SnailLoading1", 0.30),
            ("SnailLoading2", 0.30),
            ("SnailLoading3", 0.30),
        ],
        "thinking": [
            ("SnailLoading1", 0.26),
            ("SnailLoading2", 0.26),
            ("SnailLoading3", 0.26),
            ("SnailPeering", 0.32),
        ],
        "typing": [("SnailPeering", 3), ("SnailBlinking", 0.14), ("SnailPeering", 3)],
        "listening": [("SnailPeering", 0.72), ("SnailBlinking", 0.22)],
        "peering": [("SnailPeering", 1.05), ("SnailBlinking", 0.26)],
        "idea": [("SnailYawn2:JawDroppedSupprised", 0.56), ("SnailChill:Yawn1", 0.58), ("SnailIdle", 0.80)],
        "explain": [("SnailPeering", 0.66), ("SnailYawn2:JawDroppedSupprised", 0.52), ("SnailIdle", 0.72)],
        "happy": [("SnailWink", 0.58), ("SnailIdle", 0.95), ("SnailBlinking", 0.30)],
        "celebrate": [("SnailWink", 0.52), ("SnailSubtleSupprised", 0.56), ("SnailIdle", 0.80)],
        "wink": [("SnailWink", 0.72), ("SnailIdle", 0.95)],
        "concern": [("SnailShySad", 0.86), ("SnailRetracted", 0.72), ("SnailIdle", 0.86)],
        "alert": [("SnailRetracted", 0.60), ("SnailSubtleSupprised", 0.58), ("SnailPeering", 0.66)],
        "surprised": [("SnailSubtleSupprised", 0.74), ("SnailIdle", 0.90)],
        "sleepy": [("SnailChill:Yawn1", 0.78), ("SnailBlinking", 0.28), ("SnailIdle", 1.10)],
    }

    EVENT_STATE_MAP: Dict[str, Tuple[str, int]] = {
        "hover": ("listening", 900),
        "click": ("wink", 950),
        "typing": ("typing", 900),
        "suggestion": ("explain", 1800),
        "success": ("celebrate", 1700),
        "error": ("alert", 1900),
        "idle": ("sleepy", 2200),
        "idea": ("idea", 1800),
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
                    img = img.resize(self.size, Image.NEAREST)
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

    def _animate_step(self):
        seq = self._current_sequence()
        if not seq:
            seq = [("SnailIdle", 1.0)]

        name, duration_s = seq[self._state_index % len(seq)]
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

        def _try(path):
            try:
                return tk.PhotoImage(file=path) if os.path.exists(path) else None
            except Exception:
                return None

        self.idle_image = _try(os.path.join(sp_dir, "SnailIdle.png"))
        self.peering_image = _try(os.path.join(sp_dir, "SnailPeering.png"))
        self.wink_image = _try(os.path.join(sp_dir, "SnailWink.png"))

        self._all_images = list(self.frames)
        for x in (self.idle_image, self.peering_image, self.wink_image):
            if x is not None:
                self._all_images.append(x)

        initial = self.frames[0] if self.frames else self.idle_image
        self.image_id = self.canvas.create_image(size[0] // 2, size[1] // 2, image=initial)

        # Interaction bindings
        self.canvas.bind("<Enter>", lambda e: self._on_enter())
        self.canvas.bind("<Leave>", lambda e: self._on_leave())
        self.canvas.bind("<Button-1>", lambda e: self._on_click())

        self._hovering = False
        self._running = False

        # Roaming state
        self._roam_job = None
        self._roam_targets = []
        self._roam_index = 0
        self._roam_step = 8
        self._roam_x = 0

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def start(self):
        """Begin animating the loading frames."""
        if not self.frames:
            return
        self._running = True
        self._animate()

    def _animate(self):
        if not self._running:
            return
        try:
            frame = self.frames[self.frame_index % len(self.frames)]
            self.canvas.itemconfigure(self.image_id, image=frame)
            self.frame_index = (self.frame_index + 1) % len(self.frames)
        except Exception:
            pass
        self._job = self.canvas.after(self.frame_duration, self._animate)

    def stop(self):
        """Stop animation and show idle image if available."""
        self._running = False
        if self._job:
            try:
                self.canvas.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        if self.idle_image is not None:
            try:
                self.canvas.itemconfigure(self.image_id, image=self.idle_image)
            except Exception:
                pass

    def _on_enter(self):
        self._hovering = True
        if self.peering_image is not None:
            try:
                self.canvas.itemconfigure(self.image_id, image=self.peering_image)
            except Exception:
                pass

    def _on_leave(self):
        self._hovering = False
        if not self._running and self.idle_image is not None:
            try:
                self.canvas.itemconfigure(self.image_id, image=self.idle_image)
            except Exception:
                pass

    def _on_click(self):
        # clickable reaction
        if self.wink_image is not None:
            try:
                self.canvas.itemconfigure(self.image_id, image=self.wink_image)
                self.canvas.after(650, lambda: self._restore_after_interaction())
            except Exception:
                pass
        else:
            orig = self.frame_duration
            self.frame_duration = max(50, int(self.frame_duration / 3))
            self.canvas.after(600, lambda: setattr(self, 'frame_duration', orig))

    def _restore_after_interaction(self):
        if self._running and self.frames:
            return
        if self._hovering and self.peering_image is not None:
            try:
                self.canvas.itemconfigure(self.image_id, image=self.peering_image)
            except Exception:
                pass
        elif self.idle_image is not None:
            try:
                self.canvas.itemconfigure(self.image_id, image=self.idle_image)
            except Exception:
                pass

    def set_expression(self, name):
        mapping = {
            'idle': self.idle_image,
            'peering': self.peering_image,
            'wink': self.wink_image,
        }
        img = mapping.get(name)
        if img is not None:
            try:
                self.canvas.itemconfigure(self.image_id, image=img)
            except Exception:
                pass

    # ---------------- Roaming API ----------------
    def start_roam(self, widgets, duration_per_widget_ms=3000, step_ms=25):
        """Start roaming across a list of widgets (placed over the widget and moving left->right)."""
        try:
            if not widgets:
                return
            self.stop_roam()
            self._roam_targets = list(widgets)
            self._roam_index = 0
            self._roam_step = max(1, int((step_ms / 25) * 8))
            # begin roaming sequence
            self._start_roam_target(duration_per_widget_ms, step_ms)
        except Exception:
            pass

    def _start_roam_target(self, duration_per_widget_ms, step_ms):
        try:
            if not self._roam_targets:
                return
            target = self._roam_targets[self._roam_index % len(self._roam_targets)]

            # ensure widget has size
            w = target.winfo_width()
            if w <= 10:
                # try again after a short delay
                self._roam_job = self.canvas.after(120, lambda: self._start_roam_target(duration_per_widget_ms, step_ms))
                return

            start_x = -self.size[0]
            end_x = w
            self._roam_x = start_x

            # place canvas above the widget (slightly offset)
            try:
                self.canvas.place(in_=target, x=self._roam_x, y=-int(self.size[1] * 0.6))
            except Exception:
                self.canvas.place(x=0, y=0)

            # compute pixels per tick
            steps = max(1, int(duration_per_widget_ms / step_ms))
            total_distance = end_x - start_x + self.size[0]
            px_per_step = max(1, int(total_distance / steps))
            self._roam_px = px_per_step

            # animate across
            def step():
                try:
                    self._roam_x += self._roam_px
                    self.canvas.place_configure(x=self._roam_x)
                    if self._roam_x < end_x:
                        self._roam_job = self.canvas.after(step_ms, step)
                    else:
                        # finished this widget: pause briefly then move to next
                        self._roam_index = (self._roam_index + 1) % len(self._roam_targets)
                        self._roam_job = self.canvas.after(300, lambda: self._start_roam_target(duration_per_widget_ms, step_ms))
                except Exception:
                    pass

            step()
        except Exception:
            pass

    def stop_roam(self):
        try:
            if self._roam_job:
                try:
                    self.canvas.after_cancel(self._roam_job)
                except Exception:
                    pass
                self._roam_job = None
            try:
                self.canvas.place_forget()
            except Exception:
                pass
        except Exception:
            pass

