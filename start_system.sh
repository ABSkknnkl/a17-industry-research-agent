#!/usr/bin/env bash
# ==============================================================================
# 行业研究五智能体协同研报生成系统 — 前后端一键全栈启动脚本
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

BACKEND_DIR="${SCRIPT_DIR}/backend"
FRONTEND_DIR="${SCRIPT_DIR}/frontend"

export PYTHONPATH="${SCRIPT_DIR}:${SCRIPT_DIR}/agents_core/data-fetcher:${SCRIPT_DIR}/agents_core/data-analysis:${SCRIPT_DIR}/agents_core/chart-generator:${SCRIPT_DIR}/agents_core/chapter-writer:${SCRIPT_DIR}/agents_core/report-fusion:${PYTHONPATH:-}"

echo "================================================================================"
echo "🚀 正在启动 同花顺问财SkillHub五智能体全链路行业研报系统"
echo "  工程路径: ${SCRIPT_DIR}"
echo "================================================================================"

# 1. 检查并选择 Python 解释器
PYTHON_CMD="python3"
if command -v python3.11 >/dev/null 2>&1; then
  # 优先检查 3.11
  PYTHON_CMD="python3.11"
fi
if ! "${PYTHON_CMD}" -c "import fastapi, pydantic, uvicorn" >/dev/null 2>&1; then
  PYTHON_CMD="python3"
fi

echo "  --> 使用 Python: $("${PYTHON_CMD}" --version)"

# 2. 清理可能残留的端口占用
echo "  --> 检查并释放 8000 与 5173 端口..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:5173 | xargs kill -9 2>/dev/null || true

# 3. 启动 FastAPI 后端
echo "  --> 正在启动 FastAPI 后端服务 (端口 8000)..."
"${PYTHON_CMD}" "${BACKEND_DIR}/run_server.py" > "${SCRIPT_DIR}/backend.log" 2>&1 &
BACKEND_PID=$!

cleanup() {
  echo ""
  echo "🛑 正在停止前后端服务..."
  kill -9 "${BACKEND_PID}" 2>/dev/null || true
  if [ -n "${FRONTEND_PID:-}" ]; then
    kill -9 "${FRONTEND_PID}" 2>/dev/null || true
  fi
  echo "✅ 已安全停止所有服务进程。"
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 等待后端健康检查通过
echo -n "  --> 等待后端服务就绪"
for i in {1..30}; do
  if curl -s "http://localhost:8000/health" >/dev/null 2>&1; then
    echo " [OK]"
    break
  fi
  echo -n "."
  sleep 1
done

if ! curl -s "http://localhost:8000/health" >/dev/null 2>&1; then
  echo " ❌ 后端启动失败，请查看日志: ${SCRIPT_DIR}/backend.log"
  tail -n 20 "${SCRIPT_DIR}/backend.log"
  exit 1
fi

echo "  ✅ 后端服务已就绪: http://localhost:8000 (API Docs: http://localhost:8000/docs)"

# 4. 启动前端服务
echo "  --> 正在启动 Vue3 + Vite 前端工作台 (端口 5173)..."
cd "${FRONTEND_DIR}"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "================================================================================"
echo "🎉 系统全栈启动成功！"
echo "  👉 前端工作台: http://localhost:5173"
echo "  👉 后端接口:   http://localhost:8000/api/v1"
echo "  👉 接口文档:   http://localhost:8000/docs"
echo "================================================================================"
echo "💡 提示: 按 Ctrl+C 可一键停止前后端所有服务"

wait "${FRONTEND_PID}"
