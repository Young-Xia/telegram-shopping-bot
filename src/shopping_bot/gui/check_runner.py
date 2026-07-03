from __future__ import annotations

import asyncio
import importlib.util
import io
import sys
from contextlib import redirect_stdout

from shopping_bot.gui.paths import project_root


def run_setup_checks(*, write_test: bool = False) -> tuple[bool, str]:
    root = project_root()
    sys.path.insert(0, str(root / "src"))

    spec = importlib.util.spec_from_file_location("check_setup", root / "scripts" / "check_setup.py")
    if spec is None or spec.loader is None:
        return False, "找不到 scripts/check_setup.py"
    check_setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_setup)

    buffer = io.StringIO()
    ok = True

    async def _run() -> None:
        nonlocal ok
        old_argv = sys.argv
        sys.argv = ["check_setup.py"] + (["--write-test"] if write_test else [])
        try:
            with redirect_stdout(buffer):
                await check_setup.main()
        except SystemExit as exc:
            if exc.code not in (0, None):
                ok = False
        finally:
            sys.argv = old_argv

    try:
        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        ok = False
        buffer.write(f"\n检查失败: {exc}")

    output = buffer.getvalue().strip()
    if not output:
        output = "检查完成，无输出。" if ok else "检查失败。"
    return ok, output
