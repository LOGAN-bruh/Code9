import tkinter as tk
import os

class Shinzen:
    """Animated snail sprite controller for Tkinter with roaming support.

    Usage: Shinzen(parent, sprite_paths=[...], frame_duration=180, size=(18,18))
    Methods: start(), stop(), pack(**kwargs), start_roam(widgets, duration_per_widget_ms=3000), stop_roam()
    """

    def __init__(self, parent, sprite_paths=None, frame_duration=180, size=(18, 18)):
        self.parent = parent
        self.size = size
        self.frame_duration = frame_duration
        self.canvas = tk.Canvas(parent, width=size[0], height=size[1], highlightthickness=0, bg=parent["bg"])
        self._job = None
        self.frame_index = 0

        base = os.path.dirname(__file__)
        sp_dir = os.path.join(base, "SnailSprite")

        if sprite_paths is None:
            sprite_paths = [
                os.path.join(sp_dir, "SnailLoading1.png"),
                os.path.join(sp_dir, "SnailLoading2.png"),
                os.path.join(sp_dir, "SnailLoading3.png"),
            ]

        self.frames = []
        for p in sprite_paths:
            try:
                if os.path.exists(p):
                    img = tk.PhotoImage(file=p)
                    self.frames.append(img)
            except Exception:
                pass

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

