from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from shopping_bot.gui.paths import log_path, project_root, venv_python, venv_pythonw

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_PROCESS_CACHE: tuple[float, tuple[int, ...]] | None = None
_PROCESS_CACHE_TTL = 0.75
_BOT_MARKERS = ("shopping_bot.bot", "src\\shopping_bot\\bot.py", "src/shopping_bot/bot.py")


@dataclass(frozen=True)
class BotProcessInfo:
    running: bool
    pids: list[int]
    count: int


def _pid_file() -> Path:
    return log_path().parent / "bot.pid"


def _write_pid_file(pid: int) -> None:
    log_path().parent.mkdir(parents=True, exist_ok=True)
    _pid_file().write_text(str(pid), encoding="utf-8")


def _clear_pid_file() -> None:
    try:
        _pid_file().unlink()
    except FileNotFoundError:
        pass


def _read_pid_file() -> int | None:
    try:
        raw = _pid_file().read_text(encoding="utf-8").strip()
        pid = int(raw)
    except (FileNotFoundError, OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _run_powershell(script: str, *, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        creationflags=_CREATE_NO_WINDOW,
        timeout=timeout,
    )


def _cmd_is_bot(command_line: str | None) -> bool:
    cmd = (command_line or "").lower()
    if "shopping_bot.gui" in cmd:
        return False
    return any(marker in cmd for marker in _BOT_MARKERS)


def _pid_command_line(pid: int) -> str:
    if sys.platform == "win32":
        script = (
            f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" "
            "-ErrorAction SilentlyContinue; "
            "if ($p) { [string]$p.CommandLine }"
        )
        try:
            result = _run_powershell(script, timeout=5.0)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    try:
        return " ".join(psutil.Process(pid).cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


def _pid_is_alive(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return psutil.pid_exists(pid)


def _pid_file_is_fresh(seconds: float = 120.0) -> bool:
    try:
        return time.time() - _pid_file().stat().st_mtime <= seconds
    except OSError:
        return False


def _pid_is_known_bot(pid: int, *, trust_fresh_pid_file: bool = False) -> bool:
    command_line = _pid_command_line(pid)
    if _cmd_is_bot(command_line):
        return True

    # During the first moments after pythonw starts, Windows may not expose the
    # command line yet. Trust only the PID we just wrote, and only briefly.
    if trust_fresh_pid_file and not command_line and _read_pid_file() == pid and _pid_file_is_fresh():
        return _pid_is_alive(pid) and "shopping_bot.gui" not in command_line.lower()
    return False


def _win32_bot_pids() -> set[int]:
    script = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "$cmd = ([string]$_.CommandLine).ToLower(); "
        "($cmd -notlike '*shopping_bot.gui*') -and ("
        "($cmd -like '*shopping_bot.bot*') -or "
        "($cmd -like '*src\\shopping_bot\\bot.py*') -or "
        "($cmd -like '*src/shopping_bot/bot.py*')"
        ") } | ForEach-Object { $_.ProcessId }"
    )
    try:
        result = _run_powershell(script)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if result.returncode != 0:
        return set()
    return {int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()}


def _psutil_bot_pids() -> set[int]:
    pids: set[int] = set()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if _cmd_is_bot(cmdline):
                pids.add(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return pids


def invalidate_process_cache() -> None:
    global _PROCESS_CACHE
    _PROCESS_CACHE = None


def list_bot_processes(*, force: bool = False) -> list[int]:
    global _PROCESS_CACHE
    now = time.monotonic()
    if not force and _PROCESS_CACHE is not None and now - _PROCESS_CACHE[0] < _PROCESS_CACHE_TTL:
        return list(_PROCESS_CACHE[1])

    pids = _win32_bot_pids() if sys.platform == "win32" else _psutil_bot_pids()
    pids.update(_psutil_bot_pids())

    pid_from_file = _read_pid_file()
    if pid_from_file is not None:
        if _pid_is_known_bot(pid_from_file, trust_fresh_pid_file=True):
            pids.add(pid_from_file)
        else:
            _clear_pid_file()

    unique = tuple(sorted(pids))
    _PROCESS_CACHE = (now, unique)
    return list(unique)


def get_bot_status() -> BotProcessInfo:
    pids = list_bot_processes()
    return BotProcessInfo(running=bool(pids), pids=pids, count=len(pids))


def _kill_pid(pid: int) -> None:
    if not _pid_is_alive(pid):
        return
    if not _pid_is_known_bot(pid, trust_fresh_pid_file=True):
        return

    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            creationflags=_CREATE_NO_WINDOW,
        )
        return

    try:
        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            child.kill()
        proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def _wait_until_no_bots(*, timeout: float = 10.0) -> list[int]:
    deadline = time.monotonic() + timeout
    remaining: list[int] = []
    while time.monotonic() < deadline:
        invalidate_process_cache()
        remaining = list_bot_processes(force=True)
        if not remaining:
            _clear_pid_file()
            return []
        time.sleep(0.25)
    return remaining


def _stop_all_bots(*, timeout: float = 10.0) -> tuple[bool, list[int], list[int]]:
    initial = list_bot_processes(force=True)
    for pid in initial:
        _kill_pid(pid)

    remaining = _wait_until_no_bots(timeout=timeout)
    if remaining:
        for pid in remaining:
            _kill_pid(pid)
        remaining = _wait_until_no_bots(timeout=3.0)

    if remaining:
        return False, initial, remaining
    return True, initial, []


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


def _check_can_launch() -> tuple[bool, str]:
    root = project_root()
    if not (root / ".env").is_file():
        return False, "请先完成初始设置并保存 .env。"

    if not venv_pythonw().is_file():
        ok, message = ensure_dependencies()
        if not ok:
            return False, message
        if not venv_pythonw().is_file():
            return False, "找不到 pythonw.exe，请检查虚拟环境。"
    return True, ""


def _bot_log_snapshot() -> tuple[int, str]:
    path = log_path()
    if not path.is_file():
        return 0, ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, ""
    return len(text), text


def _bot_started_after(before_len: int, before_text: str) -> bool:
    path = log_path()
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    marker = "Application started"
    if len(text) > before_len:
        return marker in text[before_len:]
    return text.rfind(marker) > before_text.rfind(marker)


def _startup_log_has_error(startup_log: Path) -> bool:
    if not startup_log.is_file():
        return False
    try:
        tail = startup_log.read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        return False
    markers = ("Traceback (most recent call last)", "ModuleNotFoundError", "ImportError:", "SyntaxError:")
    return any(marker in tail for marker in markers)


def _launch_bot_process() -> tuple[Path, int | None]:
    root = project_root()
    log_path().parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    src = str(root / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")

    startup_log = log_path().parent / "bot-startup.log"
    log_handle = startup_log.open("a", encoding="utf-8")
    log_handle.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_handle.flush()

    proc = subprocess.Popen(
        [str(venv_pythonw()), "-m", "shopping_bot.bot"],
        cwd=str(root),
        env=env,
        creationflags=_CREATE_NO_WINDOW,
        stdout=log_handle,
        stderr=log_handle,
        close_fds=False,
    )
    if proc.pid:
        _write_pid_file(proc.pid)
    return startup_log, proc.pid or None


def _wait_for_started(
    launched_pid: int | None,
    before_log: tuple[int, str],
    startup_log: Path,
    *,
    timeout: float = 12.0,
) -> tuple[bool, int | None, list[int]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _startup_log_has_error(startup_log):
            return False, None, list_bot_processes(force=True)

        current = list_bot_processes(force=True)
        if launched_pid and _pid_is_alive(launched_pid) and launched_pid not in current:
            current = sorted({*current, launched_pid})

        if _bot_started_after(before_log[0], before_log[1]):
            if launched_pid and _pid_is_alive(launched_pid):
                _write_pid_file(launched_pid)
                return True, launched_pid, current
            if len(current) == 1:
                _write_pid_file(current[0])
                return True, current[0], current

        if launched_pid and not _pid_is_alive(launched_pid):
            return False, None, current
        time.sleep(0.25)

    current = list_bot_processes(force=True)
    if launched_pid and _pid_is_alive(launched_pid):
        _write_pid_file(launched_pid)
        return True, launched_pid, current or [launched_pid]
    return False, None, current


def _startup_failure_message(startup_log: Path, *, extra: str = "") -> str:
    tail = ""
    if startup_log.is_file():
        lines = startup_log.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-6:])
    hint = f"\n\n最近启动日志:\n{tail}" if tail else ""
    suffix = f"\n\n{extra}" if extra else ""
    return f"启动失败，未检测到 bot 进程。请查看 logs/bot-startup.log 或 logs/bot.log。{hint}{suffix}"


def start_bot(*, restart: bool = False) -> tuple[bool, str]:
    ok, message = _check_can_launch()
    if not ok:
        return False, message

    if not restart:
        existing = list_bot_processes(force=True)
        if existing:
            return False, f"机器人已在运行中 (PID: {', '.join(map(str, existing))})。"

    before_log = _bot_log_snapshot()
    startup_log, launched_pid = _launch_bot_process()
    ready, ready_pid, current = _wait_for_started(launched_pid, before_log, startup_log)
    invalidate_process_cache()

    if ready and ready_pid:
        verb = "重启" if restart else "启动"
        return True, f"机器人已{verb} (PID: {ready_pid})"

    if len(current) > 1:
        return False, f"启动异常：检测到多个 bot 进程 (PID: {', '.join(map(str, current))})。请先停止。"
    return False, _startup_failure_message(startup_log)


def stop_bot(*, wait_seconds: float = 0.0, max_rounds: int = 1) -> tuple[bool, str]:
    del wait_seconds, max_rounds
    initial = list_bot_processes(force=True)
    if not initial:
        _clear_pid_file()
        return True, "机器人未在运行。"

    ok, stopped, remaining = _stop_all_bots(timeout=10.0)
    if not ok:
        return False, f"未能完全停止，仍有 {len(remaining)} 个进程 (PID: {', '.join(map(str, remaining))})。"
    return True, f"已停止 {len(stopped)} 个 bot 进程。"


def restart_bot() -> tuple[bool, str]:
    ok, message = _check_can_launch()
    if not ok:
        return False, message

    ok, stopped, remaining = _stop_all_bots(timeout=10.0)
    if not ok:
        return False, f"重启失败：无法停止现有进程 (PID: {', '.join(map(str, remaining))})。"

    before_log = _bot_log_snapshot()
    startup_log, launched_pid = _launch_bot_process()
    ready, ready_pid, current = _wait_for_started(launched_pid, before_log, startup_log)
    invalidate_process_cache()

    if ready and ready_pid:
        stopped_note = f"已停止 {len(stopped)} 个旧进程，" if stopped else ""
        return True, f"机器人已重启 ({stopped_note}新 PID: {ready_pid})"

    if len(current) > 1:
        return False, f"重启异常：检测到多个 bot 进程 (PID: {', '.join(map(str, current))})。请先停止。"
    return False, _startup_failure_message(startup_log)


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
