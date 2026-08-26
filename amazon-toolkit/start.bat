@echo off
REM 一键启动：亚马逊跟卖工作台 (Windows)
REM 用法: 双击 start.bat 或在命令行运行
cd /d %~dp0

if not exist .venv (
  echo [1/3] 首次运行，创建虚拟环境 .venv ...
  python -m venv .venv
) else (
  echo [1/3] 使用已有虚拟环境 .venv
)
call .venv\Scripts\activate.bat

echo [2/3] 检查依赖 ...
pip install -q -r requirements.txt

echo [3/3] 启动工作台: http://localhost:8000  按 Ctrl+C 停止
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause