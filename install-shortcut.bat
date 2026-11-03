@echo off
rem Creates the desktop shortcut on Windows. Run once; run again if the project folder moves.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\Trade Journal.lnk\"); $p=(Get-Location).Path; $s.TargetPath=\"$p\.venv\Scripts\pythonw.exe\"; $s.Arguments='launcher.py'; $s.WorkingDirectory=$p; $s.IconLocation=\"$p\assets\icon.ico\"; $s.Save()"
echo Done. Trade Journal is on your Desktop.
pause
