import json
from datetime import datetime
from typing import Dict, Optional, List
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import SessionLocal, init_db, engine
from models import User, Message, GroupMessage


def utc_iso_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


# Initialize database on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    init_db()
    print("[SERVER] Database initialized!")
    yield
    # Shutdown
    print("[SERVER] Shutting down...")


app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


class Connection:
    """Represents a WebSocket connection from a client."""
    def __init__(self, *, ws: WebSocket, email: str, display_name: str, user_id: str):
        self.ws = ws
        self.email = email
        self.display_name = display_name
        self.user_id = user_id


class ChatHub:
    """Central hub for managing all chat connections and message routing."""
    
    def __init__(self, db: Session):
        self._clients: Dict[str, Connection] = {}
        self._db = db
        self._max_history = 300

    def users_payload(self) -> dict:
        """Create a payload with all connected users."""
        return {
            "type": "users",
            "timestamp": utc_iso_timestamp(),
            "users": [
                {"email": c.email, "display_name": c.display_name, "id": c.user_id}
                for c in self._clients.values()
            ],
        }

    async def broadcast_users(self) -> None:
        """Broadcast user list to all connected clients."""
        await self.broadcast_json(self.users_payload())

    async def broadcast_json(self, payload: dict, *, exclude_email: Optional[str] = None) -> None:
        """Broadcast a JSON payload to all clients except optionally excluded email."""
        dead = []
        msg = json.dumps(payload, ensure_ascii=False)
        for email, c in list(self._clients.items()):
            if exclude_email and email == exclude_email:
                continue
            try:
                await c.ws.send_text(msg)
            except Exception as e:
                print(f"[ERROR] Failed to send to {email}: {e}")
                dead.append(email)

        for email in dead:
            self._clients.pop(email, None)

    async def send_direct(self, to_email: str, payload: dict) -> bool:
        """Send a message directly to a specific user."""
        c = self._clients.get(to_email)
        if not c:
            return False
        try:
            await c.ws.send_text(json.dumps(payload, ensure_ascii=False))
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send direct message to {to_email}: {e}")
            self._clients.pop(to_email, None)
            return False

    async def add_group_message(self, sender_email: str, sender_id: str, message: str) -> dict:
        """Add a group message and store in database."""
        connection = self._clients.get(sender_email)
        sender_name = connection.display_name if connection else sender_email
        
        msg_dict = {
            "id": str(uuid.uuid4()),
            "sender_email": sender_email,
            "sender_name": sender_name,
            "message": message,
            "timestamp": utc_iso_timestamp(),
            "type": "group",
            "deleted": False,
        }
        
        # Store in database
        try:
            group_msg = GroupMessage(
                id=msg_dict["id"],
                sender_id=sender_id,
                content=message,
            )
            self._db.add(group_msg)
            self._db.commit()
        except Exception as e:
            print(f"[ERROR] Failed to save group message: {e}")
            self._db.rollback()
        
        return msg_dict

    async def add_dm_message(self, sender_email: str, sender_id: str, recipient_email: str, 
                            recipient_id: str, message: str) -> dict:
        """Add a direct message and store in database."""
        connection = self._clients.get(sender_email)
        sender_name = connection.display_name if connection else sender_email
        
        msg_dict = {
            "id": str(uuid.uuid4()),
            "sender_email": sender_email,
            "sender_name": sender_name,
            "message": message,
            "timestamp": utc_iso_timestamp(),
            "type": "dm",
            "deleted": False,
        }
        
        # Store in database
        try:
            dm = Message(
                id=msg_dict["id"],
                sender_id=sender_id,
                recipient_id=recipient_id,
                content=message,
            )
            self._db.add(dm)
            self._db.commit()
        except Exception as e:
            print(f"[ERROR] Failed to save DM: {e}")
            self._db.rollback()
        
        return msg_dict

    def get_group_history(self, limit: int = 50) -> List[dict]:
        """Get group message history from database."""
        try:
            messages = self._db.query(GroupMessage).order_by(GroupMessage.created_at.desc()).limit(limit).all()
            return [msg.to_dict() for msg in reversed(messages)]
        except Exception as e:
            print(f"[ERROR] Failed to retrieve group history: {e}")
            return []

    def get_dm_history(self, user1_email: str, user2_email: str, limit: int = 50) -> List[dict]:
        """Get DM history between two users from database."""
        try:
            # Get user IDs
            user1 = self._db.query(User).filter(User.email == user1_email).first()
            user2 = self._db.query(User).filter(User.email == user2_email).first()
            
            if not user1 or not user2:
                return []
            
            messages = self._db.query(Message).filter(
                (
                    (Message.sender_id == user1.id) & (Message.recipient_id == user2.id)
                ) | (
                    (Message.sender_id == user2.id) & (Message.recipient_id == user1.id)
                )
            ).order_by(Message.created_at.desc()).limit(limit).all()
            
            return [msg.to_dict() for msg in reversed(messages)]
        except Exception as e:
            print(f"[ERROR] Failed to retrieve DM history: {e}")
            return []

    async def delete_message(self, *, scope: str, message_id: str, requester_email: str, 
                            peer_email: Optional[str] = None) -> bool:
        """Delete a message (mark as deleted in database)."""
        try:
            if scope == "group":
                msg = self._db.query(GroupMessage).filter(GroupMessage.id == message_id).first()
                if msg and msg.sender.email == requester_email:
                    msg.is_deleted = True
                    msg.deleted_at = datetime.utcnow()
                    self._db.commit()
                    return True
            elif scope == "direct" and peer_email:
                msg = self._db.query(Message).filter(Message.id == message_id).first()
                if msg and msg.sender.email == requester_email:
                    msg.is_deleted = True
                    msg.deleted_at = datetime.utcnow()
                    self._db.commit()
                    return True
        except Exception as e:
            print(f"[ERROR] Failed to delete message: {e}")
            self._db.rollback()
        
        return False


# Global chat hub
chat_hub: Optional[ChatHub] = None


@app.get("/")
def index():
    """Serve the main HTML page."""
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for chat connections."""
    await websocket.accept()
    
    # Get database session
    db = SessionLocal()
    
    connection = None
    user_email = None

    try:
        # First message should be login with email and display_name
        login_msg = await websocket.receive_text()
        login_data = json.loads(login_msg)
        
        user_email = login_data.get("email", "").strip().lower()
        display_name = login_data.get("display_name", "").strip()
        
        if not user_email or "@" not in user_email:
            await websocket.send_text(
                json.dumps({"type": "error", "message": "Invalid email"}, ensure_ascii=False)
            )
            await websocket.close()
            db.close()
            return

        # Get or create user in database
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            user = User(
                email=user_email,
                display_name=display_name or user_email,
            )
            db.add(user)
            db.commit()
        else:
            # Update display name and last seen
            user.display_name = display_name or user.display_name
            user.last_seen = datetime.utcnow()
            db.commit()

        # Create connection
        connection = Connection(
            ws=websocket,
            email=user_email,
            display_name=user.display_name,
            user_id=user.id,
        )

        # Initialize chat hub if not already done
        global chat_hub
        if chat_hub is None:
            chat_hub = ChatHub(db)

        # Add connection to hub
        chat_hub._clients[user_email] = connection

        # Send confirmation and user list
        await websocket.send_text(
            json.dumps({
                "type": "login",
                "email": user_email,
                "display_name": user.display_name,
                "timestamp": utc_iso_timestamp(),
            }, ensure_ascii=False)
        )

        # Broadcast updated user list
        await chat_hub.broadcast_users()

        # Send history to new connection
        group_history = chat_hub.get_group_history()
        await websocket.send_text(
            json.dumps({
                "type": "history",
                "scope": "group",
                "messages": group_history,
                "timestamp": utc_iso_timestamp(),
            }, ensure_ascii=False)
        )

        # Main message loop
        while True:
            msg = await websocket.receive_text()
            data = json.loads(msg)
            msg_type = data.get("type")

            if msg_type == "group-message":
                # Group message
                message_text = data.get("message", "").strip()
                if message_text:
                    msg_dict = await chat_hub.add_group_message(
                        user_email, user.id, message_text
                    )
                    await chat_hub.broadcast_json({
                        "type": "message",
                        **msg_dict,
                    })

            elif msg_type == "direct-message":
                # Direct message
                to_email = data.get("to", "").strip().lower()
                message_text = data.get("message", "").strip()
                
                if to_email and message_text:
                    recipient = db.query(User).filter(User.email == to_email).first()
                    if recipient:
                        msg_dict = await chat_hub.add_dm_message(
                            user_email, user.id, to_email, recipient.id, message_text
                        )
                        
                        # Send to recipient if online
                        await chat_hub.send_direct(to_email, {
                            "type": "message",
                            **msg_dict,
                        })
                        
                        # Echo back to sender
                        await websocket.send_text(
                            json.dumps({
                                "type": "message",
                                **msg_dict,
                            }, ensure_ascii=False)
                        )

            elif msg_type == "request-history":
                # Client requesting message history
                scope = data.get("scope", "group")
                
                if scope == "group":
                    history = chat_hub.get_group_history()
                else:
                    to_email = data.get("to", "").strip().lower()
                    history = chat_hub.get_dm_history(user_email, to_email)
                
                await websocket.send_text(
                    json.dumps({
                        "type": "history",
                        "scope": scope,
                        "to": data.get("to"),
                        "messages": history,
                        "timestamp": utc_iso_timestamp(),
                    }, ensure_ascii=False)
                )

            elif msg_type == "delete-message":
                # Delete message
                message_id = data.get("id")
                scope = data.get("scope", "group")
                to_email = data.get("to")
                
                success = await chat_hub.delete_message(
                    scope=scope,
                    message_id=message_id,
                    requester_email=user_email,
                    peer_email=to_email,
                )
                
                if success:
                    await chat_hub.broadcast_json({
                        "type": "message-deleted",
                        "id": message_id,
                        "scope": scope,
                        "timestamp": utc_iso_timestamp(),
                    })

    except WebSocketDisconnect:
        print(f"[INFO] {user_email} disconnected")
        if user_email:
            chat_hub._clients.pop(user_email, None)
            if chat_hub:
                await chat_hub.broadcast_users()
    except Exception as e:
        print(f"[ERROR] WebSocket error: {e}")
    finally:
        db.close()
        if connection:
            try:
                await websocket.close()
            except:
                pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
