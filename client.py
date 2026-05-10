import socket
import threading
import json
from datetime import datetime, timezone


def utc_iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def encode_json_line(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def receiver_loop(sock: socket.socket, stop_event: threading.Event) -> None:
    buffer = b""
    try:
        while not stop_event.is_set():
            chunk = sock.recv(4096)
            if not chunk:
                print("[CLIENT] Server closed connection")
                stop_event.set()
                return

            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue

                try:
                    payload = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    print("[CLIENT] Received invalid JSON")
                    continue

                sender = payload.get("sender", "?")
                ts = payload.get("timestamp", "")
                msg = payload.get("message", "")
                print(f"[{ts}] {sender}: {msg}")
    except OSError:
        stop_event.set()


def main() -> None:
    host = "127.0.0.1"
    port = 5000

    email = input("Email: ").strip().lower()
    if not email or "@" not in email:
        print("Email is required and must be valid")
        return

    display_name = input("Display name (optional): ").strip()
    if not display_name:
        display_name = email.split("@", 1)[0]

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))

    stop_event = threading.Event()

    # Step 3: send login first
    sock.sendall(
        encode_json_line({"type": "login", "email": email, "display_name": display_name})
    )

    t = threading.Thread(target=receiver_loop, args=(sock, stop_event), daemon=True)
    t.start()

    try:
        while not stop_event.is_set():
            text = input()
            if text.strip().lower() in {"/quit", "/exit"}:
                stop_event.set()
                break

            payload = {
                "type": "message",
                "sender": display_name,
                "timestamp": utc_iso_timestamp(),
                "message": text,
            }
            try:
                sock.sendall(encode_json_line(payload))
            except OSError:
                print("[CLIENT] Failed to send (disconnected)")
                stop_event.set()
                break
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
