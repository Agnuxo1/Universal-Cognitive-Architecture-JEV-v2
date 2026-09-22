@echo off
setlocal
python -m cognitive_architecture %*
exit /b %errorlevel%
