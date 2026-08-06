@echo off
REM run_host.bat — Chrome's native-messaging "path" must be a directly-executable file, not a
REM bare .py (there is no reliable file association across machines). One-line wrapper: invoke
REM this same directory's host.py with the system Python. %~dp0 resolves to this .bat's own
REM directory regardless of CWD, so this works however Chrome launches it.
python "%~dp0host.py" %*
