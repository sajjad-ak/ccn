#!/usr/bin/env python
"""
Quick setup script for ColorChat
Run this after PostgreSQL is installed and database is created
"""

import subprocess
import sys
import os

def run_command(cmd, description):
    """Run a shell command and print status"""
    print(f"\n📦 {description}...")
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(e.stderr)
        return False

def main():
    print("""
    ╔═══════════════════════════════════════════╗
    ║        ColorChat Setup Script             ║
    ║      Real-time Messaging Application      ║
    ╚═══════════════════════════════════════════╝
    """)

    # Step 1: Check Python version
    print(f"🐍 Python version: {sys.version}")
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ is required")
        sys.exit(1)

    # Step 2: Install dependencies
    if not run_command(
        f"{sys.executable} -m pip install -r requirements.txt",
        "Installing Python dependencies"
    ):
        print("⚠️  Some dependencies failed to install, but continuing...")

    # Step 3: Create .env file if not exists
    if not os.path.exists('.env'):
        print("\n📝 Creating .env file...")
        with open('.env', 'w') as f:
            f.write("""# Database Configuration
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/instant_messaging

# Application Settings
DEBUG=False
HOST=0.0.0.0
PORT=8000
""")
        print("✅ .env file created. Please update with your database credentials")
    else:
        print("✅ .env file already exists")

    # Step 4: Initialize database
    print("\n🗄️  Initializing database...")
    try:
        import database
        database.init_db()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        print("⚠️  Make sure PostgreSQL is running and DATABASE_URL is correct in .env")

    # Step 5: Ready message
    print("""
    ╔═══════════════════════════════════════════╗
    ║      ✅ Setup Complete!                   ║
    ╠═══════════════════════════════════════════╣
    ║ To start the server, run:                 ║
    ║                                           ║
    ║   python web_server.py                    ║
    ║                                           ║
    ║ Or with Uvicorn:                          ║
    ║                                           ║
    ║   uvicorn web_server:app --reload         ║
    ║                                           ║
    ║ Then open: http://localhost:8000          ║
    ║                                           ║
    ║ 💡 Pro Tip: Open multiple browser tabs    ║
    ║    with different emails to test!         ║
    ╚═══════════════════════════════════════════╝
    """)

if __name__ == '__main__':
    main()
