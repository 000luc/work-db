@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在增量导入新会话...
py main.py import --incremental
echo.
echo 完成！按任意键退出。
pause >nul
