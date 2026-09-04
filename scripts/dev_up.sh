#!/usr/bin/env bash
# 同花顺问财 SkillHub —— 一键清理、校验并启动开发环境（后端真实模式 + 前端 dev server）
#
# 用法:
#   ./scripts/dev_up.sh          # 校验并启动前后端（默认）
#   ./scripts/dev_up.sh status   # 查看当前运行状态
#   ./scripts/dev_up.sh stop     # 停止前后端
#
# 环境变量（可选覆盖）:
#   BACKEND_PORT  默认 8000
#   FRONTEND_PORT 默认 5173
#
# 说明:
#   - 脚本会探测 shell 里导出的 CORS_ORIGINS / API_BEARER_TOKENS 是否为合法 JSON；
#     非法时仅在「本次启动的进程环境」里临时 unset，回退使用 backend/.env 的合法值，
#     不会修改你的 shell 配置。根治办法是把这两行 export 从 shell profile 里删掉，
#     或者给值加上引号（它们必须是合法 JSON）。
#   - 后端按 backend/.env 的 ENVIRONMENT 启动；非 test 环境会执行 fail-closed 配置检查，
#     缺密钥或误开 Mock 时拒绝启动，脚本会打印具体 issue code。
#   - 日志写入仓库根目录 logs/（*.log 已被 .gitignore 忽略）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$LOG_DIR/dev_up.pids"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

log()  { printf '[dev-up] %s\n' "$*"; }
warn() { printf '[dev-up][WARN] %s\n' "$*" >&2; }
die()  { printf '[dev-up][ERROR] %s\n' "$*" >&2; exit 1; }

is_pid_alive() {
  kill -0 "$1" >/dev/null 2>&1
}

port_in_use() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

json_valid() {
  printf '%s' "$1" | "$BACKEND_DIR/.venv/bin/python" -c 'import sys, json; json.load(sys.stdin)' >/dev/null 2>&1
}

stop_services() {
  if [ -f "$PID_FILE" ]; then
    while IFS= read -r pid; do
      if is_pid_alive "$pid"; then
        log "stop: killing pid $pid"
        kill "$pid" >/dev/null 2>&1 || true
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  # 兜底：按进程命令行特征清理残留。注意 npm run dev 的 vite 子进程命令行是
  # ".../frontend/node_modules/.bin/../vite/bin/vite.js"（中间含 .bin/../），
  # 模式必须允许任意中间段，且限定在本项目路径内，避免误杀其他项目的 vite。
  pkill -f "uvicorn app.main:app" >/dev/null 2>&1 || true
  pkill -f "同花顺/frontend/.*vite/bin/vite.js" >/dev/null 2>&1 || true
  log "stopped"
}

status_services() {
  local ok=0
  if port_in_use "$BACKEND_PORT"; then
    log "backend : LISTENING on :$BACKEND_PORT"
    curl -fsS "http://127.0.0.1:$BACKEND_PORT/health/ready" 2>/dev/null || true
    printf '\n'
  else
    log "backend : not running"
    ok=1
  fi
  if port_in_use "$FRONTEND_PORT"; then
    log "frontend: LISTENING on :$FRONTEND_PORT (http://localhost:$FRONTEND_PORT)"
  else
    log "frontend: not running"
    ok=1
  fi
  return $ok
}

# ---------------------------- 子命令分发 ----------------------------
case "${1:-up}" in
  stop)   stop_services; exit 0 ;;
  status) status_services || true; exit 0 ;;
  up)     ;;
  *)      die "unknown command: $1 (expected: up | status | stop)" ;;
esac

# ---------------------------- 1. 环境清理 ----------------------------
# shell 导出的复杂配置项必须是合法 JSON，否则会覆盖 backend/.env 并导致
# pydantic-settings 在 import 阶段直接崩溃（Settings 解析失败）。
for var in CORS_ORIGINS API_BEARER_TOKENS; do
  val="$(printenv "$var" || true)"
  if [ -n "$val" ] && ! json_valid "$val"; then
    warn "shell 环境变量 $var 不是合法 JSON，本次启动临时忽略它（使用 backend/.env 的值）。"
    warn "建议修复: 从 ~/.zshrc 等 profile 删除该 export，或给值加引号使其成为合法 JSON。"
    unset "$var"
  fi
done

# LLM_* 同样存在 shell 残留覆盖 .env 的问题：宿主/旧会话可能带着 DeepSeek 时代的
# LLM_BASE_URL / LLM_MODEL / LLM_API_KEY，而 pydantic-settings 中环境变量的优先级
# 高于 backend/.env。backend/.env 是 LLM 配置的唯一事实来源，这里无条件 unset；
# 需要更换模型或密钥时直接修改 backend/.env 即可。
unset LLM_BASE_URL LLM_MODEL LLM_API_KEY

# ---------------------------- 2. 前置检查 ----------------------------
[ -x "$BACKEND_DIR/.venv/bin/python" ] || die "未找到 backend/.venv。请先: cd backend && python3.12 -m venv .venv && pip install -r requirements.txt -r requirements-dev.txt"
command -v node >/dev/null 2>&1 || die "未找到 node（前端需要 Node 22+）"
command -v npm >/dev/null 2>&1 || die "未找到 npm"

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  log "frontend 缺少依赖，执行 npm ci ..."
  (cd "$FRONTEND_DIR" && npm ci)
fi

# ---------------------------- 3. 真实模式配置校验（不回显密钥） ----------------------------
log "校验后端配置（fail-closed readiness）..."
(cd "$BACKEND_DIR" && .venv/bin/python - <<'PYEOF'
from app.core.config import Settings
from app.core.readiness import runtime_configuration_issues

s = Settings()
print(
    "[dev-up] 配置概览: ENVIRONMENT=%s LLM_USE_MOCK=%s SKILLHUB_USE_MOCK=%s IMAGE_ENABLED=%s"
    % (s.ENVIRONMENT, s.LLM_USE_MOCK, s.SKILLHUB_USE_MOCK, s.INDUSTRY_CHAIN_IMAGE_ENABLED)
)
issues = runtime_configuration_issues(s)
if issues:
    print("[dev-up][ERROR] fail-closed 检查未通过: " + ", ".join(issues))
    raise SystemExit(1)
print("[dev-up] 配置校验通过，允许以真实模式启动")
PYEOF
) || die "后端配置校验失败：按上面的 issue code 修复 backend/.env 或环境变量后重试"

# ---------------------------- 4. 端口检查 ----------------------------
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if port_in_use "$port"; then
    die "端口 $port 已被占用，请先释放或改用环境变量指定其他端口（BACKEND_PORT / FRONTEND_PORT）"
  fi
done

# ---------------------------- 5. 启动后端 ----------------------------
mkdir -p "$LOG_DIR"
rm -f "$PID_FILE"

log "启动后端: uvicorn app.main:app --port $BACKEND_PORT （日志: logs/backend.log）"
(cd "$BACKEND_DIR" && nohup .venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port "$BACKEND_PORT" >>"$LOG_DIR/backend.log" 2>&1 & echo $! >>"$PID_FILE")

ready=""
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1; then
    ready="yes"
    break
  fi
  sleep 1
done
[ -n "$ready" ] || { tail -n 40 "$LOG_DIR/backend.log" >&2 || true; die "后端 40 秒内未就绪，查看 logs/backend.log"; }
log "后端就绪: $(curl -fsS "http://127.0.0.1:$BACKEND_PORT/health")"
log "readiness: $(curl -fsS "http://127.0.0.1:$BACKEND_PORT/health/ready")"

# ---------------------------- 6. 启动前端 ----------------------------
log "启动前端: npm run dev (port=${FRONTEND_PORT}, log=logs/frontend.log)"
(cd "$FRONTEND_DIR" && nohup npm run dev -- --port "$FRONTEND_PORT" >>"$LOG_DIR/frontend.log" 2>&1 & echo $! >>"$PID_FILE")

ready=""
for _ in $(seq 1 30); do
  # Vite 默认绑定 localhost（可能是 IPv6 ::1），探活必须走 localhost 而非 127.0.0.1
  if curl -fsS "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1; then
    ready="yes"
    break
  fi
  sleep 1
done
[ -n "$ready" ] || { tail -n 40 "$LOG_DIR/frontend.log" >&2 || true; die "前端 30 秒内未就绪，查看 logs/frontend.log"; }

# ---------------------------- 7. 汇总 ----------------------------
cat <<EOF

================ 启动完成 ================
  前端:   http://localhost:$FRONTEND_PORT
  后端:   http://localhost:$BACKEND_PORT
  API 文档: http://localhost:$BACKEND_PORT/docs
  日志:   $LOG_DIR/backend.log / $LOG_DIR/frontend.log
  停止:   ./scripts/dev_up.sh stop
  状态:   ./scripts/dev_up.sh status

提示:
  1) 打开前端后在 Token 对话框输入 backend/.env 中 API_BEARER_TOKENS 对应的 token；
     也可在 frontend/.env.local 写入 VITE_DEFAULT_TOKEN=<token> 免手工输入（该文件已被忽略）。
  2) 当前为真实模式：创建研报会实际调用火山方舟 ark-code-latest 与问财 SkillHub，消耗外部配额。
===========================================
EOF
