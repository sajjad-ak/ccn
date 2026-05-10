"""
chat_client.py - GUI Chat Client using TCP Sockets and Tkinter
================================================================

Architecture:
    Main Thread   → Tkinter event loop (GUI rendering & user input)
    Receiver Thread → Listens for incoming messages from the server

    The receiver thread dispatches updates to the GUI using
    root.after(), which is the ONLY thread-safe way to modify
    Tkinter widgets from a background thread.

Author:  [Student Name]
Course:  Computer Networks
Date:    May 2026
"""

import socket
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox, font as tkfont
from datetime import datetime

from protocol import (
    Message, MessageType, send_message, recv_message,
    DEFAULT_HOST, DEFAULT_PORT, GROUP_RECIPIENT
)


# ======================== COLOR PALETTE ========================

COLORS = {
    "bg":           "#0f0e17",    # Deep dark background
    "bg2":          "#1a1a2e",    # Slightly lighter panels
    "sidebar":      "#16213e",    # Left sidebar
    "input_bg":     "#1f2937",    # Input fields
    "accent":       "#6366f1",    # Primary accent (indigo)
    "accent_hover": "#818cf8",    # Hover state
    "accent2":      "#e94560",    # Secondary accent (pink)
    "success":      "#10b981",    # Online / success
    "warning":      "#f59e0b",    # Warnings
    "error":        "#ef4444",    # Errors
    "text":         "#f1f5f9",    # Primary text
    "text_dim":     "#94a3b8",    # Secondary text
    "text_dark":    "#475569",    # Placeholder text
    "border":       "#334155",    # Subtle borders
    "msg_self":     "#312e81",    # Sent message bubble
    "msg_other":    "#1e293b",    # Received message bubble
    "msg_system":   "#064e3b",    # System message bubble
}

FONT_FAMILY = "Segoe UI"


# ====================== CHAT CLIENT CLASS ======================

class ChatClient:
    """
    TCP Chat Client with a Tkinter graphical user interface.

    Screens:
        1. Login Screen   – username, host, port, connect button
        2. Chat Screen    – online users panel, chat area, input box
    """

    def __init__(self):
        # ---- Network state ----
        self.sock = None
        self.username = None
        self.connected = False

        # ---- Chat state ----
        self.current_chat = GROUP_RECIPIENT       # Who we're chatting with
        self.online_users = []
        self.chat_history = {}                     # recipient -> [lines]

        # ---- Build root window ----
        self.root = tk.Tk()
        self.root.title("Instant Messenger")
        self.root.configure(bg=COLORS["bg"])
        self.root.geometry("500x580")
        self.root.minsize(450, 500)

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Show the login screen first
        self._build_login_screen()

    # ======================== LOGIN SCREEN ========================

    def _build_login_screen(self):
        """Construct the login / connection screen."""
        self._clear_window()
        self.root.geometry("500x580")

        # Outer frame
        outer = tk.Frame(self.root, bg=COLORS["bg"])
        outer.pack(expand=True, fill="both")

        # Center card
        card = tk.Frame(outer, bg=COLORS["bg2"], padx=40, pady=35)
        card.place(relx=0.5, rely=0.5, anchor="center")

        # ---- Title ----
        tk.Label(card, text="💬", font=(FONT_FAMILY, 42),
                 bg=COLORS["bg2"], fg=COLORS["text"]).pack(pady=(0, 4))
        tk.Label(card, text="Instant Messenger",
                 font=(FONT_FAMILY, 22, "bold"),
                 bg=COLORS["bg2"], fg=COLORS["text"]).pack()
        tk.Label(card, text="Socket Programming Chat System",
                 font=(FONT_FAMILY, 9),
                 bg=COLORS["bg2"], fg=COLORS["text_dim"]).pack(pady=(2, 25))

        # ---- Username field ----
        self._field_label(card, "Username")
        self.login_username = self._entry(card, "Enter your username")

        # ---- Host field ----
        self._field_label(card, "Server Address")
        self.login_host = self._entry(card, DEFAULT_HOST)
        self.login_host.insert(0, DEFAULT_HOST)

        # ---- Port field ----
        self._field_label(card, "Port")
        self.login_port = self._entry(card, str(DEFAULT_PORT))
        self.login_port.insert(0, str(DEFAULT_PORT))

        # ---- Connect button ----
        self.connect_btn = tk.Button(
            card, text="Connect & Join",
            font=(FONT_FAMILY, 12, "bold"),
            bg=COLORS["accent"], fg="#ffffff",
            activebackground=COLORS["accent_hover"],
            activeforeground="#ffffff",
            relief="flat", cursor="hand2",
            padx=20, pady=10,
            command=self._attempt_connect
        )
        self.connect_btn.pack(pady=(20, 8), fill="x")

        # ---- Status label ----
        self.login_status = tk.Label(
            card, text="", font=(FONT_FAMILY, 9),
            bg=COLORS["bg2"], fg=COLORS["error"]
        )
        self.login_status.pack()

        # Focus the username field
        self.login_username.focus_set()

        # Bind Enter key
        self.root.bind("<Return>", lambda e: self._attempt_connect())

    # ======================== CHAT SCREEN ========================

    def _build_chat_screen(self):
        """Construct the main chat interface after successful login."""
        self._clear_window()
        self.root.geometry("960x640")
        self.root.minsize(800, 500)
        self.root.unbind("<Return>")

        # ---- Top bar ----
        topbar = tk.Frame(self.root, bg=COLORS["sidebar"], height=50)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        tk.Label(topbar, text=f"💬 Instant Messenger",
                 font=(FONT_FAMILY, 13, "bold"),
                 bg=COLORS["sidebar"], fg=COLORS["text"]).pack(side="left", padx=15)

        # Connection indicator
        self.status_dot = tk.Label(topbar, text="● Connected",
                                   font=(FONT_FAMILY, 9),
                                   bg=COLORS["sidebar"],
                                   fg=COLORS["success"])
        self.status_dot.pack(side="left", padx=5)

        # Logged-in user label
        tk.Label(topbar, text=f"👤 {self.username}",
                 font=(FONT_FAMILY, 10),
                 bg=COLORS["sidebar"], fg=COLORS["text_dim"]
                 ).pack(side="right", padx=15)

        # Logout button
        tk.Button(topbar, text="Logout", font=(FONT_FAMILY, 9),
                  bg=COLORS["error"], fg="#fff", relief="flat",
                  cursor="hand2", padx=10, pady=3,
                  command=self._on_close
                  ).pack(side="right", padx=(0, 5))

        # ---- Body (sidebar + chat area) ----
        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)

        # ------ Left sidebar: online users ------
        sidebar = tk.Frame(body, bg=COLORS["sidebar"], width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Online Users",
                 font=(FONT_FAMILY, 11, "bold"),
                 bg=COLORS["sidebar"], fg=COLORS["text"]
                 ).pack(padx=12, pady=(15, 5), anchor="w")

        # Group chat button
        self.group_btn = tk.Button(
            sidebar, text="👥  Group Chat",
            font=(FONT_FAMILY, 10), anchor="w",
            bg=COLORS["accent"], fg="#fff",
            activebackground=COLORS["accent_hover"],
            relief="flat", cursor="hand2",
            padx=12, pady=6,
            command=lambda: self._switch_chat(GROUP_RECIPIENT)
        )
        self.group_btn.pack(fill="x", padx=8, pady=(5, 2))

        # Separator
        tk.Frame(sidebar, bg=COLORS["border"], height=1).pack(fill="x", padx=8, pady=8)

        # Scrollable user list container
        self.users_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        self.users_frame.pack(fill="both", expand=True, padx=8)

        # User count
        self.user_count_label = tk.Label(
            sidebar, text="0 users online",
            font=(FONT_FAMILY, 8), bg=COLORS["sidebar"], fg=COLORS["text_dim"]
        )
        self.user_count_label.pack(pady=(0, 10))

        # ------ Right side: chat area ------
        chat_frame = tk.Frame(body, bg=COLORS["bg"])
        chat_frame.pack(side="right", fill="both", expand=True)

        # Chat header
        self.chat_header = tk.Label(
            chat_frame, text="👥 Group Chat",
            font=(FONT_FAMILY, 12, "bold"),
            bg=COLORS["bg2"], fg=COLORS["text"],
            anchor="w", padx=15, pady=10
        )
        self.chat_header.pack(fill="x")

        # Message display area
        self.chat_display = scrolledtext.ScrolledText(
            chat_frame,
            wrap="word",
            state="disabled",
            font=(FONT_FAMILY, 10),
            bg=COLORS["bg"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            relief="flat",
            padx=15, pady=10,
            spacing3=4,
        )
        self.chat_display.pack(fill="both", expand=True)

        # Configure text tags for styling messages
        self.chat_display.tag_configure("self_name",
            foreground=COLORS["accent"], font=(FONT_FAMILY, 9, "bold"))
        self.chat_display.tag_configure("other_name",
            foreground=COLORS["accent2"], font=(FONT_FAMILY, 9, "bold"))
        self.chat_display.tag_configure("system",
            foreground=COLORS["success"], font=(FONT_FAMILY, 9, "italic"))
        self.chat_display.tag_configure("error",
            foreground=COLORS["error"], font=(FONT_FAMILY, 9, "italic"))
        self.chat_display.tag_configure("timestamp",
            foreground=COLORS["text_dark"], font=(FONT_FAMILY, 7))
        self.chat_display.tag_configure("body",
            foreground=COLORS["text"], font=(FONT_FAMILY, 10))

        # ---- Input bar ----
        input_bar = tk.Frame(chat_frame, bg=COLORS["bg2"], pady=10, padx=10)
        input_bar.pack(fill="x")

        self.msg_entry = tk.Entry(
            input_bar,
            font=(FONT_FAMILY, 11),
            bg=COLORS["input_bg"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat", bd=0,
        )
        self.msg_entry.pack(side="left", fill="x", expand=True,
                            ipady=8, padx=(5, 10))
        self.msg_entry.bind("<Return>", lambda e: self._send_message())

        send_btn = tk.Button(
            input_bar, text="Send ➤",
            font=(FONT_FAMILY, 10, "bold"),
            bg=COLORS["accent"], fg="#fff",
            activebackground=COLORS["accent_hover"],
            relief="flat", cursor="hand2",
            padx=18, pady=6,
            command=self._send_message
        )
        send_btn.pack(side="right")

        # Focus input
        self.msg_entry.focus_set()

    # ==================== NETWORK LOGIC ====================

    def _attempt_connect(self):
        """Validate inputs and connect to the server."""
        username = self.login_username.get().strip()
        host = self.login_host.get().strip()
        port_str = self.login_port.get().strip()

        # --- Input validation ---
        if not username:
            self.login_status.config(text="⚠ Please enter a username.")
            return
        if len(username) > 20:
            self.login_status.config(text="⚠ Username max 20 characters.")
            return
        if not host:
            self.login_status.config(text="⚠ Please enter a server address.")
            return
        try:
            port = int(port_str)
            if not (1024 <= port <= 65535):
                raise ValueError
        except ValueError:
            self.login_status.config(text="⚠ Port must be 1024-65535.")
            return

        self.login_status.config(text="Connecting...", fg=COLORS["warning"])
        self.connect_btn.config(state="disabled")
        self.root.update()

        # --- Attempt TCP connection ---
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)       # 5-second connection timeout
            self.sock.connect((host, port))
            self.sock.settimeout(None)    # Remove timeout for normal I/O

            # Send LOGIN message
            login_msg = Message(MessageType.LOGIN, sender=username,
                                body=username)
            send_message(self.sock, login_msg)

            # Wait for LOGIN_ACK
            ack = recv_message(self.sock)
            if ack is None:
                raise ConnectionError("Server closed the connection.")

            # Parse the ack body:  "SUCCESS|Welcome!" or "FAILURE|reason"
            parts = ack.body.split("|", 1)
            status = parts[0]
            reason = parts[1] if len(parts) > 1 else ""

            if status != "SUCCESS":
                self.login_status.config(text=f"✖ {reason}", fg=COLORS["error"])
                self.connect_btn.config(state="normal")
                self.sock.close()
                return

            # --- Login successful ---
            self.username = username
            self.connected = True

            # Switch to the chat screen
            self._build_chat_screen()

            # Start the background receiver thread
            recv_thread = threading.Thread(target=self._receive_loop,
                                           daemon=True)
            recv_thread.start()

        except socket.timeout:
            self.login_status.config(
                text="✖ Connection timed out.", fg=COLORS["error"])
            self.connect_btn.config(state="normal")
        except ConnectionRefusedError:
            self.login_status.config(
                text="✖ Server not reachable.", fg=COLORS["error"])
            self.connect_btn.config(state="normal")
        except Exception as e:
            self.login_status.config(
                text=f"✖ {e}", fg=COLORS["error"])
            self.connect_btn.config(state="normal")

    def _receive_loop(self):
        """
        Background thread: continuously read messages from the server
        and dispatch them to the GUI thread via root.after().
        """
        while self.connected:
            try:
                message = recv_message(self.sock)
                if message is None:
                    # Server closed connection
                    self.root.after(0, self._handle_disconnect,
                                   "Server closed the connection.")
                    break

                # Dispatch to GUI thread
                self.root.after(0, self._process_message, message)

            except (ConnectionResetError, ConnectionAbortedError,
                    BrokenPipeError, OSError):
                self.root.after(0, self._handle_disconnect,
                               "Lost connection to server.")
                break
            except Exception as e:
                self.root.after(0, self._handle_disconnect, str(e))
                break

    def _send_message(self):
        """Read the input box and send the message to the server."""
        if not self.connected:
            return

        text = self.msg_entry.get().strip()
        if not text:
            return

        # Clear the input box
        self.msg_entry.delete(0, tk.END)

        try:
            if self.current_chat == GROUP_RECIPIENT:
                # Group message
                msg = Message(
                    msg_type  = MessageType.GROUP_MSG,
                    sender    = self.username,
                    recipient = GROUP_RECIPIENT,
                    body      = text,
                )
            else:
                # Direct message
                msg = Message(
                    msg_type  = MessageType.MSG,
                    sender    = self.username,
                    recipient = self.current_chat,
                    body      = text,
                )
            send_message(self.sock, msg)

        except Exception as e:
            self._append_chat("system",
                              f"Failed to send message: {e}", "error")

    # ==================== MESSAGE PROCESSING ====================

    def _process_message(self, message):
        """
        Handle an incoming message from the server.
        Called on the GUI (main) thread.
        """
        if message.msg_type == MessageType.MSG:
            # Direct message — display in the appropriate chat
            other = (message.sender if message.sender != self.username
                     else message.recipient)

            # Determine the chat key for history
            chat_key = other

            # Store in history
            self._store_history(chat_key, message)

            # If we're currently viewing that chat, display it
            if self.current_chat == chat_key:
                self._display_message(message)

        elif message.msg_type == MessageType.GROUP_MSG:
            self._store_history(GROUP_RECIPIENT, message)
            if self.current_chat == GROUP_RECIPIENT:
                self._display_message(message)

        elif message.msg_type == MessageType.USER_LIST:
            self._update_user_list(message.body)

        elif message.msg_type == MessageType.SYSTEM:
            # System messages go to whichever chat is open
            self._append_chat("system", message.body, "system")

        elif message.msg_type == MessageType.ERROR:
            self._append_chat("system", f"⚠ {message.body}", "error")

    def _display_message(self, message):
        """Render a single MSG or GROUP_MSG in the chat display."""
        is_self = (message.sender == self.username)
        name_tag = "self_name" if is_self else "other_name"
        prefix = "You" if is_self else message.sender

        self._append_chat(
            name_tag,
            f"{prefix}  [{message.timestamp}]\n{message.body}",
            name_tag
        )

    def _store_history(self, chat_key, message):
        """Store a message in the local chat history dictionary."""
        if chat_key not in self.chat_history:
            self.chat_history[chat_key] = []
        self.chat_history[chat_key].append(message)

    # ==================== USER LIST ====================

    def _update_user_list(self, csv_users):
        """Refresh the online-users sidebar from a comma-separated list."""
        self.online_users = [u for u in csv_users.split(",") if u]

        # Update count label
        count = len(self.online_users)
        self.user_count_label.config(text=f"{count} user{'s' if count != 1 else ''} online")

        # Clear old buttons
        for widget in self.users_frame.winfo_children():
            widget.destroy()

        # Create a button for each user (except self)
        for user in self.online_users:
            if user == self.username:
                continue

            is_active = (self.current_chat == user)
            bg = COLORS["accent"] if is_active else COLORS["sidebar"]
            fg = "#fff" if is_active else COLORS["text"]

            btn = tk.Button(
                self.users_frame,
                text=f"  💬 {user}",
                font=(FONT_FAMILY, 10),
                bg=bg, fg=fg,
                activebackground=COLORS["accent_hover"],
                activeforeground="#fff",
                relief="flat", anchor="w",
                cursor="hand2", padx=8, pady=5,
                command=lambda u=user: self._switch_chat(u)
            )
            btn.pack(fill="x", pady=1)

    # ==================== CHAT SWITCHING ====================

    def _switch_chat(self, recipient):
        """Switch the active chat view to a different user or group."""
        self.current_chat = recipient

        # Update header
        if recipient == GROUP_RECIPIENT:
            self.chat_header.config(text="👥 Group Chat")
        else:
            self.chat_header.config(text=f"💬 {recipient}")

        # Clear display
        self.chat_display.config(state="normal")
        self.chat_display.delete("1.0", tk.END)
        self.chat_display.config(state="disabled")

        # Reload history for this chat
        if recipient in self.chat_history:
            for msg in self.chat_history[recipient]:
                self._display_message(msg)

        # Refresh sidebar highlighting
        if self.online_users:
            self._update_user_list(",".join(self.online_users))

        # Focus input
        self.msg_entry.focus_set()

    # ==================== DISPLAY HELPERS ====================

    def _append_chat(self, sender_type, text, tag):
        """Append a styled line to the chat display widget."""
        self.chat_display.config(state="normal")
        self.chat_display.insert(tk.END, text + "\n\n", tag)
        self.chat_display.config(state="disabled")
        self.chat_display.see(tk.END)   # Auto-scroll to bottom

    # ==================== DISCONNECT / CLEANUP ====================

    def _handle_disconnect(self, reason=""):
        """Handle unexpected disconnection from the server."""
        if not self.connected:
            return
        self.connected = False

        try:
            self.sock.close()
        except Exception:
            pass

        # Update the status indicator
        try:
            self.status_dot.config(text="● Disconnected", fg=COLORS["error"])
        except Exception:
            pass

        messagebox.showwarning("Disconnected",
                               f"Disconnected from server.\n{reason}")

    def _on_close(self):
        """Handle the window close (X) button."""
        if self.connected:
            try:
                # Send a graceful DISCONNECT message
                msg = Message(MessageType.DISCONNECT, self.username,
                              body="bye")
                send_message(self.sock, msg)
            except Exception:
                pass
            self.connected = False
            try:
                self.sock.close()
            except Exception:
                pass

        self.root.destroy()

    # ==================== UTILITY ====================

    def _clear_window(self):
        """Remove all widgets from the root window."""
        for widget in self.root.winfo_children():
            widget.destroy()

    def _field_label(self, parent, text):
        """Create a small label above an input field."""
        tk.Label(parent, text=text,
                 font=(FONT_FAMILY, 9, "bold"),
                 bg=COLORS["bg2"], fg=COLORS["text_dim"],
                 anchor="w").pack(fill="x", pady=(10, 3))

    def _entry(self, parent, placeholder=""):
        """Create a styled Entry widget."""
        entry = tk.Entry(
            parent,
            font=(FONT_FAMILY, 11),
            bg=COLORS["input_bg"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat", bd=0,
        )
        entry.pack(fill="x", ipady=8, pady=(0, 2))
        return entry

    def run(self):
        """Start the Tkinter main event loop."""
        self.root.mainloop()


# ========================= ENTRY POINT =========================

if __name__ == "__main__":
    app = ChatClient()
    app.run()
