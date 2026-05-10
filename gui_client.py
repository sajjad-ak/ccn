import socket
import threading
import json
import queue
import random
import os
from datetime import datetime, timezone
import uuid
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import simpledialog


def utc_iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def encode_json_line(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def _user_store_path() -> str:
    return os.path.join(os.path.dirname(__file__), "user_store.json")


def load_user_store() -> dict:
    try:
        with open(_user_store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except OSError:
        return {}
    except json.JSONDecodeError:
        return {}
    return {}


def save_user_store(store: dict) -> None:
    try:
        with open(_user_store_path(), "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
    except OSError:
        return


class FloatingBackground(tk.Canvas):
    def __init__(self, master, *, bg="#05070d", dot_color="#1e88ff", width=900, height=600):
        super().__init__(master, bg=bg, highlightthickness=0)
        self._dot_color = dot_color
        self._width = width
        self._height = height
        self._dots: list[dict] = []
        self._running = False

        self.bind("<Configure>", self._on_resize)
        self._seed(28)

    def _on_resize(self, event):
        self._width = max(1, int(event.width))
        self._height = max(1, int(event.height))

    def _seed(self, count: int) -> None:
        self.delete("all")
        self._dots.clear()
        for _ in range(count):
            r = random.randint(2, 5)
            x = random.randint(0, max(1, self._width - 1))
            y = random.randint(0, max(1, self._height - 1))
            vx = random.uniform(-0.35, 0.35)
            vy = random.uniform(-0.28, 0.28)
            a = random.randint(60, 120)

            dot_id = self.create_oval(x - r, y - r, x + r, y + r, fill=self._dot_color, outline="")
            self._dots.append({"id": dot_id, "r": r, "x": float(x), "y": float(y), "vx": vx, "vy": vy, "a": a})

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self) -> None:
        self._running = False

    def _tick(self) -> None:
        if not self._running:
            return

        for d in self._dots:
            d["x"] += d["vx"]
            d["y"] += d["vy"]

            if d["x"] < 0 or d["x"] > self._width:
                d["vx"] *= -1
            if d["y"] < 0 or d["y"] > self._height:
                d["vy"] *= -1

            x = d["x"]
            y = d["y"]
            r = d["r"]
            self.coords(d["id"], x - r, y - r, x + r, y + r)

        self.after(30, self._tick)


class ChatGUI:
    def __init__(self, host: str = "127.0.0.1", port: int = 5000):
        self.host = host
        self.port = port

        self.root = tk.Tk()
        self.root.title("Instant Messenger")
        self.root.geometry("950x620")
        self.root.minsize(860, 560)

        # Theme colors: black background with blue/gold writing
        self.C_BG = "#05070d"
        self.C_PANEL = "#0b1020"
        self.C_BLUE = "#1e88ff"
        self.C_GOLD = "#e0b44a"
        self.C_TEXT = "#d9e2ff"
        self.C_MUTED = "#8aa0c8"

        self._sock: socket.socket | None = None
        self._stop_event = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._inbound: queue.Queue[dict] = queue.Queue()

        self._username = ""
        self._email = ""
        self._store = load_user_store()

        self._users: list[dict] = []
        self._active_chat_kind: str = "group"  # group|direct
        self._active_to_email: str | None = None
        self._history: dict[str, list[dict]] = {"group": []}
        self._current_line_message_ids: list[str | None] = []
        self._selected_message_id: str | None = None

        self._connected_event = threading.Event()
        self._login_failed_event = threading.Event()
        self._login_error_text = ""

        self.root.configure(bg=self.C_BG)
        self._configure_ttk_style()

        self.bg = FloatingBackground(self.root, bg=self.C_BG, dot_color=self.C_BLUE)
        self.bg.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.bg.start()

        self.container = tk.Frame(self.root, bg=self.C_BG)
        self.container.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.88, relheight=0.86)

        self.login_frame = tk.Frame(self.container, bg=self.C_PANEL)
        self.home_frame = tk.Frame(self.container, bg=self.C_PANEL)
        self.chat_frame = tk.Frame(self.container, bg=self.C_PANEL)

        self._build_login()
        self._build_home()
        self._build_chat()

        self._show_login()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Pump inbound messages from receiver thread into Tk safely
        self.root.after(50, self._drain_inbound)

    def _configure_ttk_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "TButton",
            font=("Segoe UI", 11),
            padding=10,
            background=self.C_PANEL,
            foreground=self.C_TEXT,
            borderwidth=1,
            focusthickness=0,
        )
        style.map(
            "TButton",
            background=[("active", "#111a33")],
            foreground=[("active", self.C_TEXT)],
        )

        style.configure(
            "Accent.TButton",
            background=self.C_BLUE,
            foreground="#06101f",
            font=("Segoe UI", 11, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#3a9bff")],
        )

        style.configure(
            "Gold.TButton",
            background=self.C_GOLD,
            foreground="#1b1406",
            font=("Segoe UI", 11, "bold"),
        )
        style.map(
            "Gold.TButton",
            background=[("active", "#f0c666")],
        )

    def _build_login(self) -> None:
        f = self.login_frame

        hero = tk.Frame(f, bg=self.C_PANEL)
        hero.pack(fill="x", padx=40, pady=(26, 6))

        top = tk.Label(
            hero,
            text="INSTANT MESSAGING",
            bg=self.C_PANEL,
            fg=self.C_GOLD,
            font=("Segoe UI", 10, "bold"),
        )
        top.pack(anchor="center")

        headline = tk.Frame(hero, bg=self.C_PANEL)
        headline.pack(pady=(14, 6))

        tk.Label(
            headline,
            text="Turn conversations into",
            bg=self.C_PANEL,
            fg=self.C_TEXT,
            font=("Georgia", 34, "bold"),
        ).pack(anchor="center")

        tk.Label(
            headline,
            text="secure chat sessions",
            bg=self.C_PANEL,
            fg=self.C_GOLD,
            font=("Georgia", 34, "italic"),
        ).pack(anchor="center")

        desc = tk.Label(
            hero,
            text=(
                "Login to track your identity across sessions.\n"
                "Choose Google (tracked by email) or Email login."
            ),
            bg=self.C_PANEL,
            fg=self.C_MUTED,
            font=("Segoe UI", 11),
            justify="center",
        )
        desc.pack(pady=(8, 16))

        form = tk.Frame(f, bg=self.C_PANEL)
        form.pack(pady=(8, 6))

        last = self._store.get("last_login", {}) if isinstance(self._store, dict) else {}
        last_email = last.get("email", "") if isinstance(last, dict) else ""
        last_server = last.get("server", f"{self.host}:{self.port}") if isinstance(last, dict) else f"{self.host}:{self.port}"
        last_user = last.get("username", "") if isinstance(last, dict) else ""

        tk.Label(form, text="Email", bg=self.C_PANEL, fg=self.C_TEXT, font=("Segoe UI", 11)).grid(
            row=0, column=0, sticky="w", padx=4, pady=(0, 4)
        )
        self.email_var = tk.StringVar(value=last_email)
        self.email_entry = tk.Entry(
            form,
            textvariable=self.email_var,
            bg="#0a0f1f",
            fg=self.C_TEXT,
            insertbackground=self.C_TEXT,
            relief="flat",
            font=("Segoe UI", 12),
            width=38,
        )
        self.email_entry.grid(row=1, column=0, padx=4, pady=(0, 12), ipady=8)

        tk.Label(form, text="Username", bg=self.C_PANEL, fg=self.C_TEXT, font=("Segoe UI", 11)).grid(
            row=2, column=0, sticky="w", padx=4, pady=(0, 4)
        )
        self.username_var = tk.StringVar(value=last_user)
        self.username_entry = tk.Entry(
            form,
            textvariable=self.username_var,
            bg="#0a0f1f",
            fg=self.C_TEXT,
            insertbackground=self.C_TEXT,
            relief="flat",
            font=("Segoe UI", 12),
            width=38,
        )
        self.username_entry.grid(row=3, column=0, padx=4, pady=(0, 12), ipady=8)

        tk.Label(form, text="Server (host:port)", bg=self.C_PANEL, fg=self.C_TEXT, font=("Segoe UI", 11)).grid(
            row=4, column=0, sticky="w", padx=4, pady=(0, 4)
        )
        self.server_var = tk.StringVar(value=last_server)
        self.server_entry = tk.Entry(
            form,
            textvariable=self.server_var,
            bg="#0a0f1f",
            fg=self.C_TEXT,
            insertbackground=self.C_TEXT,
            relief="flat",
            font=("Segoe UI", 12),
            width=38,
        )
        self.server_entry.grid(row=5, column=0, padx=4, pady=(0, 8), ipady=8)

        self.login_error = tk.Label(f, text="", bg=self.C_PANEL, fg="#ff6b6b", font=("Segoe UI", 11))
        self.login_error.pack(pady=(6, 10))

        btns = tk.Frame(f, bg=self.C_PANEL)
        btns.pack(pady=(4, 6))

        google_btn = ttk.Button(btns, text="Continue with Google", style="Gold.TButton", command=self._login_google)
        google_btn.grid(row=0, column=0, padx=6, pady=6)

        email_btn = ttk.Button(btns, text="Continue with Email", style="Accent.TButton", command=self._login_email)
        email_btn.grid(row=0, column=1, padx=6, pady=6)

        hint = tk.Label(
            f,
            text="Tip: run python server.py first, then login here.",
            bg=self.C_PANEL,
            fg=self.C_MUTED,
            font=("Segoe UI", 10),
        )
        hint.pack(pady=(14, 12))

        f.bind_all("<Return>", lambda _e: self._login_email())

    def _build_chat(self) -> None:
        f = self.chat_frame

        header = tk.Frame(f, bg=self.C_PANEL)
        header.pack(fill="x", padx=18, pady=(14, 8))

        back_btn = ttk.Button(header, text="Home", command=self._back_to_home)
        back_btn.pack(side="left")

        self.chat_target = tk.Label(
            header,
            text="",
            bg=self.C_PANEL,
            fg=self.C_MUTED,
            font=("Segoe UI", 10),
        )
        self.chat_target.pack(side="left", padx=(12, 0))

        self.chat_title = tk.Label(
            header,
            text="",
            bg=self.C_PANEL,
            fg=self.C_GOLD,
            font=("Segoe UI", 16, "bold"),
        )
        self.chat_title.pack(side="left", padx=(12, 0))

        self.status_label = tk.Label(
            header,
            text="",
            bg=self.C_PANEL,
            fg=self.C_MUTED,
            font=("Segoe UI", 10),
        )
        self.status_label.pack(side="right")

        body = tk.Frame(f, bg=self.C_PANEL)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 10))

        self.chat_text = tk.Text(
            body,
            bg="#070b16",
            fg=self.C_TEXT,
            insertbackground=self.C_TEXT,
            relief="flat",
            wrap="word",
            font=("Consolas", 11),
        )
        self.chat_text.pack(fill="both", expand=True, side="left")
        self.chat_text.configure(state="disabled")
        self.chat_text.bind("<Button-1>", self._on_chat_click)

        scroll = ttk.Scrollbar(body, orient="vertical", command=self.chat_text.yview)
        scroll.pack(side="right", fill="y")
        self.chat_text.configure(yscrollcommand=scroll.set)

        composer = tk.Frame(f, bg=self.C_PANEL)
        composer.pack(fill="x", padx=18, pady=(0, 18))

        self.msg_var = tk.StringVar()
        self.msg_entry = tk.Entry(
            composer,
            textvariable=self.msg_var,
            bg="#0a0f1f",
            fg=self.C_TEXT,
            insertbackground=self.C_TEXT,
            relief="flat",
            font=("Segoe UI", 12),
        )
        self.msg_entry.pack(side="left", fill="x", expand=True, ipady=10)
        self.msg_entry.bind("<Return>", lambda _e: self._send_message())

        send_btn = ttk.Button(composer, text="Send", style="Accent.TButton", command=self._send_message)
        send_btn.pack(side="left", padx=(10, 0))

        self.delete_btn = ttk.Button(composer, text="Delete", command=self._delete_selected)
        self.delete_btn.pack(side="left", padx=(10, 0))
        self.delete_btn.state(["disabled"])

        leave_btn = ttk.Button(composer, text="Leave", command=self._leave_chat)
        leave_btn.pack(side="left", padx=(10, 0))

    def _build_home(self) -> None:
        f = self.home_frame

        wrap = tk.Frame(f, bg=self.C_PANEL)
        wrap.pack(fill="both", expand=True, padx=40, pady=30)

        tk.Label(
            wrap,
            text="Welcome",
            bg=self.C_PANEL,
            fg=self.C_GOLD,
            font=("Georgia", 30, "bold"),
        ).pack(pady=(16, 4))

        self.home_identity = tk.Label(
            wrap,
            text="",
            bg=self.C_PANEL,
            fg=self.C_TEXT,
            font=("Segoe UI", 12),
        )
        self.home_identity.pack(pady=(0, 14))

        self.home_status = tk.Label(
            wrap,
            text="",
            bg=self.C_PANEL,
            fg=self.C_MUTED,
            font=("Segoe UI", 10),
        )
        self.home_status.pack(pady=(0, 18))

        actions = tk.Frame(wrap, bg=self.C_PANEL)
        actions.pack(pady=8)

        enter_btn = ttk.Button(actions, text="Open Group Chat", style="Accent.TButton", command=self._enter_group)
        enter_btn.grid(row=0, column=0, padx=8, pady=8)

        dm_btn = ttk.Button(actions, text="Chat with Selected", command=self._enter_selected_user)
        dm_btn.grid(row=0, column=1, padx=8, pady=8)

        refresh_btn = ttk.Button(actions, text="Refresh Users", command=self._request_user_list)
        refresh_btn.grid(row=0, column=2, padx=8, pady=8)

        logout_btn = ttk.Button(actions, text="Logout", command=self._logout)
        logout_btn.grid(row=0, column=3, padx=8, pady=8)

        tk.Label(
            wrap,
            text="Online Users",
            bg=self.C_PANEL,
            fg=self.C_TEXT,
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(18, 6))

        self.users_list = tk.Listbox(
            wrap,
            bg="#070b16",
            fg=self.C_TEXT,
            activestyle="none",
            highlightthickness=0,
            selectbackground="#111a33",
            selectforeground=self.C_TEXT,
            relief="flat",
            font=("Consolas", 11),
            height=8,
        )
        self.users_list.pack(fill="x", pady=(0, 6))

        tk.Label(
            wrap,
            text="Tip: select a user and click 'Chat with Selected' for 1-to-1 messaging.",
            bg=self.C_PANEL,
            fg=self.C_MUTED,
            font=("Segoe UI", 10),
        ).pack(pady=(6, 0))

        tk.Label(
            wrap,
            text="Group chat broadcasts messages to all connected users.",
            bg=self.C_PANEL,
            fg=self.C_MUTED,
            font=("Segoe UI", 10),
        ).pack(pady=(18, 0))

    def _show_login(self) -> None:
        self.chat_frame.pack_forget()
        self.home_frame.pack_forget()
        self.login_frame.pack(fill="both", expand=True)
        self.login_error.configure(text="")
        self.root.after(50, lambda: self.username_entry.focus_set())

    def _show_home(self) -> None:
        self.login_frame.pack_forget()
        self.chat_frame.pack_forget()
        self.home_frame.pack(fill="both", expand=True)

    def _show_chat(self) -> None:
        self.login_frame.pack_forget()
        self.home_frame.pack_forget()
        self.chat_frame.pack(fill="both", expand=True)
        self.root.after(50, lambda: self.msg_entry.focus_set())

    def _append_chat_line(self, text: str) -> None:
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", text + "\n")
        self.chat_text.see("end")
        self.chat_text.configure(state="disabled")

    def _render_current_history(self) -> None:
        key = "group" if self._active_chat_kind == "group" else (self._active_to_email or "group")
        items = self._history.get(key, [])
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        self._current_line_message_ids = []
        self._selected_message_id = None
        self.delete_btn.state(["disabled"])

        for m in items:
            ts = str(m.get("timestamp", ""))
            sender = str(m.get("sender", "?"))
            msg_id = m.get("id")
            deleted = bool(m.get("deleted"))

            if m.get("type") == "direct":
                sender_email = str(m.get("sender_email", ""))
                prefix = "DM (you)" if sender_email == self._email else "DM"
                text = "(deleted)" if deleted else str(m.get("message", ""))
                line = f"[{ts}] {prefix} {sender}: {text}"
            else:
                text = "(deleted)" if deleted else str(m.get("message", ""))
                line = f"[{ts}] {sender}: {text}"

            self.chat_text.insert("end", line + "\n")
            self._current_line_message_ids.append(str(msg_id) if msg_id else None)
        self.chat_text.see("end")
        self.chat_text.configure(state="disabled")

    def _request_history_current(self) -> None:
        if self._sock is None:
            return
        try:
            if self._active_chat_kind == "group":
                self._sock.sendall(encode_json_line({"type": "history", "scope": "group"}))
            elif self._active_chat_kind == "direct" and self._active_to_email:
                self._sock.sendall(
                    encode_json_line({"type": "history", "scope": "direct", "peer": self._active_to_email})
                )
        except OSError:
            self.status_label.configure(text="History request failed")

    def _login_google(self) -> None:
        email = self.email_var.get().strip()
        if not email:
            email = simpledialog.askstring("Google Login", "Enter your Google email for tracking:")
            if email is None:
                return
            email = email.strip()
            self.email_var.set(email)

        if not email or "@" not in email:
            self.login_error.configure(text="Enter a valid email for Google tracking")
            return

        username = self.username_var.get().strip()
        if not username:
            username = email.split("@", 1)[0]
            self.username_var.set(username)

        self._persist_identity(method="google", email=email, username=username)
        self._connect_and_login(email=email, display_name=username)

    def _login_email(self) -> None:
        email = self.email_var.get().strip()
        username = self.username_var.get().strip()

        if not email or "@" not in email:
            self.login_error.configure(text="Email is required and must be valid")
            return

        if not username:
            username = email.split("@", 1)[0]
            self.username_var.set(username)

        if not username:
            return

        self._persist_identity(method="email", email=email, username=username)
        self._connect_and_login(email=email, display_name=username)

    def _persist_identity(self, *, method: str, email: str, username: str) -> None:
        server = self.server_var.get().strip()
        self._store = {
            "last_login": {
                "method": method,
                "email": email,
                "username": username,
                "server": server,
                "timestamp": utc_iso_timestamp(),
            }
        }
        save_user_store(self._store)

    def _parse_server(self) -> tuple[str, int] | None:
        raw = self.server_var.get().strip()
        if not raw:
            return None
        if ":" not in raw:
            return None
        host, port_s = raw.rsplit(":", 1)
        host = host.strip()
        try:
            port = int(port_s.strip())
        except ValueError:
            return None
        if not host or port <= 0 or port > 65535:
            return None
        return host, port

    def _connect_and_login(self, *, email: str, display_name: str) -> None:
        hp = self._parse_server()
        if hp is None:
            self.login_error.configure(text="Server must be in host:port format")
            return

        host, port = hp

        self._connected_event.clear()
        self._login_failed_event.clear()
        self._login_error_text = ""

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, port))
            sock.sendall(encode_json_line({"type": "login", "email": email, "display_name": display_name}))
        except OSError as e:
            self.login_error.configure(text=f"Could not connect/login: {e}")
            try:
                sock.close()
            except Exception:
                pass
            return

        self._sock = sock
        self._username = display_name
        self._email = email
        self._stop_event.clear()

        self.chat_title.configure(text=f"Chat — {display_name}")
        self.status_label.configure(text=f"Connected to {host}:{port}")

        self.home_identity.configure(text=f"{display_name}  <{email}>")
        self.home_status.configure(text=f"Connected to {host}:{port}")

        self._rx_thread = threading.Thread(target=self._receiver_loop, daemon=True)
        self._rx_thread.start()

        self._append_chat_line(f"[{utc_iso_timestamp()}] CLIENT: connected, waiting for server welcome...")
        self.home_identity.configure(text=f"{display_name}  <{email}>")
        self.home_status.configure(text="Authenticating...")
        self._show_home()

        # Wait briefly for server to accept/reject login (receiver thread sets events)
        self.root.after(50, self._check_login_result)

    def _check_login_result(self) -> None:
        if self._login_failed_event.is_set():
            msg = self._login_error_text or "Login failed"
            self._disconnect()
            self._show_login()
            messagebox.showerror("Login Failed", msg)
            return

        if self._connected_event.is_set():
            self.home_status.configure(text="Authenticated")
            self._request_user_list()
            return

        if self._sock is None or self._stop_event.is_set():
            return

        self.root.after(50, self._check_login_result)

    def _enter_group(self) -> None:
        self._active_chat_kind = "group"
        self._active_to_email = None
        self.chat_target.configure(text="GROUP")
        self._show_chat()
        self._request_history_current()
        self.msg_entry.configure(state="normal")
        self.root.after(50, lambda: self.msg_entry.focus_set())

    def _enter_direct(self, to_email: str, to_display: str) -> None:
        self._active_chat_kind = "direct"
        self._active_to_email = to_email
        if to_email not in self._history:
            self._history[to_email] = []
        self.chat_target.configure(text=f"DM → {to_display} <{to_email}>")
        self._show_chat()
        self._request_history_current()
        self.msg_entry.configure(state="normal")
        self.root.after(50, lambda: self.msg_entry.focus_set())

    def _enter_selected_user(self) -> None:
        if not hasattr(self, "users_list"):
            return
        sel = self.users_list.curselection()
        if not sel:
            self.home_status.configure(text="Select a user first")
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._users):
            return
        u = self._users[idx]
        to_email = str(u.get("email", "")).strip().lower()
        to_name = str(u.get("display_name", "")).strip() or to_email
        if not to_email or to_email == self._email:
            self.home_status.configure(text="Select another user")
            return
        self._enter_direct(to_email, to_name)

    def _back_to_home(self) -> None:
        self._show_home()

    def _logout(self) -> None:
        self._disconnect()
        self._show_login()

    def _receiver_loop(self) -> None:
        assert self._sock is not None
        buffer = b""

        try:
            while not self._stop_event.is_set():
                chunk = self._sock.recv(4096)
                if not chunk:
                    self._inbound.put({"type": "status", "message": "Server closed connection"})
                    self._stop_event.set()
                    return

                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue

                    try:
                        payload = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        self._inbound.put({"type": "status", "message": "Received invalid JSON"})
                        continue

                    self._inbound.put(payload)
        except OSError:
            self._inbound.put({"type": "status", "message": "Disconnected"})
            self._stop_event.set()

    def _drain_inbound(self) -> None:
        try:
            while True:
                payload = self._inbound.get_nowait()

                if payload.get("type") == "welcome":
                    self._connected_event.set()
                    continue

                if payload.get("type") == "error":
                    self._login_error_text = str(payload.get("message", "Login rejected"))
                    self._login_failed_event.set()
                    continue

                if payload.get("type") == "users":
                    users = payload.get("users", [])
                    if isinstance(users, list):
                        self._users = [u for u in users if isinstance(u, dict)]
                        self._refresh_users_list()
                    continue

                if payload.get("type") == "status":
                    self.status_label.configure(text=str(payload.get("message", "")))
                    continue

                if payload.get("type") == "history":
                    key = str(payload.get("key", "")).strip() or "group"
                    messages = payload.get("messages", [])
                    if isinstance(messages, list):
                        self._history[key] = [m for m in messages if isinstance(m, dict)]
                    self._render_current_history()
                    continue

                if payload.get("type") == "deleted":
                    msg_id = str(payload.get("id", "")).strip()
                    scope = str(payload.get("scope", "")).strip()
                    if msg_id:
                        self._apply_deleted(msg_id, scope)
                        self._render_current_history()
                    continue

                if payload.get("type") == "direct":
                    sender_email = str(payload.get("sender_email", ""))
                    to_email = str(payload.get("to", "")).strip().lower()
                    key = to_email if sender_email == self._email else sender_email
                    if key:
                        msg_id = str(payload.get("id", "")).strip()
                        if not msg_id or not self._has_message_id(key, msg_id):
                            self._history.setdefault(key, []).append(payload)
                        if self._active_chat_kind == "direct" and self._active_to_email == key:
                            self._render_current_history()
                    continue

                if payload.get("type") == "message":
                    msg_id = str(payload.get("id", "")).strip()
                    if not msg_id or not self._has_message_id("group", msg_id):
                        self._history.setdefault("group", []).append(payload)
                    if self._active_chat_kind == "group":
                        self._render_current_history()
                    continue

                sender = payload.get("sender", "?")
                ts = payload.get("timestamp", "")
                msg = payload.get("message", "")
                if sender and msg:
                    line = f"[{ts}] {sender}: {msg}"
                    self._history.setdefault("group", []).append({
                        "type": "system",
                        "timestamp": ts,
                        "sender": sender,
                        "message": msg,
                        "deleted": False,
                    })
                    if self._active_chat_kind == "group":
                        self._render_current_history()
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self._drain_inbound)

    def _apply_deleted(self, message_id: str, scope: str) -> None:
        if scope == "group":
            keys = ["group"]
        else:
            keys = list(self._history.keys())

        for k in keys:
            items = self._history.get(k, [])
            for m in items:
                if isinstance(m, dict) and str(m.get("id", "")) == message_id:
                    m["deleted"] = True
                    m["message"] = ""

    def _has_message_id(self, key: str, message_id: str) -> bool:
        items = self._history.get(key, [])
        for m in items:
            if isinstance(m, dict) and str(m.get("id", "")) == message_id:
                return True
        return False

    def _refresh_users_list(self) -> None:
        if not hasattr(self, "users_list"):
            return
        self.users_list.delete(0, "end")
        filtered = []
        for u in self._users:
            email = str(u.get("email", "")).strip().lower()
            name = str(u.get("display_name", "")).strip() or email
            if not email:
                continue
            filtered.append({"email": email, "display_name": name})
        self._users = filtered
        for u in self._users:
            marker = " (you)" if u.get("email") == self._email else ""
            self.users_list.insert("end", f"{u.get('display_name')} <{u.get('email')}>{marker}")

    def _request_user_list(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.sendall(encode_json_line({"type": "list_users"}))
        except OSError:
            self.status_label.configure(text="Request failed (disconnected)")
            self._stop_event.set()

    def _send_message(self) -> None:
        text = self.msg_var.get()
        if not text.strip():
            return

        if self._sock is None:
            self.status_label.configure(text="Not connected")
            return

        client_id = uuid.uuid4().hex
        if self._active_chat_kind == "direct" and self._active_to_email:
            payload = {"type": "direct", "to": self._active_to_email, "message": text, "client_id": client_id}
            optimistic = {
                "type": "direct",
                "id": client_id,
                "sender": self._username,
                "sender_email": self._email,
                "to": self._active_to_email,
                "timestamp": utc_iso_timestamp(),
                "message": text,
                "deleted": False,
            }
            self._history.setdefault(self._active_to_email, []).append(optimistic)
        else:
            payload = {"type": "message", "message": text, "client_id": client_id}
            optimistic = {
                "type": "message",
                "id": client_id,
                "sender": self._username,
                "sender_email": self._email,
                "timestamp": utc_iso_timestamp(),
                "message": text,
                "deleted": False,
            }
            self._history.setdefault("group", []).append(optimistic)

        try:
            self._sock.sendall(encode_json_line(payload))
        except OSError:
            self.status_label.configure(text="Send failed (disconnected)")
            self._stop_event.set()

        self.msg_var.set("")
        self._render_current_history()

    def _on_chat_click(self, event) -> None:
        try:
            index = self.chat_text.index(f"@{event.x},{event.y}")
            line_no = int(index.split(".", 1)[0])
        except Exception:
            return

        if line_no <= 0 or line_no > len(self._current_line_message_ids):
            self._selected_message_id = None
            self.delete_btn.state(["disabled"])
            return

        msg_id = self._current_line_message_ids[line_no - 1]
        if not msg_id:
            self._selected_message_id = None
            self.delete_btn.state(["disabled"])
            return

        key = "group" if self._active_chat_kind == "group" else (self._active_to_email or "group")
        items = self._history.get(key, [])
        msg = next((m for m in items if isinstance(m, dict) and str(m.get("id", "")) == msg_id), None)
        if not msg:
            self._selected_message_id = None
            self.delete_btn.state(["disabled"])
            return

        if str(msg.get("sender_email", "")) != self._email or bool(msg.get("deleted")):
            self._selected_message_id = None
            self.delete_btn.state(["disabled"])
            return

        self._selected_message_id = msg_id
        self.delete_btn.state(["!disabled"])

    def _delete_selected(self) -> None:
        if not self._selected_message_id or self._sock is None:
            return

        if self._active_chat_kind == "group":
            payload = {"type": "delete", "scope": "group", "id": self._selected_message_id}
        else:
            payload = {
                "type": "delete",
                "scope": "direct",
                "peer": self._active_to_email,
                "id": self._selected_message_id,
            }
        try:
            self._sock.sendall(encode_json_line(payload))
        except OSError:
            self.status_label.configure(text="Delete failed (disconnected)")
            self._stop_event.set()

    def _leave_chat(self) -> None:
        self._disconnect()
        self._show_login()

    def _disconnect(self) -> None:
        self._stop_event.set()

        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass

        self._sock = None
        self._username = ""
        self._email = ""
        self.status_label.configure(text="")

    def _on_close(self) -> None:
        self._disconnect()
        self.bg.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ChatGUI(host="127.0.0.1", port=5000).run()
