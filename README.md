# ColorChat - Instant Messaging Application

A modern, real-time instant messaging application with group chat and direct messaging capabilities. Built with FastAPI (backend) and modern web technologies (frontend), featuring persistent data storage with PostgreSQL.

## 🎨 Features

### Core Messaging
- ✅ **Group Chat** - Broadcast messages to all online users
- ✅ **Direct Messaging** - Private one-on-one conversations
- ✅ **Message History** - Persistent storage of all messages
- ✅ **Message Deletion** - Users can delete their own messages
- ✅ **Real-time Updates** - WebSocket-based instant message delivery

### User Management
- ✅ **User Authentication** - Email-based login system
- ✅ **Display Names** - Customize your profile name
- ✅ **User Directory** - See all online users in real-time
- ✅ **User Profiles** - Track user information and activity

### UI/UX
- ✅ **Modern Design** - Colorful, vibrant interface with gradients and animations
- ✅ **Responsive Layout** - Works on desktop and mobile devices
- ✅ **Toast Notifications** - Real-time feedback messages
- ✅ **Connection Status** - Visual indicator of connection state
- ✅ **Message Timestamps** - Know exactly when messages were sent

### Backend
- ✅ **FastAPI** - High-performance async web framework
- ✅ **PostgreSQL** - Robust, scalable database
- ✅ **SQLAlchemy ORM** - Type-safe database operations
- ✅ **WebSocket** - Real-time bidirectional communication
- ✅ **Database Persistence** - All messages and user data are saved

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- PostgreSQL 10+
- pip (Python package manager)

### Installation

1. **Clone/Download the project**
```bash
cd windsurf-project
```

2. **Create a virtual environment** (recommended)
```bash
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Set up PostgreSQL**

Make sure PostgreSQL is installed and running. Create a new database:
```sql
CREATE DATABASE instant_messaging;
```

5. **Configure environment**

Copy `.env.example` to `.env` and update with your database credentials:
```bash
cp .env.example .env
```

Edit `.env`:
```
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/instant_messaging
```

6. **Initialize the database**

Run the database initialization script:
```bash
python database.py
```

This will create all necessary tables.

7. **Start the server**
```bash
python web_server.py
```

Or use Uvicorn directly:
```bash
uvicorn web_server:app --host 0.0.0.0 --port 8000 --reload
```

8. **Open in browser**

Navigate to: `http://localhost:8000`

## 📱 Usage

### Login
1. Enter your email address (must be valid email format)
2. (Optional) Enter a display name
3. Click "Join the Chat"

### Group Chat
- Click "👥 Group Chat" in the sidebar
- Type your message and press Enter or click Send
- Your message will be broadcast to all connected users

### Direct Messages
- Click on a user in the "Online Users" list
- Or use the "💌 Direct Messages" tab
- Type your message and send
- Messages are only visible to you and the recipient

### Delete Messages
- Hover over your messages
- Click the ✕ button to delete
- Deleted messages show as "(This message was deleted)"

### Logout
- Click the "Logout" button in the sidebar

## 🏗️ Project Structure

```
windsurf-project/
├── web_server.py          # FastAPI application with WebSocket handler
├── models.py              # SQLAlchemy database models
├── database.py            # Database configuration and initialization
├── requirements.txt       # Python dependencies
├── .env.example           # Environment variables template
├── static/
│   ├── index.html         # Main HTML page
│   ├── styles.css         # Modern colorful CSS styles
│   └── app.js             # Frontend JavaScript logic
├── user_store.json        # (Legacy) User storage
└── README.md              # This file
```

## 🗄️ Database Schema

### Users Table
- `id` - Unique user identifier (UUID)
- `email` - Email address (unique)
- `display_name` - User's display name
- `created_at` - Account creation timestamp
- `last_seen` - Last activity timestamp
- `is_active` - Account status

### Messages Table (Direct Messages)
- `id` - Message identifier (UUID)
- `sender_id` - Foreign key to Users
- `recipient_id` - Foreign key to Users
- `content` - Message text
- `created_at` - Message timestamp
- `is_deleted` - Soft delete flag
- `deleted_at` - Deletion timestamp

### GroupMessages Table
- `id` - Message identifier (UUID)
- `sender_id` - Foreign key to Users
- `content` - Message text
- `created_at` - Message timestamp
- `is_deleted` - Soft delete flag
- `deleted_at` - Deletion timestamp

## 🔧 API & WebSocket Protocol

### WebSocket Connection
**Endpoint:** `ws://localhost:8000/ws`

### Message Types

#### Client → Server

**Login:**
```json
{
  "type": "login",
  "email": "user@example.com",
  "display_name": "John Doe"
}
```

**Group Message:**
```json
{
  "type": "group-message",
  "message": "Hello everyone!"
}
```

**Direct Message:**
```json
{
  "type": "direct-message",
  "to": "recipient@example.com",
  "message": "Hello!"
}
```

**Request History:**
```json
{
  "type": "request-history",
  "scope": "group"
}
```

**Delete Message:**
```json
{
  "type": "delete-message",
  "id": "message-id",
  "scope": "group"
}
```

#### Server → Client

**Login Success:**
```json
{
  "type": "login",
  "email": "user@example.com",
  "display_name": "John Doe",
  "timestamp": "2024-05-08T12:00:00Z"
}
```

**Message:**
```json
{
  "type": "message",
  "id": "msg-id",
  "sender_email": "user@example.com",
  "sender_name": "John Doe",
  "message": "Hello!",
  "timestamp": "2024-05-08T12:00:00Z",
  "deleted": false,
  "type": "group"
}
```

**Users List:**
```json
{
  "type": "users",
  "timestamp": "2024-05-08T12:00:00Z",
  "users": [
    {
      "id": "user-id",
      "email": "user@example.com",
      "display_name": "John Doe"
    }
  ]
}
```

**Message History:**
```json
{
  "type": "history",
  "scope": "group",
  "messages": [
    {
      "id": "msg-id",
      "sender_email": "user@example.com",
      "sender_name": "John Doe",
      "message": "Hello!",
      "timestamp": "2024-05-08T12:00:00Z",
      "deleted": false,
      "type": "group"
    }
  ]
}
```

## 🎨 UI Color Scheme

- **Primary:** #6366f1 (Indigo)
- **Secondary:** #ec4899 (Pink)
- **Tertiary:** #f59e0b (Amber)
- **Success:** #10b981 (Emerald)
- **Danger:** #ef4444 (Red)
- **Warning:** #f97316 (Orange)

## 🔒 Security Notes

- Messages are validated on both client and server
- Soft deletion ensures data is never permanently lost
- Users can only delete their own messages
- Email-based identification system
- WebSocket connections are encrypted over WSS (in production)

## 🐛 Troubleshooting

### Connection Issues
- Ensure PostgreSQL is running
- Check `.env` file has correct DATABASE_URL
- Verify database exists: `createdb instant_messaging`

### Database Errors
- Run `python database.py` to reinitialize tables
- Check PostgreSQL logs for specific errors
- Ensure PostgreSQL user has proper permissions

### WebSocket Connection Failed
- Check if server is running on correct port
- Verify firewall allows WebSocket connections
- Check browser console for specific errors

## 📝 License

This project is open source and available for educational purposes.

## 👨‍💻 Development

### Running in Development Mode
```bash
uvicorn web_server:app --reload --host 0.0.0.0 --port 8000
```

### Running Tests
```bash
pytest
```

### Database Migrations
For production, consider using Alembic for database migrations:
```bash
pip install alembic
alembic init migrations
```

## 📚 Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [WebSocket Protocol](https://tools.ietf.org/html/rfc6455)

## 💡 Future Enhancements

- [ ] File sharing and media uploads
- [ ] Message reactions/emojis
- [ ] Typing indicators
- [ ] Read receipts
- [ ] Message search functionality
- [ ] User profiles and avatars
- [ ] Message pinning
- [ ] Group creation and management
- [ ] Message encryption
- [ ] Video/audio calling

---

**ColorChat** - Where conversations come alive with color! 🎨💬
#   c c n  
 