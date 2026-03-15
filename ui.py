"""
J.A.R.V.I.S  HUD  —  pywebview-based UI
Provides the same public interface as the original Tkinter UI so that
main.py and every action module keep working without changes.
"""

import os, sys, json, time, threading, base64
from pathlib import Path

import psutil

try:
    import webview
except ImportError:
    print("[UI] pywebview not installed. Run: pip install pywebview")
    sys.exit(1)

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"
WEB_DIR    = BASE_DIR / "web"


# ── JS ↔ Python bridge ──────────────────────────────────────────

class _JarvisAPI:
    """Exposed to JS as ``window.pywebview.api``."""

    def __init__(self, ui: "JarvisUI"):
        self._ui = ui

    # --- JS → Python actions ---
    def toggle_mic(self):
        self._ui.toggle_mic()

    def toggle_video(self):
        self._ui._toggle_video()

    def send_chat(self, text: str):
        if self._ui.chat_callback:
            self._ui.write_log(f"You: {text}")
            self._ui.chat_callback(text)

    def save_api_key(self, key: str):
        self._ui._save_api_key(key)

    def get_metrics(self):
        return {
            "cpu":        self._ui.cpu_pct,
            "mem_pct":    self._ui.mem_pct,
            "mem_used":   self._ui.mem_used,
            "top_procs":  self._ui._top_procs_serial,
            "mic_active": self._ui.mic_active,
            "speaking":   self._ui.speaking,
            "video_active": self._ui.video_active,
        }

    def get_face_base64(self):
        return self._ui._face_b64


# ── Main UI class ────────────────────────────────────────────────

class JarvisUI:
    """Drop-in replacement for the Tkinter JarvisUI.

    Public surface used by main.py / actions:
        write_log, stream_log, set_amplitude, start_speaking,
        stop_speaking, toggle_mic, activate_mic_for, set_chat_callback,
        wait_for_api_key, mic_active, speaking, video_active,
        latest_camera_frame
    """

    def __init__(self, face_path: str = "", size=None):
        self._api = _JarvisAPI(self)
        self._ready = threading.Event()

        # --- state ---
        self.amplitude        = 0.0
        self.speaking         = False
        self.mic_active       = False
        self.mic_timer        = 0
        self.chat_callback    = None
        self.video_active     = False
        self.latest_camera_frame = None

        # --- metrics ---
        self.cpu_pct   = 0.0
        self.mem_pct   = 0.0
        self.mem_used  = 0.0
        self.top_procs = []
        self._top_procs_serial = []

        # --- face GIF as base64 for the web UI (unused, kept for compat) ---
        self._face_b64 = ""

        # --- API key ---
        self._api_key_ready = self._api_keys_exist()

        # --- camera ---
        self._run_cam = False
        self._cam_thread = None

        # --- pywebview window ---
        self._window = webview.create_window(
            "J.A.R.V.I.S",
            url=str(WEB_DIR / "index.html"),
            js_api=self._api,
            width=1200,
            height=850,
            min_size=(900, 600),
            background_color="#0a0304",
            text_select=False,
        )
        self._window.events.loaded += self._on_loaded

        # --- background threads ---
        threading.Thread(target=self._poll_metrics, daemon=True).start()
        threading.Thread(target=self._mic_timer_thread, daemon=True).start()

        # Provide a fake `root` with a `mainloop` so existing code
        # calling ``ui.root.mainloop()`` keeps working.
        class _Root:
            def __init__(self_root, ui_ref):
                self_root._ui = ui_ref
            def mainloop(self_root):
                self_root._ui.mainloop()
        self.root = _Root(self)

    # ── lifecycle ────────────────────────────────────────────

    def mainloop(self):
        """Start the webview event loop (blocks the main thread)."""
        webview.start(debug=False)

    def _on_loaded(self):
        self._ready.set()
        if not self._api_key_ready:
            self._eval_js("showSetupUI()")

    # ── JS evaluation helper ─────────────────────────────────

    def _eval_js(self, code: str):
        if self._window and self._ready.is_set():
            try:
                self._window.evaluate_js(code)
            except Exception:
                pass

    # ── public API (called by main.py / actions) ─────────────

    def write_log(self, text: str):
        self._eval_js(f"writeLog({json.dumps(text)})")

    def stream_log(self, text: str, tag: str = "ai"):
        self._eval_js(f"streamLog({json.dumps(text)}, {json.dumps(tag)})")

    def stream_end(self):
        self._eval_js("streamEnd()")

    def set_amplitude(self, value: float):
        self.amplitude = value
        self._eval_js(f"setAmplitude({value})")

    def start_speaking(self):
        self.speaking = True
        self._eval_js("setSpeaking(true)")

    def stop_speaking(self):
        self.speaking = False
        self._eval_js("setSpeaking(false)")

    def toggle_mic(self):
        self.mic_active = not self.mic_active
        if self.mic_active:
            self.mic_timer = 0
        self._eval_js(f"setMicActive({'true' if self.mic_active else 'false'})")

    def activate_mic_for(self, seconds: float):
        self.mic_active = True
        self.mic_timer = time.time() + seconds
        self._eval_js("setMicActive(true)")

    def set_chat_callback(self, callback):
        self.chat_callback = callback

    # ── API key management ───────────────────────────────────

    def _api_keys_exist(self):
        return API_FILE.exists()

    def wait_for_api_key(self):
        while not self._api_key_ready:
            time.sleep(0.1)

    def _save_api_key(self, key: str):
        if not key:
            return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(API_FILE, "w", encoding="utf-8") as f:
            json.dump({"gemini_api_key": key}, f)
        self._api_key_ready = True
        self.write_log("SYS: Systems initialised.")

    # ── face GIF ─────────────────────────────────────────────

    def _load_face_b64(self, path: str):
        try:
            if not os.path.isabs(path):
                path = os.path.join(BASE_DIR, path)
            with open(path, "rb") as f:
                self._face_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            print(f"[UI] Failed to load face: {e}")
            self._face_b64 = ""

    # ── metrics polling ──────────────────────────────────────

    def _poll_metrics(self):
        while True:
            try:
                self.cpu_pct = psutil.cpu_percent()
                mem = psutil.virtual_memory()
                self.mem_pct = mem.percent
                self.mem_used = mem.used / (1024 ** 3)

                procs = []
                for p in sorted(
                    psutil.process_iter(["name", "cpu_percent", "memory_percent"]),
                    key=lambda k: k.info.get("cpu_percent", 0) or 0,
                    reverse=True,
                ):
                    if p.info["name"] and p.info["name"].lower() not in (
                        "system idle process", "system",
                    ):
                        procs.append({
                            "name": (p.info["name"] or "unknown")[:18],
                            "cpu_percent": p.info.get("cpu_percent", 0) or 0,
                            "memory_percent": p.info.get("memory_percent", 0) or 0,
                        })
                    if len(procs) >= 5:
                        break
                self.top_procs = procs
                self._top_procs_serial = procs
            except Exception:
                pass
            time.sleep(1.5)

    # ── mic auto-deactivation timer ──────────────────────────

    def _mic_timer_thread(self):
        while True:
            if self.mic_timer > 0 and time.time() > self.mic_timer:
                self.mic_timer = 0
                self.mic_active = False
                self._eval_js("setMicActive(false)")
            time.sleep(0.2)

    # ── camera ───────────────────────────────────────────────

    def _toggle_video(self):
        if not HAS_CV2:
            self.write_log("SYS: OpenCV not found. Camera unavailable.")
            return

        self.video_active = not self.video_active
        if self.video_active:
            self._run_cam = True
            self._cam_thread = threading.Thread(target=self._camera_worker, daemon=True)
            self._cam_thread.start()
        else:
            self._run_cam = False
            self._eval_js("updateCameraFrame(null)")

    def _camera_worker(self):
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(0)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            subtractor = cv2.createBackgroundSubtractorMOG2(history=100, varThreshold=25)
            font = cv2.FONT_HERSHEY_SIMPLEX

            while self._run_cam:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.02)
                    continue

                # Motion detection HUD overlay
                fgmask = subtractor.apply(frame)
                contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for c in contours:
                    if cv2.contourArea(c) > 300:
                        x, y, w, h = cv2.boundingRect(c)
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 242, 255), 2)
                        cv2.putText(frame, "TARGET ACQUIRED", (x, max(15, y - 8)),
                                    font, 0.45, (0, 242, 255), 1, cv2.LINE_AA)
                        cv2.line(frame, (x, y), (x + 10, y), (0, 255, 136), 2)
                        cv2.line(frame, (x, y), (x, y + 10), (0, 255, 136), 2)

                # Store RGB frame for screen_processor
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self.latest_camera_frame = rgb.copy()

                # Encode to JPEG base64 and push to JS
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                b64 = base64.b64encode(buf).decode("utf-8")
                self._eval_js(f"updateCameraFrame('{b64}')")

                time.sleep(0.06)  # ~15 fps

        except Exception as e:
            print(f"[UI] Camera thread error: {e}")
            import traceback; traceback.print_exc()
        finally:
            try:
                cap.release()
            except Exception:
                pass

    # ── cleanup ──────────────────────────────────────────────

    def _close_app(self):
        self._run_cam = False
        os._exit(0)
