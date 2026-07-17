"""Native Windows entry point for the xianyuxian desktop client."""

from __future__ import annotations

import asyncio
import ctypes
import os
import socket
import sys
import threading
import time
import traceback
import json
from pathlib import Path
from types import ModuleType


APP_NAME = "xianyuxian"
APP_TITLE = "闲鱼超级管家"
LOCAL_API_HOST = "127.0.0.1"
LOCAL_API_PORT = 18765
MUTEX_NAME = r"Local\xianyuxian.desktop.client.v1"
STARTUP_TIMEOUT_SECONDS = 180.0


def application_data_root() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("Windows LOCALAPPDATA 环境变量不可用")
    return Path(local_app_data) / APP_NAME


def installation_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def prepare_runtime_environment() -> Path:
    """Prepare writable storage and locked-down loopback server settings."""
    data_root = application_data_root()
    for child in ("data", "logs", "backups", "cache"):
        (data_root / child).mkdir(parents=True, exist_ok=True)

    os.environ["XIANYUXIAN_DESKTOP"] = "1"
    os.environ["API_HOST"] = LOCAL_API_HOST
    os.environ["API_PORT"] = str(LOCAL_API_PORT)
    os.environ["ALLOW_REMOTE_API"] = "0"
    os.environ["DB_PATH"] = str(data_root / "data" / "xianyu_data.db")
    os.environ["XIANYUXIAN_UPLOADS_DIR"] = str(data_root / "data" / "uploads" / "images")
    os.environ.setdefault("SQL_LOG_ENABLED", "false")
    os.environ.setdefault("PYTHONUTF8", "1")

    browser_root = installation_root() / "playwright"
    if browser_root.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_root)
    runtime_root = installation_root() / "runtime"
    if (runtime_root.exists()):
        os.environ["PATH"] = str(runtime_root) + os.pathsep + os.environ.get("PATH", "")

    os.chdir(data_root)
    return data_root


class SingleInstance:
    """Per-user named mutex preventing duplicate local API processes."""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self) -> None:
        self.handle = None

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        self.handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
        return ctypes.get_last_error() != self.ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self.handle and sys.platform == "win32":
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self.handle)
            self.handle = None


def _show_error(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)
    else:
        print(message, file=sys.stderr)


def _port_is_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((LOCAL_API_HOST, LOCAL_API_PORT))
            return True
        except OSError:
            return False


def _wait_for_server(worker: threading.Thread, timeout: float = STARTUP_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not worker.is_alive():
            return False
        try:
            with socket.create_connection((LOCAL_API_HOST, LOCAL_API_PORT), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.15)
    return False


class BackendRunner:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.error_log_path = log_dir / "desktop-startup-error.log"
        self.activity_log_path = log_dir / "desktop-startup.log"
        self.module: ModuleType | None = None
        self.error: str | None = None
        self.phase = "等待启动"
        self.started_at = time.monotonic()
        self._status_lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name="xianyuxian-backend", daemon=True)

    def _record(self, phase: str) -> None:
        elapsed = time.monotonic() - self.started_at
        line = f"[{elapsed:8.2f}s] {phase}\n"
        with self._status_lock:
            self.phase = phase
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with self.activity_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def _run(self) -> None:
        try:
            self._record("正在加载本地服务模块")
            import Start

            self.module = Start
            self._record("本地服务模块加载完成，正在启动 API")
            asyncio.run(Start.main())
            self._record("本地服务已停止")
        except BaseException:
            self.error = traceback.format_exc()
            self.error_log_path.parent.mkdir(parents=True, exist_ok=True)
            self.error_log_path.write_text(self.error, encoding="utf-8")
            self._record("本地服务启动异常")

    def start(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.error_log_path.unlink(missing_ok=True)
        self.activity_log_path.write_text("", encoding="utf-8")
        self.started_at = time.monotonic()
        self._record("桌面启动器已创建后台线程")
        self.thread.start()

    def failure_detail(self, timeout: float) -> str:
        if self.error:
            return self.error

        stack = ""
        thread_id = self.thread.ident
        if thread_id is not None:
            frame = sys._current_frames().get(thread_id)
            if frame is not None:
                stack = "".join(traceback.format_stack(frame))

        elapsed = time.monotonic() - self.started_at
        diagnostic = (
            f"elapsed_seconds={elapsed:.2f}\n"
            f"phase={self.phase}\n"
            f"thread_alive={self.thread.is_alive()}\n\n"
            f"Backend thread stack:\n{stack or '(stack unavailable)'}"
        )
        self.error_log_path.write_text(diagnostic, encoding="utf-8")
        return (
            f"本地服务在 {int(timeout)} 秒内未能完成首次启动。\n"
            f"当前阶段：{self.phase}\n"
            f"诊断日志：{self.error_log_path}"
        )

    def stop(self) -> None:
        if self.module and hasattr(self.module, "request_shutdown"):
            self.module.request_shutdown()
        self.thread.join(timeout=8)


class TrayController:
    """Windows notification-area controller; closing the window keeps tasks running."""

    def __init__(self, window) -> None:
        self.window = window
        self.icon = None
        self.exit_requested = False
        self.available = False

    @staticmethod
    def _image():
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (64, 64), "#FFE815")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=24)
        box = draw.textbbox((0, 0), "XY", font=font)
        x = (64 - (box[2] - box[0])) / 2
        y = (64 - (box[3] - box[1])) / 2
        draw.text((x, y), "XY", fill="#111111", font=font)
        return image

    def show(self, *_args) -> None:
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass

    def quit(self, *_args) -> None:
        self.exit_requested = True
        if self.icon:
            self.icon.stop()
        self.window.destroy()

    def on_closing(self) -> bool | None:
        if self.exit_requested or not self.available:
            return None
        self.window.hide()
        return False

    def run(self) -> None:
        import pystray

        self.icon = pystray.Icon(
            "xianyuxian",
            self._image(),
            APP_TITLE,
            menu=pystray.Menu(
                pystray.MenuItem("打开主窗口", self.show, default=True),
                pystray.MenuItem("退出", self.quit),
            ),
        )
        self.available = True
        try:
            self.icon.run()
        finally:
            self.available = False

    def stop(self) -> None:
        if self.icon:
            self.icon.stop()


def run_self_test() -> int:
    """Exercise the Windows-only trust and storage primitives after packaging."""
    root = prepare_runtime_environment()
    report_path = root / "logs" / "windows-self-test.json"
    checks: dict[str, object] = {"passed": False}
    runner: BackendRunner | None = None
    try:
        from desktop_client import build_config
        from desktop_client.licensing.device import get_windows_device_identity
        from desktop_client.licensing.storage import DPAPIProtector
        import httpx

        identity = get_windows_device_identity()
        protector = DPAPIProtector()
        probe = os.urandom(32)
        protected = protector.protect(probe)
        if protector.unprotect(protected) != probe:
            raise RuntimeError("DPAPI round-trip mismatch")
        response = httpx.get(f"{build_config.LICENSE_API_BASE_URL}/v1/public-key", timeout=15)
        response.raise_for_status()
        server_key = response.json().get("public_key")
        if server_key != build_config.LICENSE_PUBLIC_KEY_BASE64:
            raise RuntimeError("embedded Ed25519 public key does not match the server")
        node_result = os.popen('node --version').read().strip()
        if not node_result.startswith('v'):
            raise RuntimeError("bundled Node.js runtime is unavailable")

        if not _port_is_available():
            raise RuntimeError(f"local API port {LOCAL_API_PORT} is already in use")
        runner = BackendRunner(root / "logs")
        runner.start()
        if not _wait_for_server(runner.thread, STARTUP_TIMEOUT_SECONDS):
            raise RuntimeError(runner.failure_detail(STARTUP_TIMEOUT_SECONDS))
        local_response = httpx.get(
            f"http://{LOCAL_API_HOST}:{LOCAL_API_PORT}/api/license/status",
            timeout=15,
        )
        local_response.raise_for_status()
        checks.update({
            "passed": True,
            "app_version": build_config.APP_VERSION,
            "device_id_suffix": identity.device_id[-12:],
            "dpapi": "ok",
            "license_api": "ok",
            "node": node_result,
            "local_backend": "ok",
            "backend_startup_seconds": round(time.monotonic() - runner.started_at, 2),
        })
        result = 0
    except Exception as exc:
        checks.update({"error": str(exc), "traceback": traceback.format_exc()})
        if runner:
            if runner.activity_log_path.exists():
                checks["backend_activity"] = runner.activity_log_path.read_text(encoding="utf-8")[-12000:]
            if runner.error_log_path.exists():
                checks["backend_diagnostic"] = runner.error_log_path.read_text(encoding="utf-8")[-12000:]
        result = 1
    finally:
        if runner:
            runner.stop()
    report_path.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def run() -> int:
    if sys.platform != "win32":
        raise RuntimeError("xianyuxian Windows client can only run on Windows")

    if "--self-test" in sys.argv:
        return run_self_test()

    mutex = SingleInstance()
    if not mutex.acquire():
        _show_error("闲鱼超级管家已经在运行。")
        return 0

    runner: BackendRunner | None = None
    try:
        data_root = prepare_runtime_environment()
        if not _port_is_available():
            _show_error(f"本地端口 {LOCAL_API_PORT} 已被其他程序占用，请关闭占用程序后重试。")
            return 2

        runner = BackendRunner(data_root / "logs")
        runner.start()
        if not _wait_for_server(runner.thread, STARTUP_TIMEOUT_SECONDS):
            detail = runner.failure_detail(STARTUP_TIMEOUT_SECONDS)
            _show_error(f"客户端启动失败。\n\n{detail[-1600:]}")
            return 3

        import webview

        window = webview.create_window(
            APP_TITLE,
            f"http://{LOCAL_API_HOST}:{LOCAL_API_PORT}/",
            width=1280,
            height=820,
            min_size=(1024, 680),
            resizable=True,
            background_color="#F4F5F7",
            text_select=True,
        )
        tray = TrayController(window)
        window.events.closing += tray.on_closing
        window.events.closed += runner.stop
        webview.start(tray.run, gui="edgechromium", debug=False, private_mode=True)
        tray.stop()
        return 0
    except Exception:
        detail = traceback.format_exc()
        try:
            root = application_data_root()
            (root / "logs").mkdir(parents=True, exist_ok=True)
            (root / "logs" / "desktop-fatal-error.log").write_text(detail, encoding="utf-8")
        except Exception:
            pass
        _show_error(f"客户端发生严重错误。\n\n{detail[-1600:]}")
        return 1
    finally:
        if runner and runner.thread.is_alive():
            runner.stop()
        mutex.release()


if __name__ == "__main__":
    raise SystemExit(run())
