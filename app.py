"""
app.py — Flask-SocketIO Chat Server (Secure + Media)
======================================================
Features: Group chat, Direct messaging, Inbox, Read receipts,
          Message search, Privacy mode, Online tracking,
          Password Security, Image Uploads.
"""

import eventlet
eventlet.monkey_patch()

import os
import uuid
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect

from server.database import (
    init_db, save_message, get_group_history, get_dm_history,
    get_inbox, get_unread_total, mark_read, search_messages,
    create_user, get_user_hash, create_chat_group, delete_chat_group, get_all_groups, delete_message
)
from server.auth import is_username_taken, register_user, remove_user, get_online_users
import logging
from datetime import datetime

# ─── App Setup ─────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = 'ccn-im-secret-2026-secure'
DATA_DIR = os.environ.get('DATA_DIR', os.path.dirname(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(DATA_DIR, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024 # 1 GB max upload

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] %(levelname)s: %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger(__name__)

init_db()
log.info("Database initialized.")


# ─── HTTP Routes ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        action = request.form.get('action', 'login')

        if not username or not password:
            error = 'Username and password are required.'
        elif len(username) > 20:
            error = 'Username must be 20 characters or less.'
        elif not username.replace('_', '').isalnum():
            error = 'Only letters, numbers, and underscores allowed in username.'
        else:
            if action == 'register':
                # Register a new user
                hashed = generate_password_hash(password)
                if create_user(username, hashed):
                    error = 'Registration successful! You can now log in.'
                else:
                    error = 'Username already exists. Please log in or choose another.'
            elif action == 'login':
                # Login existing user
                saved_hash = get_user_hash(username)
                if saved_hash and check_password_hash(saved_hash, password):
                    if is_username_taken(username):
                        error = f'"{username}" is already online elsewhere.'
                    else:
                        session['username'] = username
                        register_user(username)
                        log.info(f"User '{username}' logged in securely.")
                        return redirect(url_for('chat'))
                else:
                    error = 'Invalid username or password.'

    return render_template('login.html', error=error)


@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('chat.html', username=session['username'])


@app.route('/logout')
def logout():
    username = session.pop('username', None)
    if username:
        remove_user(username)
        log.info(f"User '{username}' logged out.")
    return redirect(url_for('login'))


# --- Image & Media Upload Endpoint ---
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'webm', 'ogg', 'mp3', 'wav', 'm4a'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    if 'image' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        
        image_url = f"/static/uploads/{unique_filename}"
        return jsonify({'image_url': image_url}), 200
        
    return jsonify({'error': 'Invalid file type'}), 400


# ─── REST API Endpoints ───────────────────────────────────────────────────

@app.route('/api/history/group/<path:group_name>')
def api_group_history(group_name):
    return jsonify(get_group_history(group_name=group_name, limit=100))

@app.route('/api/groups')
def api_groups():
    return jsonify(get_all_groups())

@app.route('/api/history/dm/<other_user>')
def api_dm_history(other_user):
    username = session.get('username')
    if not username:
        return jsonify([])
    return jsonify(get_dm_history(username, other_user, limit=100))

@app.route('/api/inbox')
def api_inbox():
    username = session.get('username')
    if not username:
        return jsonify([])
    return jsonify(get_inbox(username))

@app.route('/api/unread')
def api_unread():
    username = session.get('username')
    if not username:
        return jsonify({'count': 0})
    return jsonify({'count': get_unread_total(username)})

@app.route('/api/search')
def api_search():
    username = session.get('username')
    q = request.args.get('q', '').strip()
    if not username or not q:
        return jsonify([])
    return jsonify(search_messages(username, q))

@app.route('/api/users')
def api_users():
    return jsonify({'users': get_online_users()})


# ─── WebSocket Events ─────────────────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    username = session.get('username')
    if not username:
        disconnect()
        return
    log.info(f"[WS] '{username}' connected (sid={request.sid})")
    join_room('group')
    _broadcast_user_list()
    _broadcast_groups()
    socketio.emit('system', {
        'body': f'Welcome to Secure InstantChat, {username}!',
        'timestamp': _now()
    }, to=request.sid)
    socketio.emit('system', {
        'body': f'👋 {username} joined the chat!',
        'timestamp': _now()
    }, room='group', include_self=False)

@socketio.on('disconnect')
def on_disconnect():
    username = session.get('username')
    if not username:
        return
    log.info(f"[WS] '{username}' disconnected")
    remove_user(username)
    socketio.emit('system', {
        'body': f'👋 {username} left the chat.',
        'timestamp': _now()
    }, room='group')
    _broadcast_user_list()

@socketio.on('join_personal_room')
def on_join_personal_room():
    username = session.get('username')
    if username:
        join_room(f'user_{username}')

@socketio.on('join_room')
def on_join_room(data):
    room = data.get('room')
    if room and room.startswith('#'):
        join_room(room)

@socketio.on('group_message')
def on_group_message(data):
    username = session.get('username')
    if not username:
        return
    body = data.get('body', '').strip()
    image_url = data.get('image_url', None)
    room_name = data.get('room', '__GROUP__')
    
    if not body and not image_url:
        return
    if len(body) > 2000:
        return
        
    
    ts = _now()
    msg_id = save_message(sender=username, recipient=room_name, body=body, image_url=image_url, timestamp=ts)
    log.info(f"[{room_name}] {username}: {body[:60]} (Media: {image_url})")
    
    socketio.emit('group_message', {
        'id': msg_id,
        'sender': username,
        'room': room_name,
        'body': body,
        'image_url': image_url,
        'timestamp': ts,
    }, room=room_name)

@socketio.on('create_group')
def on_create_group(data):
    username = session.get('username')
    name = data.get('name', '').strip()
    if not username or not name: return
    
    new_name = create_chat_group(name, username)
    if new_name:
        _broadcast_groups()
        socketio.emit('system', {'body': f"Group {new_name} created by {username}."}, room='group')

@socketio.on('delete_group')
def on_delete_group(data):
    username = session.get('username')
    name = data.get('name', '').strip()
    if not username or not name: return
    
    if delete_chat_group(name, username):
        _broadcast_groups()
        socketio.emit('group_deleted', {'name': name})
        socketio.emit('system', {'body': f"Group {name} was deleted."}, room='group')

@socketio.on('delete_message')
def on_delete_msg(data):
    username = session.get('username')
    msg_id = data.get('id')
    room = data.get('room')
    if not username or not msg_id: return
    
    delete_message(msg_id, username)
    
    if room and room.startswith('#'):
        socketio.emit('message_deleted', {'id': msg_id, 'room': room}, room=room)
    elif room:
        socketio.emit('message_deleted', {'id': msg_id, 'room': room}, room=f'user_{room}')
        socketio.emit('message_deleted', {'id': msg_id, 'room': username}, room=f'user_{username}')
    else:
        socketio.emit('message_deleted', {'id': msg_id, 'room': '__GROUP__'}, room='group')

@socketio.on('direct_message')
def on_direct_message(data):
    sender = session.get('username')
    if not sender:
        return
    recipient = data.get('to', '').strip()
    body = data.get('body', '').strip()
    image_url = data.get('image_url', None)
    private = data.get('private', False)
    
    if not recipient or (not body and not image_url) or len(body) > 2000:
        return
        
    ts = _now()
    msg_id = save_message(sender=sender, recipient=recipient, body=body, image_url=image_url,
                 timestamp=ts, encrypted=private)
    log.info(f"[DM] {sender} → {recipient}: {body[:60]} (Media: {image_url})")

    payload = {
        'id': msg_id,
        'sender': sender,
        'recipient': recipient,
        'body': body,
        'image_url': image_url,
        'timestamp': ts,
        'private': private,
    }
    socketio.emit('direct_message', payload, room=f'user_{recipient}')
    if sender != recipient:
        socketio.emit('direct_message', payload, room=f'user_{sender}')

    socketio.emit('inbox_update', {}, room=f'user_{recipient}')

@socketio.on('mark_read')
def on_mark_read(data):
    username = session.get('username')
    partner = data.get('partner', '')
    if username and partner:
        mark_read(sender=partner, recipient=username)
        socketio.emit('read_receipt', {
            'reader': username
        }, room=f'user_{partner}')

@socketio.on('typing')
def on_typing(data):
    username = session.get('username')
    if not username:
        return
    recipient = data.get('to', '__GROUP__')
    if recipient == '__GROUP__':
        socketio.emit('typing', {'user': username}, room='group', include_self=False)
    else:
        socketio.emit('typing', {'user': username}, room=f'user_{recipient}')


# ─── Helpers ───────────────────────────────────────────────────────────────

def _broadcast_user_list():
    users = get_online_users()
    socketio.emit('user_list', {'users': users}, room='group')

def _broadcast_groups():
    groups = get_all_groups()
    socketio.emit('group_list', {'groups': groups}, room='group')

def _now():
    return datetime.now().strftime('%H:%M')


# ─── Entry Point ───────────────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("Starting Secure InstantChat Server...")
    log.info("Open http://localhost:5000 in your browser")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
