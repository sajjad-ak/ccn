"""
chat_server.py - Multi-Client TCP Chat Server
===============================================

This server application:
  - Listens for TCP connections on a configurable host and port
  - Handles multiple clients concurrently using multi-threading
  - Maintains a thread-safe registry of connected users
  - Routes direct messages and broadcasts group messages
  - Implements the custom length-prefixed JSON protocol (protocol.py)

Architecture:
  ┌──────────────┐
  │  Main Thread  │  ← Accepts new TCP connections
  └──────┬───────┘
         │ spawns one thread per client
   ┌─────┴──────┐
   │  Thread #1  │  ← Handles Client A
   │  Thread #2  │  ← Handles Client B
   │  Thread #N  │  ← Handles Client N
   └─────────────┘

Thread Safety:
  A threading.Lock protects the shared `clients` dictionary so that
  concurrent connect / disconnect events do not corrupt the data.

Author:  [Student Name]
Course:  Computer Networks
Date:    May 2026
"""

import socket
import threading
import sys
from datetime import datetime

# Import our custom protocol module
from protocol import (
    Message, MessageType, send_message, recv_message,
    DEFAULT_HOST, DEFAULT_PORT, GROUP_RECIPIENT
)


# ========================= SERVER CLASS =========================

class ChatServer:
    """
    Multi-threaded TCP Chat Server.

    Attributes:
        host          (str):  IP address to bind to
        port          (int):  Port number to listen on
        server_socket (socket): The main listening socket
        clients       (dict):   username -> (socket, address)
        clients_lock  (Lock):   Protects the clients dictionary
        running       (bool):   Server running flag
    """

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.host = host
        self.port = port
        self.server_socket = None
        self.clients = {}                       # username -> (socket, address)
        self.clients_lock = threading.Lock()     # Thread-safe access
        self.running = False

    # -------------------- Lifecycle --------------------

    def start(self):
        """
        Initialize and start the server.

        Socket Lifecycle:
            1. socket()    – Create a TCP socket (AF_INET, SOCK_STREAM)
            2. setsockopt()– Allow address reuse for quick restarts
            3. bind()      – Attach to (host, port)
            4. listen()    – Mark socket as passive (accept connections)
            5. accept()    – Block until a client connects (loop)
        """
        # Step 1: Create a TCP/IPv4 socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Step 2: Allow port reuse (avoids "Address already in use" error)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Step 3: Bind to the specified network interface and port
        self.server_socket.bind((self.host, self.port))

        # Step 4: Start listening (backlog = 5 pending connections)
        self.server_socket.listen(5)
        self.running = True

        self._log("=" * 55)
        self._log("   INSTANT MESSAGING SERVER")
        self._log(f"   Listening on {self.host}:{self.port}")
        self._log("=" * 55)
        self._log("Waiting for client connections...\n")

        # Step 5: Main accept loop
        try:
            while self.running:
                # accept() blocks until a new client connects
                client_socket, client_address = self.server_socket.accept()
                self._log(f"[CONNECT] New connection from {client_address}")

                # Spawn a dedicated thread for this client
                thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, client_address),
                    daemon=True   # Dies when main thread exits
                )
                thread.start()

                # Show active thread count
                active = threading.active_count() - 1  # exclude main thread
                self._log(f"[THREADS] Active client threads: {active}")

        except KeyboardInterrupt:
            self._log("\n[SHUTDOWN] Server interrupted by user.")
        finally:
            self.stop()

    def stop(self):
        """Gracefully shut down the server and disconnect all clients."""
        self.running = False

        # Notify every connected client
        with self.clients_lock:
            for username, (sock, _) in self.clients.items():
                try:
                    msg = Message(MessageType.SYSTEM, "SERVER",
                                  body="Server is shutting down. Goodbye!")
                    send_message(sock, msg)
                    sock.close()
                except Exception:
                    pass
            self.clients.clear()

        # Close the listening socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass

        self._log("[SHUTDOWN] Server stopped.\n")

    # -------------------- Client Handler --------------------

    def _handle_client(self, client_socket, client_address):
        """
        Handle the full lifecycle of one connected client.

        Runs in its own thread. Steps:
            1. Wait for a LOGIN message
            2. Validate the username (non-empty, no duplicates)
            3. Register the user and broadcast the updated user list
            4. Enter the receive loop — route messages until disconnect
            5. Clean up on exit
        """
        username = None

        try:
            # ===== PHASE 1: LOGIN =====
            login_msg = recv_message(client_socket)
            if login_msg is None or login_msg.msg_type != MessageType.LOGIN:
                client_socket.close()
                return

            requested_name = login_msg.body.strip()

            # Validate: non-empty
            if not requested_name:
                self._send_login_ack(client_socket, False,
                                     "Username cannot be empty.")
                client_socket.close()
                return

            # Validate: no duplicates (thread-safe check)
            with self.clients_lock:
                if requested_name in self.clients:
                    self._send_login_ack(
                        client_socket, False,
                        f"Username '{requested_name}' is already taken."
                    )
                    client_socket.close()
                    return

                # Register the user
                username = requested_name
                self.clients[username] = (client_socket, client_address)

            # Acknowledge successful login
            self._send_login_ack(client_socket, True,
                                 f"Welcome to the chat, {username}!")
            self._log(f"[LOGIN] '{username}' logged in from {client_address}")

            # Notify everyone and refresh user lists
            self._broadcast_system(f"📢 '{username}' has joined the chat!")
            self._broadcast_user_list()

            # ===== PHASE 2: MESSAGE LOOP =====
            while self.running:
                message = recv_message(client_socket)
                if message is None:
                    break  # Client disconnected

                self._log(f"[MSG] {username} -> {message.msg_type.value}"
                          f" | to={message.recipient}"
                          f" | {message.body[:60]}")

                # Route based on message type
                if message.msg_type == MessageType.MSG:
                    self._route_direct_message(username, message)

                elif message.msg_type == MessageType.GROUP_MSG:
                    self._route_group_message(username, message)

                elif message.msg_type == MessageType.DISCONNECT:
                    break  # Graceful disconnect

        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self._log(f"[LOST] Connection lost: '{username or client_address}'")
        except Exception as e:
            self._log(f"[ERROR] Client '{username or client_address}': {e}")
        finally:
            # ===== PHASE 3: CLEANUP =====
            self._remove_client(username, client_socket)

    # -------------------- Message Routing --------------------

    def _route_direct_message(self, sender, message):
        """
        Deliver a private message from sender to one recipient.

        The message is sent to the recipient AND echoed back to the
        sender so both sides can display it in their chat windows.
        """
        recipient = message.recipient

        with self.clients_lock:
            if recipient not in self.clients:
                # Recipient is offline — notify sender
                err = Message(MessageType.ERROR, "SERVER",
                              body=f"User '{recipient}' is not online.")
                try:
                    send_message(self.clients[sender][0], err)
                except Exception:
                    pass
                return

            # Build the routed message
            routed = Message(
                msg_type  = MessageType.MSG,
                sender    = sender,
                recipient = recipient,
                body      = message.body,
                timestamp = message.timestamp,
            )

            # Send to recipient
            try:
                send_message(self.clients[recipient][0], routed)
            except Exception:
                pass

            # Echo back to sender (for display confirmation)
            try:
                send_message(self.clients[sender][0], routed)
            except Exception:
                pass

    def _route_group_message(self, sender, message):
        """
        Broadcast a message to ALL connected users (including sender).
        """
        group_msg = Message(
            msg_type  = MessageType.GROUP_MSG,
            sender    = sender,
            recipient = GROUP_RECIPIENT,
            body      = message.body,
            timestamp = message.timestamp,
        )

        with self.clients_lock:
            for uname, (sock, _) in self.clients.items():
                try:
                    send_message(sock, group_msg)
                except Exception:
                    pass

    # -------------------- Broadcasts --------------------

    def _broadcast_system(self, text):
        """Send a system notification to every connected client."""
        msg = Message(MessageType.SYSTEM, "SERVER", body=text)
        with self.clients_lock:
            for _, (sock, _) in self.clients.items():
                try:
                    send_message(sock, msg)
                except Exception:
                    pass

    def _broadcast_user_list(self):
        """Send the updated online-users list to every connected client."""
        with self.clients_lock:
            usernames = list(self.clients.keys())
            msg = Message(
                msg_type = MessageType.USER_LIST,
                sender   = "SERVER",
                body     = ",".join(usernames),
            )
            for _, (sock, _) in self.clients.items():
                try:
                    send_message(sock, msg)
                except Exception:
                    pass

    # -------------------- Helpers --------------------

    def _send_login_ack(self, sock, success, text):
        """Send a LOGIN_ACK response to a client."""
        status = "SUCCESS" if success else "FAILURE"
        ack = Message(MessageType.LOGIN_ACK, "SERVER",
                      body=f"{status}|{text}")
        send_message(sock, ack)

    def _remove_client(self, username, client_socket):
        """Remove a client from the registry and notify others."""
        try:
            client_socket.close()
        except Exception:
            pass

        if username:
            with self.clients_lock:
                self.clients.pop(username, None)

            self._log(f"[LOGOUT] '{username}' disconnected.")
            self._broadcast_system(f"👋 '{username}' has left the chat.")
            self._broadcast_user_list()

    def _log(self, text):
        """Print a timestamped log line to the console."""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {text}")


# ========================= ENTRY POINT =========================

if __name__ == "__main__":
    host = DEFAULT_HOST
    port = DEFAULT_PORT

    # Optional CLI arguments:  python chat_server.py [host] [port]
    if len(sys.argv) >= 2:
        host = sys.argv[1]
    if len(sys.argv) >= 3:
        port = int(sys.argv[2])

    server = ChatServer(host, port)
    server.start()
