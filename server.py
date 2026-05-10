import socket
import threading
import json
from datetime import datetime, timezone
import uuid


def utc_iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def encode_json_line(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


class ChatServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 5000):
        self.host = host
        self.port = port

        self._server_socket: socket.socket | None = None

        # email -> {"socket": socket.socket, "display_name": str}
        self._clients: dict[str, dict] = {}
        self._clients_lock = threading.Lock()

        self._history_lock = threading.Lock()
        self._group_history: list[dict] = []
        self._dm_history: dict[tuple[str, str], list[dict]] = {}
        self._max_history = 300

        self._shutdown_event = threading.Event()

    def start(self) -> None:
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen()

        print(f"[SERVER] Listening on {self.host}:{self.port}", flush=True)

        try:
            while not self._shutdown_event.is_set():
                client_socket, client_addr = self._server_socket.accept()
                print(f"[SERVER] Connection from {client_addr}", flush=True)

                t = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, client_addr),
                    daemon=True,
                )
                t.start()
        except KeyboardInterrupt:
            print("\n[SERVER] Shutting down...")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._shutdown_event.set()

        with self._clients_lock:
            for username, sock in list(self._clients.items()):
                try:
                    sock["socket"].shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock["socket"].close()
                except OSError:
                    pass
                self._clients.pop(username, None)

        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None

    def _send_to(self, client_socket: socket.socket, payload: dict) -> None:
        client_socket.sendall(encode_json_line(payload))

    def _history_key(self, a: str, b: str) -> tuple[str, str]:
        return tuple(sorted((a, b)))

    def _trim(self, items: list[dict]) -> None:
        if len(items) > self._max_history:
            del items[: len(items) - self._max_history]

    def _add_group_message(self, msg: dict) -> None:
        with self._history_lock:
            self._group_history.append(msg)
            self._trim(self._group_history)

    def _add_dm_message(self, a: str, b: str, msg: dict) -> None:
        key = self._history_key(a, b)
        with self._history_lock:
            if key not in self._dm_history:
                self._dm_history[key] = []
            self._dm_history[key].append(msg)
            self._trim(self._dm_history[key])

    def _get_group_history(self) -> list[dict]:
        with self._history_lock:
            return list(self._group_history)

    def _get_dm_history(self, a: str, b: str) -> list[dict]:
        key = self._history_key(a, b)
        with self._history_lock:
            return list(self._dm_history.get(key, []))

    def _delete_message(self, *, scope: str, message_id: str, requester_email: str, peer_email: str | None = None) -> bool:
        with self._history_lock:
            if scope == "group":
                items = self._group_history
            elif scope == "direct" and peer_email:
                items = self._dm_history.get(self._history_key(requester_email, peer_email), [])
            else:
                return False

            for m in items:
                if m.get("id") == message_id:
                    if m.get("sender_email") != requester_email:
                        return False
                    m["deleted"] = True
                    m["message"] = ""
                    return True
        return False

    def _broadcast_user_list(self) -> None:
        with self._clients_lock:
            users = [
                {"email": email, "display_name": entry.get("display_name", "")}
                for email, entry in self._clients.items()
            ]

        payload = {
            "type": "users",
            "timestamp": utc_iso_timestamp(),
            "users": users,
        }
        self._broadcast(payload)

    def _send_user_list_to(self, client_socket: socket.socket) -> None:
        with self._clients_lock:
            users = [
                {"email": email, "display_name": entry.get("display_name", "")}
                for email, entry in self._clients.items()
            ]

        self._send_to(
            client_socket,
            {
                "type": "users",
                "timestamp": utc_iso_timestamp(),
                "users": users,
            },
        )

    def _send_direct(self, to_email: str, payload: dict) -> bool:
        with self._clients_lock:
            entry = self._clients.get(to_email)
        if not entry:
            return False
        try:
            entry["socket"].sendall(encode_json_line(payload))
            return True
        except OSError:
            self._remove_client(to_email)
            return False

    def _broadcast(self, payload: dict, *, exclude_username: str | None = None) -> None:
        data = encode_json_line(payload)

        with self._clients_lock:
            items = list(self._clients.items())

        for email, entry in items:
            if exclude_username is not None and email == exclude_username:
                continue
            try:
                entry["socket"].sendall(data)
            except OSError:
                # If a send fails, treat it as a disconnect and cleanup.
                self._remove_client(email)

    def _remove_client(self, email: str) -> None:
        entry: dict | None = None
        with self._clients_lock:
            entry = self._clients.pop(email, None)

        if entry is None:
            return

        sock = entry.get("socket")
        display_name = entry.get("display_name", email)

        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

        leave_notice = {
            "sender": "SERVER",
            "timestamp": utc_iso_timestamp(),
            "message": f"{display_name} left the chat.",
        }
        self._broadcast(leave_notice)
        self._broadcast_user_list()
        print(f"[SERVER] {display_name} <{email}> disconnected", flush=True)

    def _read_json_lines(self, client_socket: socket.socket):
        buffer = b""
        while True:
            chunk = client_socket.recv(4096)
            if not chunk:
                return

            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue

                try:
                    payload = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    yield {"_bad_json": True}
                    continue

                yield payload

    def _handle_client(self, client_socket: socket.socket, client_addr) -> None:
        email: str | None = None
        display_name: str | None = None

        try:
            # Step 3: Username-based login handshake.
            # The first message MUST be: {"type":"login","username":"..."}
            login_payload = None
            for payload in self._read_json_lines(client_socket):
                login_payload = payload
                break

            if not isinstance(login_payload, dict) or login_payload.get("type") != "login":
                self._send_to(
                    client_socket,
                    {
                        "type": "error",
                        "sender": "SERVER",
                        "timestamp": utc_iso_timestamp(),
                        "message": "First message must be a login payload.",
                    },
                )
                return

            requested_email = str(login_payload.get("email", "")).strip().lower()
            requested_name = str(login_payload.get("display_name", "")).strip()

            if not requested_email or "@" not in requested_email:
                self._send_to(
                    client_socket,
                    {
                        "type": "error",
                        "sender": "SERVER",
                        "timestamp": utc_iso_timestamp(),
                        "message": "Email is required and must be valid.",
                    },
                )
                return

            if not requested_name:
                requested_name = requested_email.split("@", 1)[0]

            with self._clients_lock:
                if requested_email in self._clients:
                    self._send_to(
                        client_socket,
                        {
                            "type": "error",
                            "sender": "SERVER",
                            "timestamp": utc_iso_timestamp(),
                            "message": "Email already logged in.",
                        },
                    )
                    return

                self._clients[requested_email] = {"socket": client_socket, "display_name": requested_name}
                email = requested_email
                display_name = requested_name

            self._send_to(
                client_socket,
                {
                    "type": "welcome",
                    "email": email,
                    "display_name": display_name,
                    "sender": "SERVER",
                    "timestamp": utc_iso_timestamp(),
                    "message": f"Welcome, {display_name}!",
                },
            )

            self._send_to(
                client_socket,
                {
                    "type": "history",
                    "scope": "group",
                    "key": "group",
                    "timestamp": utc_iso_timestamp(),
                    "messages": self._get_group_history(),
                },
            )

            self._send_user_list_to(client_socket)

            join_notice = {
                "sender": "SERVER",
                "timestamp": utc_iso_timestamp(),
                "message": f"{display_name} joined the chat.",
            }
            self._broadcast(join_notice, exclude_username=email)
            self._broadcast_user_list()
            print(f"[SERVER] {display_name} <{email}> logged in from {client_addr}", flush=True)

            # Step 4: Broadcast messages to all users.
            for payload in self._read_json_lines(client_socket):
                if payload.get("_bad_json"):
                    self._send_to(
                        client_socket,
                        {
                            "sender": "SERVER",
                            "timestamp": utc_iso_timestamp(),
                            "message": "Invalid JSON received. Messages must be JSON.",
                        },
                    )
                    continue

                if not isinstance(payload, dict):
                    continue

                if payload.get("type") == "message":
                    msg = str(payload.get("message", ""))
                    if not msg.strip():
                        continue

                    client_id = str(payload.get("client_id", "")).strip()
                    msg_id = client_id if client_id else uuid.uuid4().hex

                    outgoing = {
                        "type": "message",
                        "id": msg_id,
                        "sender": display_name,
                        "sender_email": email,
                        "timestamp": utc_iso_timestamp(),
                        "message": msg,
                        "deleted": False,
                    }
                    self._add_group_message(outgoing)
                    self._broadcast(outgoing)
                elif payload.get("type") == "direct":
                    to_email = str(payload.get("to", "")).strip().lower()
                    msg = str(payload.get("message", ""))
                    if not to_email or "@" not in to_email or not msg.strip():
                        continue

                    client_id = str(payload.get("client_id", "")).strip()
                    msg_id = client_id if client_id else uuid.uuid4().hex

                    outgoing = {
                        "type": "direct",
                        "id": msg_id,
                        "sender": display_name,
                        "sender_email": email,
                        "to": to_email,
                        "timestamp": utc_iso_timestamp(),
                        "message": msg,
                        "deleted": False,
                    }

                    self._add_dm_message(email, to_email, outgoing)

                    ok = self._send_direct(to_email, outgoing)
                    # Echo to sender for inbox/history consistency
                    try:
                        self._send_to(client_socket, outgoing)
                    except OSError:
                        pass
                    if not ok:
                        self._send_to(
                            client_socket,
                            {
                                "sender": "SERVER",
                                "timestamp": utc_iso_timestamp(),
                                "message": f"User offline or unknown: {to_email}",
                            },
                        )
                elif payload.get("type") == "list_users":
                    self._send_user_list_to(client_socket)
                elif payload.get("type") == "history":
                    scope = str(payload.get("scope", "")).strip()
                    if scope == "group":
                        self._send_to(
                            client_socket,
                            {
                                "type": "history",
                                "scope": "group",
                                "key": "group",
                                "timestamp": utc_iso_timestamp(),
                                "messages": self._get_group_history(),
                            },
                        )
                    elif scope == "direct":
                        peer = str(payload.get("peer", "")).strip().lower()
                        if not peer or "@" not in peer:
                            continue
                        self._send_to(
                            client_socket,
                            {
                                "type": "history",
                                "scope": "direct",
                                "key": peer,
                                "timestamp": utc_iso_timestamp(),
                                "messages": self._get_dm_history(email, peer),
                            },
                        )
                elif payload.get("type") == "delete":
                    scope = str(payload.get("scope", "")).strip()
                    message_id = str(payload.get("id", "")).strip()
                    peer = str(payload.get("peer", "")).strip().lower() if payload.get("peer") else None
                    if not message_id:
                        continue

                    ok = self._delete_message(scope=scope, message_id=message_id, requester_email=email, peer_email=peer)
                    if not ok:
                        self._send_to(
                            client_socket,
                            {
                                "type": "error",
                                "sender": "SERVER",
                                "timestamp": utc_iso_timestamp(),
                                "message": "Delete failed (not found or not permitted)",
                            },
                        )
                        continue

                    deleted_evt = {
                        "type": "deleted",
                        "scope": scope,
                        "id": message_id,
                        "timestamp": utc_iso_timestamp(),
                    }

                    if scope == "group":
                        self._broadcast(deleted_evt)
                    elif scope == "direct" and peer:
                        # Notify both parties
                        self._send_to(client_socket, deleted_evt)
                        self._send_direct(peer, deleted_evt)
                else:
                    # Ignore unknown message types.
                    continue

        except ConnectionResetError:
            pass
        except OSError:
            pass
        finally:
            if email is not None:
                self._remove_client(email)
            else:
                try:
                    client_socket.close()
                except OSError:
                    pass


if __name__ == "__main__":
    ChatServer(host="127.0.0.1", port=5000).start()
