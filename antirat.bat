@echo off
title Rat protection system
Echo While this file runs the rat cannot run
:loop
taskkill /F /IM pythonw.exe
goto:loop