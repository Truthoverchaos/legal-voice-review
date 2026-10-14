@echo off
rem Starts the Voice Review server (private podcast feed + desk page + notes).
rem Leave this window open while you want your phone to reach the PC.
cd /d "%~dp0"
py -3.13 -I voice.py urls
echo.
py -3.13 -I voice.py serve
pause
