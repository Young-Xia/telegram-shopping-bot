from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass

import psutil

from shopping_bot.gui.paths import log_path, project_root, venv_python, venv_pythonw

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_PYTHON_NAMES = frozenset({"python.exe", "pythonw.exe"})
_PROCESS_CACHE: tuple[float, tuple[int, ...]] | None = None
_PROCESS_CACHE_TTL = 1.5


@dataclass(frozen=True)
class BotProcessInfo:
    running: bool
    pids: list[int]
    count: int


def _is_bot_process(proc: psutil.Process) -> bool:
    try:
        cmdline = " ".join(proc.cmdline()).lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    if "shopping_bot.gui" in cmdline:
        return False
    if "shopping_bot.bot" in cmdline:
        return True
    if "-m" in cmdline and "shopping_bot" in cmdline and "bot" in cmdline:
        return True
    return False


def invalidate_process_cache() -> None:
    global _PROCESS_CACHE
    _PROCESS_CACHE = None


def list_bot_processes(*, force: bool = False) -> list[int]:
    global _PROCESS_CACHE
    now = time.monotonic()
    if (
        not force
        and _PROCESS_CACHE is not None
        and now - _PROCESS_CACHE[0] < _PROCESS_CACHE_TTL
    ):
        return list(_PROCESS_CACHE[1])

    pids: list[int] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            info = proc.info
            if (info.get("name") or "").lower() not in _PYTHON_NAMES:
                continue
            if _is_bot_process(proc):
                pids.append(int(info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    unique = tuple(sorted(set(pids)))
    _PROCESS_CACHE = (now, unique)
    return list(unique)


def get_bot_status() -> BotProcessInfo:
    pids = list_bot_processes()
    return BotProcessInfo(running=bool(pids), pids=pids, count=len(pids))


def _kill_pid(pid: int) -> None:
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return

    children = proc.children(recursive=True)
    for child in children:
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    try:
        proc.kill()
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True,
                creationflags=_CREATE_NO_WINDOW,
            )

    try:
        proc.wait(timeout=3)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
        pass


def _wait_until_stopped(*, timeout: float = 12.0, interval: float = 0.4) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        invalidate_process_cache()
        if not list_bot_processes(force=True):
            return True
        time.sleep(interval)
    invalidate_process_cache()
    return not list_bot_processes(force=True)


def _wait_for_bot_running(*, timeout: float = 15.0, interval: float = 0.5) -> BotProcessInfo | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        invalidate_process_cache()
        status = get_bot_status()
        if status.running:
            time.sleep(0.3)
            invalidate_process_cache()
            return get_bot_status()
        time.sleep(interval)
    return None


def stop_bot(*, wait_seconds: float = 0.8, max_rounds: int = 6) -> tuple[bool, str]:
    initial = list_bot_processes(force=True)
    if not initial:
        return True, "机器人未在运行。"

    invalidate_process_cache()

    for _ in range(max_rounds):
        pids = list_bot_processes(force=True)
        if not pids:
            return True, f"已停止 {len(initial)} 个 bot 进程。"

        for pid in pids:
            _kill_pid(pid)
        time.sleep(wait_seconds)

    invalidate_process_cache()
    remaining = list_bot_processes(force=True)
    if remaining:
        return False, (
            f"未能完全停止，仍有 {len(remaining)} 个进程 (PID: "
            f"{', '.join(map(str, remaining))})。"
            "若已安装开机自启，可先运行 uninstall-autostart.cmd。"
        )
    return True, f"已停止 {len(initial)} 个 bot 进程。"


def ensure_dependencies() -> tuple[bool, str]:
    root = project_root()
    py = venv_python()
    if not py.is_file():
        try:
            subprocess.run(
                ["py", "-3", "-m", "venv", str(root / ".venv")],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            return False, f"创建虚拟环境失败: {exc}"

    req = root / "requirements.txt"
    if not req.is_file():
        return False, "缺少 requirements.txt"

    for args in (
        [str(py), "-m", "pip", "install", "-q", "-U", "pip"],
        [str(py), "-m", "pip", "install", "-q", "-r", str(req)],
    ):
        result = subprocess.run(
            args,
            cwd=str(root),
            capture_output=True,
            text=True,
            creationflags=_CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False, result.stderr or "依赖安装失败"
    return True, "依赖已就绪。"


def _launch_bot_process() -> Path:
    root = project_root()
    log_path().parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    src = str(root / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")

    startup_log = log_path().parent / "bot-startup.log"
    log_handle = startup_log.open("a", encoding="utf-8")
    log_handle.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_handle.flush()

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    pyw = venv_pythonw()
    subprocess.Popen(
        [str(pyw), "-m", "shopping_bot.bot"],
        cwd=str(root),
        env=env,
        creationflags=creationflags,
        stdout=log_handle,
        stderr=log_handle,
        close_fds=False,
    )
    return startup_log


def _startup_failure_message(startup_log: Path) -> str:
    tail = ""
    if startup_log.is_file():
        lines = startup_log.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-6:])
    hint = f"\n\n最近启动日志:\n{tail}" if tail else ""
    return f"启动失败，未检测到 bot 进程。请查看 logs/bot-startup.log 或 logs/bot.log。{hint}"


def start_bot(*, restart: bool = False) -> tuple[bool, str]:
    root = project_root()
    env_file = root / ".env"
    if not env_file.is_file():
        return False, "请先完成初始设置并保存 .env。"

    pyw = venv_pythonw()
    if not pyw.is_file():
        ok, message = ensure_dependencies()
        if not ok:
            return False, message
        pyw = venv_pythonw()
        if not pyw.is_file():
            return False, "找不到 pythonw.exe，请检查虚拟环境。"

    if restart:
        if get_bot_status().running:
            ok, message = stop_bot()
            if not ok:
                return False, message
            if not _wait_until_stopped():
                remaining = list_bot_processes(force=True)
                return False, (
                    "重启失败：停止后仍有残留进程 (PID: "
                    f"{', '.join(map(str, remaining))})。"
                )
            time.sleep(1.0)
    elif get_bot_status().running:
        return False, "机器人已在运行中。"

    startup_log = _launch_bot_process()
    status = _wait_for_bot_running(timeout=15.0)
    if status and status.running:
        verb = "重启" if restart else "启动"
        return True, f"机器人已{verb} (PID: {', '.join(map(str, status.pids))})"

    return False, _startup_failure_message(startup_log)


def restart_bot() -> tuple[bool, str]:
    return start_bot(restart=True)


def read_log_tail(max_lines: int = 250) -> str:
    path = log_path()
    if not path.is_file():
        return "（尚无日志，启动机器人后这里会显示运行日志）\n"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"无法读取日志: {exc}"
    if not lines:
        return "（日志文件为空）\n"
    return "\n".join(lines[-max_lines:]) + "\n"
