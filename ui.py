import os, json, time, math, random, threading
import tkinter as tk
from collections import deque
from PIL import Image, ImageTk, ImageDraw, ImageSequence
import sys
from pathlib import Path
import psutil

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

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = "17.0"

C_BG     = "#010e14" # Dashboard dark base
C_PRI    = "#00f2ff" # Cyan accent
C_MID    = "#007a99"
C_DIM    = "#004052"
C_GLOW   = "#0048af"
C_ACC    = "#1c8b8b"
C_ACC2   = "#ffcc00"
C_TEXT   = "#dbfdfd"
C_PANEL  = "#04151f" # Slightly lighter than BG
C_GREEN  = "#00ff88"
C_RED    = "#ff3333"

class JarvisUI:
    def __init__(self, face_path, size=None):
        self.root = tk.Tk()
        self.root.title(SYSTEM_NAME)
        self.root.attributes("-transparentcolor", "#000003")
        
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.W  = min(sw, 1200)
        self.H  = min(sh, 850)
        self.root.geometry(f"{self.W}x{self.H}+{(sw-self.W)//2}+{(sh-self.H)//2}")
        self.root.configure(bg=C_BG)
        
        # Metrics state
        self.cpu_pct = 0.0
        self.mem_pct = 0.0
        self.mem_used = 0.0
        self.top_procs = []
        
        # Animations & Data
        self.amplitude = 0.0
        self.bg_scroll = 0.0
        self.scan_pos = -200
        self.tick = 0
        self.stars = []
        for _ in range(60):
            self.stars.append({
                "x": random.randint(0, 1000), "y": random.randint(0, 1000),
                "s": random.uniform(0.5, 1.5), "sz": random.uniform(1, 2)
            })

        self.speaking     = False
        self.scale        = 1.0
        self.target_scale = 1.0
        self.halo_a       = 60.0
        self.target_halo  = 60.0
        self.last_t       = time.time()
        self.pulse_r      = [0.0, 100, 200]
        self.status_text  = "ONLINE"
        self.status_blink = True
        
        # Grain Physics
        self.grains = []
        for _ in range(120):
            self.grains.append({"angle": random.uniform(0, 2*math.pi), "vx": 0, "vy": 0})

        self.typing_queue    = deque()
        self.is_typing       = False
        self.chat_callback   = None

        # Face configuration
        self.FACE_SZ = 320
        self._face_pil         = None
        self._has_face         = False
        self._face_frames      = []
        self._tk_frames        = []
        self._frame_idx        = 0
        self._face_scale_cache = None
        self._load_face(face_path)

        # Main Canvas layout
        self.bg = tk.Canvas(self.root, width=self.W, height=self.H, bg=C_BG, highlightthickness=0)
        self.bg.pack(fill="both", expand=True)

        # Dynamic layout vars
        self.L_W = 320
        self.R_W = 340
        self.MARGIN = 20
        self.GAP = 15
        self.FCX = self.W // 2
        self.FCY = self.H // 2

        self.root.bind("<Configure>", self._on_resize)
        
        # Transcript Widgets (Right Panel)
        self.log_frame = tk.Frame(self.root, bg=C_PANEL, highlightthickness=0)
        self.log_text = tk.Text(self.log_frame, fg=C_TEXT, bg="#020a0f",
                                insertbackground=C_TEXT, borderwidth=0, selectbackground=C_MID,
                                wrap="word", font=("Courier", 10), padx=10, pady=10)
        
        # Enhanced Chat Input Box
        self.chat_bg_frame = tk.Frame(self.log_frame, bg="#021c26", bd=0, highlightthickness=1, highlightbackground=C_DIM)
        self.chat_bg_frame.pack(side="bottom", fill="x", padx=10, pady=10)
        
        self.prompt_label = tk.Label(self.chat_bg_frame, text=" ❯ ", fg="#00ffcc", bg="#021c26", font=("Courier", 12, "bold"))
        self.prompt_label.pack(side="left", padx=(5,0))
        
        self.placeholder = "Enter command..."
        self.chat_entry = tk.Entry(self.chat_bg_frame, fg=C_DIM, bg="#021c26", 
                                   insertbackground="#00ff88", borderwidth=0, relief="flat",
                                   font=("Courier", 11, "bold"))
        self.chat_entry.insert(0, self.placeholder)
        self.chat_entry.pack(side="left", fill="both", expand=True, padx=5, pady=8)
        
        self.chat_entry.bind("<Return>", self._handle_chat_event)
        self.chat_entry.bind("<FocusIn>", self._clear_placeholder)
        self.chat_entry.bind("<FocusOut>", self._restore_placeholder)

        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        
        # Tags for Transcript styling
        self.log_text.tag_config("you", foreground="#00ffcc", font=("Courier", 10, "bold"), spacing1=8, spacing3=8)
        self.log_text.tag_config("ai",  foreground="#ffffff", font=("Courier", 10), spacing3=8)
        self.log_text.tag_config("sys", foreground=C_ACC2, font=("Courier", 9, "italic"), spacing3=8)

        # Video Widgets (Left Panel)
        self.video_active = False
        self.video_label = tk.Label(self.root, bg="#000000", text="VIDEO FEED OFFLINE", fg=C_DIM, font=("Courier", 12))
        self.mic_active = False
        self.mic_timer = 0

        self._run_cam = False
        self._cam_thread = None
        self.latest_camera_frame = None

        self._api_key_ready = self._api_keys_exist()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._last_stream_tag = ""
        self._type_after_id = None
        
        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", self._close_app)

    def _toggle_video(self):
        if not HAS_CV2:
            self.write_log("SYS: OpenCV not found. Please install opencv-python.")
            return

        self.video_active = not self.video_active
        if self.video_active:
            self._run_cam = True
            self.video_label.configure(text="")
            self._cam_thread = threading.Thread(target=self._camera_worker, daemon=True)
            self._cam_thread.start()
        else:
            self._run_cam = False
            self.video_label.configure(image="", text="VIDEO FEED OFFLINE")
            self.video_label.imgtk = None
            
    def toggle_mic(self):
        self.mic_active = not self.mic_active
        if self.mic_active:
            self.mic_timer = 0 # stays on until toggled

    def activate_mic_for(self, seconds: float):
        self.mic_active = True
        self.mic_timer = time.time() + seconds

    def _camera_worker(self):
        try:
            # Use DirectShow on Windows for zero lag/buffering
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
                
            # Keep resolution manageable for fast background subtraction
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) # Only keep the newest frame

            subtractor = cv2.createBackgroundSubtractorMOG2(history=100, varThreshold=25)
            font = cv2.FONT_HERSHEY_SIMPLEX
            
            while self._run_cam:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue
                
                # Fast generic object/motion detection for "Smart Vision" effect
                fgmask = subtractor.apply(frame)
                contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for c in contours:
                    if cv2.contourArea(c) > 300:
                        x, y, w, h = cv2.boundingRect(c)
                        # Draw futuristic bounding boxes
                        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 242, 255), 2)
                        cv2.putText(frame, "TARGET ACQUIRED", (x, max(15, y-8)), font, 0.45, (0, 242, 255), 1, cv2.LINE_AA)
                        
                        # Corner crosshairs
                        cv2.line(frame, (x, y), (x+10, y), (0, 255, 136), 2)
                        cv2.line(frame, (x, y), (x, y+10), (0, 255, 136), 2)

                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self.latest_camera_frame = frame.copy()
                
                # Resize dynamically based on current frame width
                if hasattr(self, 'v_w') and self.v_w > 10:
                    try:
                        frame = cv2.resize(frame, (int(self.v_w), int(self.v_h)))
                        img = Image.fromarray(frame)
                        self.root.after(0, self._update_video_label, img)
                    except: pass
                
                time.sleep(0.01)
        except Exception as e:
            print("[UI] Camera thread error: ", e)
            import traceback; traceback.print_exc()
        finally:
            cap.release()

    def _update_video_label(self, img):
        if not self._run_cam: return
        try:
            imgtk = ImageTk.PhotoImage(image=img)
            if self.video_label.winfo_exists():
                self.video_label.imgtk = imgtk 
                self.video_label.configure(image=imgtk)
        except: pass

    def set_amplitude(self, value):
        self.amplitude = value

    def _load_face(self, path):
        FW = self.FACE_SZ
        try:
            if not os.path.isabs(path):
                path = os.path.join(BASE_DIR, path)
            img = Image.open(path)
            self._face_frames = []
            
            mask = Image.new("L", (FW * 2, FW * 2), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((4, 4, FW * 2 - 4, FW * 2 - 4), fill=255)
            mask = mask.resize((FW, FW), Image.LANCZOS)
            
            from PIL import ImageFilter
            for frame in ImageSequence.Iterator(img):
                f = frame.convert("RGBA").resize((FW, FW), Image.LANCZOS)
                r, g, b, a = f.split()
                clean_rgb = Image.merge("RGB", (r, g, b)).filter(ImageFilter.MedianFilter(size=3))
                clean_rgb = clean_rgb.filter(ImageFilter.SMOOTH_MORE)
                clean_a = a.point(lambda x: 0 if x < 140 else 255)
                
                final_a = Image.new("L", (FW, FW), 0)
                inner_mask = Image.new("L", (FW, FW), 0)
                idraw = ImageDraw.Draw(inner_mask)
                idraw.ellipse((6, 6, FW-6, FW-6), fill=255)
                final_a.paste(inner_mask, (0, 0), mask=clean_a)
                
                f = clean_rgb.convert("RGBA")
                f.putalpha(final_a)
                self._face_frames.append(f)
            
            self._has_face = len(self._face_frames) > 0
            self._frame_idx = 0
        except Exception as e:
            print(f"[UI] [!] Failed to load face: {e}")
            self._has_face = False

    @staticmethod
    def _ac(r, g, b, a):
        f = a / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    def _rounded_rect(self, canvas, x, y, w, h, r, **kwargs):
        points = [
            x+r, y, x+w-r, y, x+w, y, x+w, y+r, x+w, y+h-r, x+w, y+h,
            x+w-r, y+h, x+r, y+h, x, y+h, x, y+h-r, x, y+r, x, y
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        if now - self.last_t > (0.14 if self.speaking else 0.55):
            self.target_scale = random.uniform(1.05, 1.11) if self.speaking else random.uniform(1.001, 1.007)
            self.last_t = now

        if self.mic_timer > 0 and time.time() > self.mic_timer:
            self.mic_timer = 0
            self.mic_active = False

        sp = 0.35 if self.speaking else 0.16
        self.scale  += (self.target_scale - self.scale) * sp

        if self._has_face:
            self._frame_idx = (self._frame_idx + 1) % len(self._face_frames)

        # Pulse rings
        pspd  = 3.8 if self.speaking else 1.8
        limit = self.FACE_SZ * 0.75
        new_p = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(new_p) < 3 and random.random() < (0.06 if self.speaking else 0.022):
            new_p.append(0.0)
        self.pulse_r = new_p

        if t % 40 == 0:
            self.status_blink = not self.status_blink

        # BG Scroll & Stars
        bg_speed = 0.4 + self.amplitude * 5.0
        self.bg_scroll = (self.bg_scroll + bg_speed) % 100
        for star in self.stars:
            star["y"] = (star["y"] + star["s"] * (1.0 + self.amplitude * 3.0)) % 1000

        # Hardware Metrics
        if t % 30 == 0:
            self.cpu_pct = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            self.mem_pct = mem.percent
            self.mem_used = mem.used / (1024**3)
            
            procs = []
            for p in sorted(psutil.process_iter(['name', 'cpu_percent', 'memory_percent']), key=lambda k: k.info.get('cpu_percent', 0) or 0, reverse=True):
                if p.info['name'] and p.info['name'].lower() not in ('system idle process', 'system'):
                    procs.append(p.info)
                if len(procs) >= 4:
                    break
            self.top_procs = procs

        self._draw_reactive_circle()
        self._draw()
        self.root.after(16, self._animate)

    def _draw_reactive_circle(self):
        self._dots_data = []
        base_r = self.FACE_SZ * 0.52
        gravity = 0.12
        friction = 0.94
        for g in self.grains:
            target_r = base_r * self.scale
            bx = self.FCX + target_r * math.cos(g["angle"])
            by = self.FCY + target_r * math.sin(g["angle"])
            
            if self.amplitude > 0.15:
                force = self.amplitude * 12.0
                g["vx"] += math.cos(g["angle"]) * force * random.uniform(0.5, 1.5)
                g["vy"] += math.sin(g["angle"]) * force * random.uniform(0.5, 1.5)
                g["vy"] += gravity * (1.0 + self.amplitude * 15.0)
            
            g["vx"] *= friction
            g["vy"] *= friction
            g["vy"] += gravity
            
            x = bx + g["vx"]
            y = by + g["vy"]
            
            if self.amplitude < 0.05:
                 g["vx"] *= 0.5; g["vy"] *= 0.5
            
            size = 1.0 + self.amplitude * 5.0
            alpha = int(120 + self.amplitude * 135)
            col = self._ac(0, 242, 255, max(10, alpha))
            self._dots_data.append((x, y, size, col))

    def _draw(self):
        c = self.bg
        W, H = self.W, self.H
        c.delete("all")

        M = self.MARGIN
        G = self.GAP
        LW = self.L_W
        RW = self.R_W

        c.create_rectangle(0, 0, W, H, fill=C_BG, width=0)

        # Background grid simulation
        for i in range(12):
            y_base = (i * 25 + self.bg_scroll) % H
            c.create_line(0, y_base, W, y_base, fill=self._ac(0, 51, 68, 30), width=1)

        # -- TOP BAR --
        TY = 40
        c.create_rectangle(0, 0, W, TY, fill="#040c11", outline="")
        tabs = ["DASHBOARD", "CONTACTS", "NOTES", "CONNECT", "PHONE"]
        tx = 20
        for idx, tab in enumerate(tabs):
            fg = C_PRI if idx == 0 else C_DIM
            c.create_text(tx, TY//2, text=tab, fill=fg, font=("Courier", 10, "bold"), anchor="w")
            tx += len(tab)*10 + 25

        c.create_oval(W-250, TY//2-4, W-242, TY//2+4, fill="#00ff88", outline="")
        c.create_text(W-235, TY//2, text="ONLINE", fill="#00ff88", font=("Courier", 10, "bold"), anchor="w")
        
        # Mic Switch Top Bar Removed
        
        c.create_text(W-50, TY//2, text="SYSTEM READY", fill=C_MID, font=("Courier", 9, "bold"), anchor="e")

        # -- LEFT PANELS --
        PANEL_BG = "#06131c"
        # 1. VISUAL INPUT
        vh_px = 250
        v_y = TY + M
        self._rounded_rect(c, M, v_y, LW, vh_px, 20, fill=PANEL_BG, outline=C_DIM)
        c.create_text(M+15, v_y+15, text="[O] VISUAL INPUT", fill=C_PRI, font=("Courier", 10, "bold"), anchor="w")
        
        # Cam Switch Top Right of Panel
        c_col = C_PRI if self.video_active else C_DIM
        self._rounded_rect(c, M+LW-55, v_y+5, 40, 20, 10, fill=c_col, outline="", tags="btn_cam")
        c.create_text(M+LW-35, v_y+15, text="CAM", fill=C_BG if self.video_active else C_TEXT, font=("Courier", 8, "bold"), tags="btn_cam")
        c.tag_bind("btn_cam", "<Button-1>", lambda e: self._toggle_video())
        
        # Geometry for Video feed inside Visual Input panel
        vfx, vfy = M+10, v_y+35
        vfw, vfh = LW-20, vh_px-45
        self.v_w, self.v_h = vfw, vfh
        
        if not hasattr(self, "_vid_placed"):
            self.video_label.place(x=vfx, y=vfy, width=vfw, height=vfh)
            self._vid_placed = True

        # 2. SYSTEM METRICS
        mh_px = 160
        m_y = v_y + vh_px + G
        self._rounded_rect(c, M, m_y, LW, mh_px, 20, fill=PANEL_BG, outline=C_DIM)
        c.create_text(M+15, m_y+15, text="[::] SYSTEM METRICS", fill=C_PRI, font=("Courier", 10, "bold"), anchor="w")
        c.create_text(M+LW-15, m_y+15, text="ONLINE", fill="#00ff88", font=("Courier", 8, "bold"), anchor="e")
        
        # CPU Graphic
        c.create_text(M+15, m_y+50, text="CPU LOAD", fill=C_TEXT, font=("Courier", 9), anchor="w")
        c.create_text(M+LW-15, m_y+50, text=f"{self.cpu_pct}%", fill=C_PRI, font=("Courier", 12, "bold"), anchor="e")
        pb_w = LW - 30
        c.create_rectangle(M+15, m_y+65, M+15+pb_w, m_y+72, fill="#001a1a", outline="")
        c.create_rectangle(M+15, m_y+65, M+15+(pb_w*self.cpu_pct/100), m_y+72, fill=C_PRI, outline="")

        # RAM Graphic
        c.create_text(M+15, m_y+95, text="RAM USAGE", fill=C_TEXT, font=("Courier", 9), anchor="w")
        c.create_text(M+LW-15, m_y+95, text=f"{self.mem_pct}% ({self.mem_used:.1f} GB)", fill="#00ff88", font=("Courier", 12, "bold"), anchor="e")
        c.create_rectangle(M+15, m_y+110, M+15+pb_w, m_y+117, fill="#001a1a", outline="")
        c.create_rectangle(M+15, m_y+110, M+15+(pb_w*self.mem_pct/100), m_y+117, fill="#00ff88", outline="")

        # 3. TOP PROCESSES
        ph_px = H - m_y - mh_px - M
        p_y = m_y + mh_px + G
        self._rounded_rect(c, M, p_y, LW, ph_px, 20, fill=PANEL_BG, outline=C_DIM)
        c.create_text(M+15, p_y+15, text="[*] TOP PROCESSES", fill=C_PRI, font=("Courier", 10, "bold"), anchor="w")
        
        c.create_text(M+15, p_y+40, text="APP NAME", fill=C_DIM, font=("Courier", 8), anchor="w")
        c.create_text(M+LW-60, p_y+40, text="CPU", fill=C_DIM, font=("Courier", 8), anchor="e")
        c.create_text(M+LW-15, p_y+40, text="MEM", fill=C_DIM, font=("Courier", 8), anchor="e")
        
        py_off = p_y + 60
        for pr in self.top_procs:
            n = (pr['name'] or 'unknown')[:15]
            cpu = f"{pr.get('cpu_percent', 0.0):.1f}%"
            mem = f"{pr.get('memory_percent', 0.0):.1f}%"
            c.create_text(M+15, py_off, text=n, fill=C_TEXT, font=("Courier", 9), anchor="w")
            c.create_text(M+LW-60, py_off, text=cpu, fill=C_PRI, font=("Courier", 9), anchor="e")
            c.create_text(M+LW-15, py_off, text=mem, fill=C_TEXT, font=("Courier", 9), anchor="e")
            py_off += 25

        # -- RIGHT PANEL (TRANSCRIPT) --
        r_x = W - RW - M
        r_y = TY + M
        r_h = H - TY - M*2
        self._rounded_rect(c, r_x, r_y, RW, r_h, 20, fill=PANEL_BG, outline=C_DIM)
        c.create_text(r_x+15, r_y+15, text="[T] TRANSCRIPT", fill=C_PRI, font=("Courier", 10, "bold"), anchor="w")

        if not hasattr(self, "_log_placed"):
            self.log_frame.place(x=r_x+5, y=r_y+35, width=RW-10, height=r_h-45)
            self._log_placed = True

        # -- CENTER PANEL (CORE SYSTEM) --
        cx = M + LW + G
        cy = TY + M
        cw = W - LW - RW - M*2 - G*2
        ch = H - TY - M*2
        self._rounded_rect(c, cx, cy, cw, ch, 20, fill=PANEL_BG, outline=C_DIM)
        c.create_text(cx+15, cy+15, text="[O] CORE SYSTEM", fill=C_PRI, font=("Courier", 10, "bold"), anchor="w")
        c.create_text(cx+cw-15, cy+15, text="FREQ: 16-24KHZ", fill=C_GREEN, font=("Courier", 9, "bold"), anchor="e")

        self.FCX = cx + cw // 2
        self.FCY = cy + ch // 2 - 20 # slightly above center to accommodate buttons

        for star in self.stars:
            sx = cx + int(star["x"] * cw / 1000)
            sy = cy + int(star["y"] * ch / 1000)
            alpha = int(80 + self.amplitude * 175)
            c.create_oval(sx, sy, sx+star["sz"], sy+star["sz"], fill=self._ac(0, 242, 255, alpha), outline="")

        if hasattr(self, "_dots_data"):
            for dx, dy, ds, col in self._dots_data:
                c.create_oval(dx-ds, dy-ds, dx+ds, dy+ds, fill=col, outline="")

        if self._has_face:
            fw = int(self.FACE_SZ * self.scale)
            if (self._face_scale_cache is None or abs(self._face_scale_cache[0] - self.scale) > 0.005 or self._face_scale_cache[1] != self._frame_idx):
                pil_frame = self._face_frames[self._frame_idx]
                if abs(self.scale - 1.0) > 0.01:
                    scaled = pil_frame.resize((fw, fw), Image.BILINEAR)
                else:
                    scaled = pil_frame
                tk_img = ImageTk.PhotoImage(scaled)
                self._face_scale_cache = (self.scale, self._frame_idx, tk_img)
            
            c.create_image(self.FCX, self.FCY, image=self._face_scale_cache[2])

        # Status text under GIF
        if self.speaking:
            status_txt = "['] SPEECH OUTPUT ACTIVE"
            s_col = C_PRI
        elif self.mic_active:
            status_txt = "[(•)] LISTENING / RECORDING"
            s_col = C_GREEN
        else:
            status_txt = "[-] STANDBY / READY"
            s_col = C_DIM
        c.create_text(self.FCX, self.FCY + int(self.FACE_SZ/2) + 20, text=status_txt, fill=s_col, font=("Courier", 10, "bold"))

        # Bottom Buttons in Core System
        btn_y = cy + ch - 50
        
        # Main Mic Button (Centered)
        mx = self.FCX
        nm_col = "#002b26" if self.mic_active else C_BG
        m_out  = C_GREEN if self.mic_active else C_DIM
        c.create_rectangle(mx-55, btn_y, mx+55, btn_y+35, fill=nm_col, outline=m_out, width=1, tags="btn_main_mic")
        c.create_text(mx, btn_y+17, text="[=] MIC ON" if self.mic_active else "[-] MIC OFF", fill=C_GREEN if self.mic_active else C_DIM, font=("Courier", 10, "bold"), tags="btn_main_mic")
        c.tag_bind("btn_main_mic", "<Button-1>", lambda e: self.toggle_mic())

    def _on_resize(self, event):
        if event.widget == self.root:
            if event.width != self.W or event.height != self.H:
                self.W, self.H = event.width, event.height
                
                L_W = int(self.W * 0.26)
                self.L_W = max(280, min(360, L_W))
                
                R_W = int(self.W * 0.3)
                self.R_W = max(300, min(420, R_W))

                cw = self.W - self.L_W - self.R_W - self.MARGIN*2 - self.GAP*2
                if cw < 300:
                    self.FACE_SZ = min(cw - 20, 320)
                else:
                    self.FACE_SZ = 320

                # Force re-place widgets on resize
                M, G = self.MARGIN, self.GAP
                TY = 40
                vh_px = 250
                v_y = TY + M
                self.video_label.place(x=M+10, y=v_y+35, width=self.L_W-20, height=vh_px-45)
                
                r_x = self.W - self.R_W - M
                r_y = TY + M
                r_h = self.H - TY - M*2
                self.log_frame.place(x=r_x+5, y=r_y+35, width=self.R_W-10, height=r_h-45)

    def write_log(self, text: str):
        self.typing_queue.append(text)
        if not self.is_typing:
            self._start_typing()

    def stream_log(self, text: str, tag: str = "ai"):
        self.log_text.configure(state="normal")
        if self.is_typing:
            self._finish_typing()
        
        last_char = self.log_text.get("end-2c", "end-1c")
        if self._last_stream_tag != tag and last_char != "\n" and last_char != "":
            self.log_text.insert(tk.END, "\n")
            
        self.log_text.insert(tk.END, text, tag)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
        self._last_stream_tag = tag

    def _finish_typing(self):
        if self._type_after_id:
            try: self.root.after_cancel(self._type_after_id)
            except: pass
            self._type_after_id = None
        
        while self.typing_queue:
            text = self.typing_queue.popleft()
            tl = text.lower()
            tag = "you" if tl.startswith("you:") else "ai" if tl.startswith("ai:") else "sys"
            self.log_text.insert(tk.END, text + "\n", tag)
            self._last_stream_tag = tag

        self.is_typing = False
        self.log_text.configure(state="disabled")

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        tag  = "you" if tl.startswith("you:") else "ai" if tl.startswith("ai:") else "sys"
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self._type_after_id = self.root.after(5, self._type_char, text, i + 1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self._last_stream_tag = tag
            self.log_text.configure(state="disabled")
            self._type_after_id = self.root.after(25, self._start_typing)

    def set_chat_callback(self, callback):
        self.chat_callback = callback

    def _handle_chat_event(self, event):
        text = self.chat_entry.get().strip()
        if not text or text == self.placeholder: return
        self.chat_entry.delete(0, tk.END)
        self.write_log(f"You: {text}")
        if self.chat_callback: self.chat_callback(text)

    def _clear_placeholder(self, event):
        if self.chat_entry.get() == self.placeholder:
            self.chat_entry.delete(0, tk.END)
            self.chat_entry.configure(fg=C_PRI)
        # Apply glow effect on focus
        if hasattr(self, 'chat_bg_frame'):
            self.chat_bg_frame.configure(highlightbackground=C_PRI, highlightthickness=1)
            self.chat_entry.configure(bg="#012b3a")
            self.prompt_label.configure(bg="#012b3a", fg="#00ff88")
            self.chat_bg_frame.configure(bg="#012b3a")

    def _restore_placeholder(self, event):
        if not self.chat_entry.get():
            self.chat_entry.insert(0, self.placeholder)
            self.chat_entry.configure(fg=C_DIM)
        # Remove glow effect when unfocused
        if hasattr(self, 'chat_bg_frame'):
            self.chat_bg_frame.configure(highlightbackground=C_DIM, highlightthickness=1)
            self.chat_entry.configure(bg="#021c26")
            self.prompt_label.configure(bg="#021c26", fg="#00ffcc")
            self.chat_bg_frame.configure(bg="#021c26")

    def _close_app(self):
        self._run_cam = False
        os._exit(0)

    def start_speaking(self): self.speaking = True
    def stop_speaking(self): self.speaking = False

    def _api_keys_exist(self): return API_FILE.exists()
    def wait_for_api_key(self):
        while not self._api_key_ready: time.sleep(0.1)

    def _show_setup_ui(self):
        self.setup_frame = tk.Frame(self.root, bg="#00080d", highlightbackground=C_PRI, highlightthickness=1)
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(self.setup_frame, text="  INITIALISATION REQUIRED", fg=C_PRI, bg="#00080d", font=("Courier", 13, "bold")).pack(pady=10)
        tk.Label(self.setup_frame, text="GEMINI API KEY", fg=C_DIM, bg="#00080d", font=("Courier", 9)).pack()
        self.g_entry = tk.Entry(self.setup_frame, width=52, fg=C_TEXT, bg="#000d12", show="*")
        self.g_entry.pack(pady=5)
        tk.Button(self.setup_frame, text="SAVE", command=self._save_api_keys, bg=C_BG, fg=C_PRI).pack(pady=10)

    def _save_api_keys(self):
        key = self.g_entry.get().strip()
        if not key: return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(API_FILE, "w", encoding="utf-8") as f: json.dump({"gemini_api_key": key}, f)
        self.setup_frame.destroy()
        self._api_key_ready = True
        self.write_log("SYS: Systems initialised.")