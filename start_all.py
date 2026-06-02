"""
start_all.py - AIArticle 一键启动（前端 + 后端）

双击 start.bat 即可同时启动前端和后端，浏览器自动打开。
双击 Ctrl+C（3秒内）停止所有服务。
"""
import subprocess
import sys
import os
import signal
import time
import threading
import urllib.request
import urllib.error

# 强制 UTF-8，防止中文路径乱码
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
os.environ["NODE_OPTIONS"] = os.environ.get("NODE_OPTIONS", "") + " --no-warnings"
# Windows 终端 UTF-8
try:
    os.system("")
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_kill_count = 0
_procs = {}  # name -> subprocess.Popen
_log_files = {}

BACKEND_PORT = 8000
FRONTEND_PORT = 3000
OPEN_URL = f"http://localhost:{FRONTEND_PORT}"


def _handle_int(sig, frame):
    global _kill_count

    _kill_count += 1

    if _kill_count == 1:
        sys.stdout.write(
            "\r\n  [!] 再按一次 Ctrl+C（3 秒内）确认停止所有服务器 ...\r\n"
        )
        sys.stdout.flush()

        def _reset():
            global _kill_count
            time.sleep(3)
            if _kill_count == 1:
                _kill_count = 0
                sys.stdout.write(
                    "\r\n  [i] 已取消，服务器继续运行。\r\n"
                )
                sys.stdout.flush()

        threading.Thread(target=_reset, daemon=True).start()

    elif _kill_count >= 2:
        sys.stdout.write("\r\n  正在停止所有服务 ...\r\n")
        sys.stdout.flush()
        _cleanup()
        sys.stdout.write("  所有服务已停止。\r\n")
        sys.stdout.flush()
        sys.exit(0)


def _kill_proc(proc):
    """杀掉进程及其整棵子进程树"""
    if proc and proc.poll() is None:
        pid = proc.pid
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=5,
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _kill_by_port(port):
    """根据端口号杀掉占用该端口的进程"""
    try:
        result = subprocess.run(
            f'netstat -aon | findstr ":{port} " | findstr "LISTENING"',
            capture_output=True, text=True, shell=True, timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.strip().split()
            if len(parts) >= 5:
                pid = parts[-1]
                if pid.isdigit() and int(pid) > 0:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True, timeout=5,
                    )
                    sys.stdout.write(f"    killed PID {pid} (port {port})\r\n")
                    sys.stdout.flush()
    except Exception:
        pass


def _cleanup():
    """彻底清理：先杀进程树 → 按镜像名杀 → 按端口兜底"""
    # 1) 杀直接子进程树
    for name, proc in _procs.items():
        _kill_proc(proc)

    # 2) 按镜像名杀（shell=True 下进程树可能断链）
    for image in ["node.exe"]:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", image, "/T"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    # 3) 按端口号最终兜底
    time.sleep(0.5)
    for port in [BACKEND_PORT, FRONTEND_PORT]:
        _kill_by_port(port)


def _check_port(port, path="/health"):
    """检查端口是否可访问（含 HTTP 错误也算就绪）"""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="GET")
        urllib.request.urlopen(req, timeout=2)
        return True
    except urllib.error.HTTPError:
        # 服务已在响应（可能 404），算就绪
        return True
    except Exception:
        return False


def _wait_for(name, check_fn, timeout=90):
    for i in range(timeout):
        if check_fn():
            return True
        # 每 10 秒打印一个状态
        if i % 10 == 0 and i > 0:
            sys.stdout.write(f"  [{name}] 仍在启动中 ... ({i}s)\r\n")
            sys.stdout.flush()
        time.sleep(1)
    return False


def _start_backend():
    """启动后端 FastAPI"""
    backend_dir = os.path.join(ROOT, "backed")
    log = os.path.join(backend_dir, "uvicorn.out.log")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "main:app",
            "--host", "0.0.0.0",
            "--port", str(BACKEND_PORT),
        ],
        stdout=open(log, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        cwd=backend_dir,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    _procs["backend"] = proc
    _log_files["backend"] = log
    return proc


def _start_frontend():
    """启动前端 Next.js"""
    frontend_dir = os.path.join(ROOT, "frontend")
    log = os.path.join(frontend_dir, "dev-server.log")

    # 构造子进程 UTF-8 环境变量
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        "npm run dev",
        shell=True,
        stdout=open(log, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        cwd=frontend_dir,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    _procs["frontend"] = proc
    _log_files["frontend"] = log
    return proc


def _tail_logs():
    """并行 tail 两份日志"""
    import queue

    q = queue.Queue()

    def reader(name, logfile):
        try:
            proc = subprocess.Popen(
                ["powershell", "-Command", f"Get-Content '{logfile}' -Wait"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _procs[f"tail_{name}"] = proc
            for line in proc.stdout:
                q.put((name, line.rstrip()))
        except Exception:
            pass

    threading.Thread(target=reader, args=("backend", _log_files["backend"]), daemon=True).start()
    threading.Thread(target=reader, args=("frontend", _log_files["frontend"]), daemon=True).start()

    # 简易输出：区分前后端日志
    while True:
        try:
            name, line = q.get(timeout=0.5)
            if name == "backend":
                sys.stdout.write(f"  \033[90m[backend]\033[0m {line}\n")
            else:
                sys.stdout.write(f"  \033[90m[frontend]\033[0m {line}\n")
            sys.stdout.flush()
        except Exception:
            if all(p.poll() is not None for p in _procs.values() if isinstance(p, subprocess.Popen)):
                break


def main():
    os.chdir(ROOT)

    print()
    print("  ╔═══════════════════════════════════════════════════════╗")
    print("  ║          AIArticle  一键启动（前端 + 后端）          ║")
    print("  ╠═══════════════════════════════════════════════════════╣")
    print(f"  ║  后端:  FastAPI  http://localhost:{BACKEND_PORT}/docs          ║")
    print(f"  ║  前端:  Next.js  http://localhost:{FRONTEND_PORT}/             ║")
    print("  ╚═══════════════════════════════════════════════════════╝")
    print()

    # 1) 先启动后端，等待就绪后再启动前端（消除竞态）
    print("  [1/3] 启动后端 FastAPI ...")
    _start_backend()

    print("  [1/3] 等待后端就绪 ...")
    backend_ready = _wait_for("backend", lambda: _check_port(BACKEND_PORT, "/health"), timeout=90)
    if not backend_ready:
        print(f"  [!] 后端在 90 秒内未启动，请检查 backed/uvicorn.out.log")
        print("  按回车退出 ...")
        input()
        _cleanup()
        sys.exit(1)
    print("  [1/3] 后端已就绪，启动前端 Next.js ...")
    _start_frontend()

    # 2) 等待前端就绪
    print()
    print("  [2/3] 等待前端就绪 ...")
    frontend_ready = _wait_for("frontend", lambda: _check_port(FRONTEND_PORT, "/"), timeout=90)

    print()
    if not backend_ready:
        print(f"  [!] 后端在 90 秒内未启动，请检查 backed/uvicorn.out.log")
    if not frontend_ready:
        print(f"  [!] 前端在 90 秒内未启动，请检查 frontend/dev-server.log")

    if backend_ready or frontend_ready:
        # 3) 打开浏览器
        print("  [3/3] 打开浏览器 ...")
        os.startfile(OPEN_URL)
        print()
        print("  ───────────────────────────────────────────────────")
        print(f"  后端:  http://localhost:{BACKEND_PORT}/docs")
        print(f"  前端:  http://localhost:{FRONTEND_PORT}/")
        print("  按 Ctrl+C 两次（3秒内）停止所有服务")
        print("  ───────────────────────────────────────────────────")
        print()
    else:
        print()
        print("  所有服务均未启动成功，请检查日志文件后重试。")
        print("  按回车退出 ...")
        input()
        _cleanup()
        sys.exit(1)

    # 4) tail 日志
    signal.signal(signal.SIGINT, _handle_int)
    _tail_logs()


ROOT = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    main()
