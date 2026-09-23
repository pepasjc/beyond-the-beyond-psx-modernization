@echo off
rem Boots work\<cue> (default smooth.cue) in PCSX-Redux with debug\hang_probe.lua (no input
rem needed); the log goes to work\hang_probe.txt.  Put the save in
rem %APPDATA%\pcsx-redux\memcard1.mcd first (back up the old one).
set ROOT=%~dp0..
set W=%ROOT%\work
set R=%W%\redux\drop\binaries\vsprojects\x64\ReleaseCLI
set CUE=%1
if "%CUE%"=="" set CUE=smooth.cue
if "%BIOS%"=="" set BIOS=G:\Emulation\bios\scph1001.bin
taskkill /IM pcsx-redux.main /F >nul 2>&1
start "redux" /D "%R%" "%R%\pcsx-redux.exe" -iso "%W%\%CUE%" -bios "%BIOS%" -run -interpreter -debugger -dofile "%ROOT%\debug\hang_probe.lua"
