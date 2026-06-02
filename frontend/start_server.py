"""
start_server.py - AIArticle 前端开发服务器启动器

功能:
  1. 启动 npm run dev
  2. 等待端口就绪后自动打开浏览器
  3. 双击 Ctrl+C 终止（3秒内按两次）
"""
import subprocess
import sys
import os
import signal
import time
import threading
import urllib.request
import urllib.error

# 强制 UTF-8 输出，防止 emoji 乱码
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["NODE_OPTIONS"] = os.environ.get("NODE_OPTIONS", "") + " --no-warnings"
# Windows 终端 UTF-8
try:
    os.system("")  # 启用 VT100
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


_kill_count = 0
_npm_proc = None
_tail_proc = None


def _handle_int(sig, frame):
    global _kill_count

    _kill_count += 1

    if _kill_count == 1:
        sys.stdout.write(
            "\r\n  [!] 再按一次 Ctrl+C（3 秒内）确认停止服务器 ...\r\n"
        )
        sys.stdout.flush()

        def _reset():
            global _kill_count
            time.sleep(3)
            if _kill_count == 1:
                _kill_count = 0
                sys.stdout.write(
                    "\r\n  [i] 已取消，服务器继续运行。\r\n> "
                )
                sys.stdout.flush()

        threading.Thread(target=_reset, daemon=True).start()

    elif _kill_count >= 2:
        sys.stdout.write("\r\n  正在停止 dev server ...\r\n")
        sys.stdout.flush()
        # 杀掉子进程
        _kill_proc(_tail_proc)
        _kill_proc(_npm_proc)
        # 杀掉 npm 产生的所有 node 子进程
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "node.exe", "/T"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass
        sys.stdout.write("  已停止。\r\n")
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


def _wait_for_server(timeout=60):
    """轮询 localhost:3000 直到可访问（含 404 也算，说明 Next.js 已在运行）"""
    url = "http://127.0.0.1:3000/"
    for _ in range(timeout):
        try:
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=2)
            return True
        except urllib.error.HTTPError:
            # HTTP 错误（含 404）说明 Next.js 已经在响应了
            return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        sys.stdout.write(".")
        sys.stdout.flush()
        time.sleep(1)
    return False


def main():
    global _npm_proc, _tail_proc

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print()
    print("  ========================================================")
    print("     AIArticle Frontend  |  Starting dev server ...")
    print("  ========================================================")
    print()

    # 1) 启动 npm run dev，日志写入文件
    print("  启动 Next.js ...")
    log_file = os.path.join(os.getcwd(), "dev-server.log")
    # 构造子进程 UTF-8 环境变量
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    _npm_proc = subprocess.Popen(
        "npm run dev",
        shell=True,
        stdout=open(log_file, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # 2) 等待服务器就绪
    print("  等待服务器启动 ", end="")
    if _wait_for_server():
        print()
        print("  服务器已就绪！")
        print("  正在打开浏览器 ...")
        os.startfile("http://localhost:3000/")
        print()
        print("  ========================================================")
        print("     http://localhost:3000/")
        print("     按 Ctrl+C 两次（3秒内）停止服务器")
        print("  ========================================================")
        print()
    else:
        print()
        print(f"  [!] 服务器在 {60} 秒内未启动。")
        print()
        print("  最后 20 行日志:")
        print("  ----------------------------------------")
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                for line in lines[-20:]:
                    print(f"  {line.rstrip()}")
        except FileNotFoundError:
            print("  (日志文件未找到)")
        print("  ----------------------------------------")
        print()
        _kill_proc(_npm_proc)
        sys.exit(1)

    # 3) 实时 tail 日志
    signal.signal(signal.SIGINT, _handle_int)

    _tail_proc = subprocess.Popen(
        ["powershell", "-Command", f"Get-Content '{log_file}' -Wait"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    try:
        _tail_proc.wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
