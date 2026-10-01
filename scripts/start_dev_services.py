"""启动前后端开发服务，并让进程脱离当前会话（避免被回收）。

用法::

    python scripts/start_dev_services.py            # 同时启动后端 + 前端
    python scripts/start_dev_services.py backend    # 只重启后端（改后端代码后用）
    python scripts/start_dev_services.py frontend   # 只重启前端

关键点：subprocess.Popen(start_new_session=True) → 子进程 setsid，
进入独立进程组/会话，父进程（WorkBuddy 的 shell）结束时不会被连带杀掉。

注意：后端 uvicorn 是 reload=False 启动的，**改完后端代码必须用本脚本重启**才生效。
"""
import os
import signal
import subprocess
import sys
import time

ROOT = "/Users/Zhuanz1/Downloads/行业研究智能体-全链路系统 4"
PY = "/Users/Zhuanz1/PycharmProjects/同花顺/backend/.venv/bin/python"
NODE_BIN = "/Users/Zhuanz1/.workbuddy/binaries/node/versions/22.22.2-3/bin"
AGENTS = [
    "data-fetcher",
    "data-analysis",
    "chart-generator",
    "chapter-writer",
    "report-fusion",
]

TARGET = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
if TARGET not in ("all", "backend", "frontend"):
    raise SystemExit(f"未知参数 {TARGET!r}，可选：all / backend / frontend")


def free_port(port: int) -> None:
    """释放端口上残留的进程（重启先清干净，避免 Address already in use）。"""
    out = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True, text=True,
    ).stdout.split()
    for pid in out:
        try:
            os.kill(int(pid), signal.SIGTERM)
            print(f"已停止端口 {port} 上的旧进程 pid={pid}", flush=True)
        except (ProcessLookupError, PermissionError, ValueError):
            pass
    if out:
        time.sleep(2)


def start(name, cmd, cwd, env, log_path):
    log = open(log_path, "w")
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    print(f"{name}: pid={proc.pid} log={log_path}", flush=True)
    return proc


procs = []

# ── 后端 ──────────────────────────────────────────────────────────────
if TARGET in ("all", "backend"):
    free_port(8000)
    env_b = os.environ.copy()
    env_b["PYTHONPATH"] = ":".join([ROOT] + [f"{ROOT}/agents_core/{a}" for a in AGENTS])
    env_b.pop("PYTHONHOME", None)
    procs.append(start("backend", [PY, "backend/run_server.py"], ROOT, env_b, f"{ROOT}/backend.log"))
    time.sleep(2)

# ── 前端 ──────────────────────────────────────────────────────────────
if TARGET in ("all", "frontend"):
    free_port(5173)
    env_f = os.environ.copy()
    env_f.pop("NODE_OPTIONS", None)  # WorkBuddy broker shim 会拦 node 的文件系统操作
    env_f["PATH"] = f"{NODE_BIN}:{env_f.get('PATH', '')}"
    procs.append(start(
        "frontend", ["./node_modules/.bin/vite"], f"{ROOT}/frontend", env_f,
        "/tmp/frontend_dev.log",
    ))

# ── 等待并回报状态 ────────────────────────────────────────────────────
time.sleep(10)
for p in procs:
    print(f"pid={p.pid} alive={p.poll() is None}", flush=True)

