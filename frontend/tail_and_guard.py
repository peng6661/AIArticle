"""
tail_and_guard.py - 实时输出日志文件，支持双击 Ctrl+C 才终止

用法: python tail_and_guard.py <logfile>
"""
import subprocess
import sys
import signal
import threading

_count = 0
_proc = None


def handle_int(sig, frame):
    global _count
    _count += 1
    if _count == 1:
        sys.stdout.write(
            "\r\n  [!] 再按一次 Ctrl+C（3 秒内）确认停止服务器 ...\r\n"
        )
        sys.stdout.flush()
        # 3 秒后自动重置计数
        def reset():
            global _count
            import time
            time.sleep(3)
            if _count == 1:
                _count = 0
                sys.stdout.write(
                    "\r\n  [i] 已取消，服务器继续运行。\r\n"
                )
                sys.stdout.flush()
        threading.Thread(target=reset, daemon=True).start()
    elif _count >= 2:
        sys.stdout.write("\r\n  Stopping dev server ...\r\n")
        sys.stdout.flush()
        if _proc:
            _proc.kill()
        sys.exit(0)


def main():
    global _proc
    if len(sys.argv) < 2:
        print("Usage: python tail_and_guard.py <logfile>")
        sys.exit(1)

    logfile = sys.argv[1]

    signal.signal(signal.SIGINT, handle_int)

    _proc = subprocess.Popen(
        ["powershell", "-Command", f"Get-Content '{logfile}' -Wait"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    try:
        _proc.wait()
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
