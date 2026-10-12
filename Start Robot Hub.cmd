@echo off
title Robot Hub
rem Double-click to update and start the Robot Hub. Closing this window stops it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start-hub.ps1" & echo. & echo The hub has stopped. & pause & exit /b
