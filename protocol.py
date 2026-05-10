"""
protocol.py - Custom Application-Layer Protocol for Instant Messaging
======================================================================

This module defines the communication protocol used between client and server.
It handles message serialization, deserialization, framing, and reliable
transmission over TCP sockets.

Protocol Frame Format:
    +------------------+--------------------+
    | Length (4 bytes)  |   JSON Payload     |
    | Big-endian uint32 |   UTF-8 encoded    |
    +------------------+--------------------+

JSON Payload Structure:
    {
        "type":      "LOGIN | LOGIN_ACK | MSG | GROUP_MSG | USER_LIST | ...",
        "sender":    "<username>",
        "recipient": "<username> | __GROUP__",
        "timestamp": "YYYY-MM-DD HH:MM:SS",
        "length":    <integer - body length>,
        "body":      "<message content>"
    }

Why length-prefixed framing?
    TCP is a STREAM protocol - it does NOT preserve message boundaries.
    A single send() may arrive as multiple recv() calls, or multiple
    sends may be merged into one recv(). The 4-byte length prefix lets
    the receiver know exactly how many bytes to read for each message.

Author:  [Student Name]
Course:  Computer Networks
Date:    May 2026
"""

import json
import struct
import socket
from datetime import datetime
from enum import Enum


# ======================= CONSTANTS =======================

HEADER_SIZE = 4          # 4 bytes for the message length prefix
BUFFER_SIZE = 4096       # Maximum bytes to read per recv() call
DEFAULT_HOST = '127.0.0.1'  # Localhost (loopback address)
DEFAULT_PORT = 9000      # Default server port
ENCODING = 'utf-8'       # Character encoding for JSON payloads


# ===================== MESSAGE TYPES =====================

class MessageType(str, Enum):
    """
    Enumeration of all supported message types in the protocol.

    Each message type defines a specific action or event:
        LOGIN      - Client requests to register with a username
        LOGIN_ACK  - Server responds to login (success or failure)
        MSG        - Direct (private) message between two users
        GROUP_MSG  - Broadcast message sent to all online users
        USER_LIST  - Server sends the current list of online users
        DISCONNECT - Signals intentional disconnection
        ERROR      - Server sends an error notification
        SYSTEM     - System-level notification (join/leave events)
    """
    LOGIN      = "LOGIN"
    LOGIN_ACK  = "LOGIN_ACK"
    MSG        = "MSG"
    GROUP_MSG  = "GROUP_MSG"
    USER_LIST  = "USER_LIST"
    DISCONNECT = "DISCONNECT"
    ERROR      = "ERROR"
    SYSTEM     = "SYSTEM"


# Special recipient identifier for group (broadcast) messages
GROUP_RECIPIENT = "__GROUP__"


# ==================== MESSAGE CLASS ======================

class Message:
    """
    Represents a single protocol message.

    Attributes:
        msg_type  (str): Type of the message (from MessageType enum)
        sender    (str): Username of the sender
        recipient (str): Username of the recipient, or GROUP_RECIPIENT
        timestamp (str): Human-readable timestamp string
        body      (str): The actual message content
    """

    def __init__(self, msg_type, sender="", recipient="", body="", timestamp=None):
        self.msg_type  = msg_type
        self.sender    = sender
        self.recipient = recipient
        self.body      = body
        self.timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---------- Serialization ----------

    def to_dict(self):
        """Convert the message to a plain dictionary."""
        return {
            "type":      self.msg_type,
            "sender":    self.sender,
            "recipient": self.recipient,
            "timestamp": self.timestamp,
            "length":    len(self.body),
            "body":      self.body,
        }

    def to_json(self):
        """Serialize the message to a JSON string."""
        return json.dumps(self.to_dict())

    # ---------- Deserialization ----------

    @classmethod
    def from_dict(cls, data):
        """Create a Message from a dictionary."""
        return cls(
            msg_type  = data.get("type", ""),
            sender    = data.get("sender", ""),
            recipient = data.get("recipient", ""),
            body      = data.get("body", ""),
            timestamp = data.get("timestamp"),
        )

    @classmethod
    def from_json(cls, json_str):
        """Create a Message from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    def __repr__(self):
        return (f"Message(type={self.msg_type}, sender={self.sender}, "
                f"recipient={self.recipient}, body={self.body[:30]}...)")


# ============= NETWORK SEND / RECEIVE HELPERS =============

def send_message(sock, message):
    """
    Send a Message over a TCP socket using length-prefixed framing.

    Steps:
        1. Serialize Message -> JSON string -> UTF-8 bytes
        2. Pack the byte-length as a 4-byte big-endian unsigned int
        3. Send [length_header + json_bytes] atomically via sendall()

    Args:
        sock    (socket.socket): The TCP socket to send on
        message (Message):       The Message object to transmit

    Raises:
        ConnectionError: If the socket is closed or broken
    """
    # Serialize to bytes
    json_bytes = message.to_json().encode(ENCODING)

    # Create 4-byte length header  ('!' = network byte order, 'I' = unsigned int)
    length_header = struct.pack('!I', len(json_bytes))

    # sendall() guarantees all bytes are transmitted
    sock.sendall(length_header + json_bytes)


def recv_message(sock):
    """
    Receive a complete Message from a TCP socket.

    Handles TCP stream semantics by:
        1. Reading exactly 4 bytes  -> message length
        2. Reading exactly N bytes  -> JSON payload
        3. Deserializing JSON back into a Message object

    Returns:
        Message object, or None if the connection was closed.
    """
    # Step 1: Read the 4-byte length header
    header = _recv_exact(sock, HEADER_SIZE)
    if header is None:
        return None  # Connection closed gracefully

    # Step 2: Unpack the length
    msg_length = struct.unpack('!I', header)[0]

    # Safety: reject messages larger than 10 MB
    if msg_length > 10 * 1024 * 1024:
        raise ValueError(f"Message too large: {msg_length} bytes")

    # Step 3: Read the full JSON payload
    payload = _recv_exact(sock, msg_length)
    if payload is None:
        return None  # Connection closed mid-message

    # Step 4: Decode and deserialize
    return Message.from_json(payload.decode(ENCODING))


def _recv_exact(sock, num_bytes):
    """
    Read exactly `num_bytes` from a TCP socket.

    Why this is needed:
        TCP is a byte-stream protocol.  A single recv() call may return
        fewer bytes than requested (partial read).  This function loops
        until ALL requested bytes have been accumulated.

    Args:
        sock      (socket.socket): The TCP socket
        num_bytes (int):           Exact number of bytes to read

    Returns:
        bytes of length `num_bytes`, or None if the peer closed the connection.
    """
    data = b''
    while len(data) < num_bytes:
        remaining = num_bytes - len(data)
        chunk = sock.recv(min(remaining, BUFFER_SIZE))
        if not chunk:
            # Empty bytes means the remote side closed the connection
            return None
        data += chunk
    return data
