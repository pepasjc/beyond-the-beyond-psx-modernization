@echo off
rem Opens PCSX-Redux with the always-encounter test disc and the battle
rem movement logger, for a person to play while the script records.
rem   1. python debug\test_build.py        (from the repo root; needs patched.bin)
rem   2. put the save in %APPDATA%\pcsx-redux\memcard1.mcd (back up the old one)
rem   3. run this; log goes to work\battle_walk_watch.txt
rem Redux CLI build expected in work\redux (from pcsx-redux's ReleaseCLI zip).
set ROOT=%~dp0..
set W=%ROOT%\work
set R=%W%\redux\drop\binaries\vsprojects\x64\ReleaseCLI
if "%BIOS%"=="" set BIOS=G:\Emulation\bios\scph1001.bin
taskkill /IM pcsx-redux.main /F >nul 2>&1
start "redux" /D "%R%" "%R%\pcsx-redux.exe" -iso "%W%\test.cue" -bios "%BIOS%" -run -interpreter -debugger -dofile "%ROOT%\debug\battle_walk_watch.lua"
