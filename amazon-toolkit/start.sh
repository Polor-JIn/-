#!/usr/bin/env bash
# 一键启动：亚马逊跟卖工作台 (Mac / Linux)
# 用法: bash start.sh   （或 chmod +x start.sh 后 ./start.sh）
# 可自定义端口: PORT=8080 bash start.sh
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[1/3] 首次运行，创建虚拟环境 .venv ..."
  python3 -m venv .venv
else
  echo "[1/3] 使用已有虚拟环境 .venv"
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/3] 检查依赖 ..."
pip install -q -r requirements.txt

echo "[3/3] 启动工作台: http://localhost:${PORT:-8000}  (Ctrl+C 停止)"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"