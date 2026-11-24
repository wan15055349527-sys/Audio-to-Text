"""Desktop entry point and private loopback transport."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit, unquote
import argparse
import ctypes
import json
import logging
import msvcrt
import os
import re
import secrets
import sys
import time

import webview

from library import Library, export_text

ASSETS = Path(__file__).resolve().parent / "web"
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
TYPES = {
    "index.html": "text/html; charset=utf-8", "desk.css": "text/css; charset=utf-8",
    "desk.js": "text/javascript; charset=utf-8", "demo.json": "application/json",
    "demo.mp3": "audio/mpeg",
}


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, library):
        super().__init__(("127.0.0.1", 0), Handler)
        self.library = library
        self.token = secrets.token_urlsafe(32)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}/{self.token}/"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logging.debug(format, *args)

    def route(self):
        host = f"127.0.0.1:{self.server.server_port}"
        expected = f"/{self.server.token}/"
        path = urlsplit(self.path).path
        if self.headers.get("Host") != host or not path.startswith(expected):
            raise FileNotFoundError
        if self.headers.get("Origin") not in (None, f"http://{host}"):
            raise FileNotFoundError
        return path[len(expected):].split("/")

    def headers_out(self, mime, size, *, status=200, extras=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extras:
            for key, val in extras.items():
                self.send_header(key, val)
        self.end_headers()

    def json_out(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.headers_out("application/json; charset=utf-8", len(data), status=status)
        self.wfile.write(data)

    def read_json(self, size):
        if not 0 < size <= 131072:
            raise ValueError("请求大小不正确。")
        return json.loads(self.rfile.read(size))

    def file_out(self, file, mime, *, audio=False):
        size = file.stat().st_size
        start, end = 0, size - 1
        headers = {"Accept-Ranges": "bytes"} if audio else {}
        code = 200
        request = self.headers.get("Range") if audio else None
        if request:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", request)
            if match and match[1]:
                start = int(match[1])
                end = min(end, int(match[2])) if match[2] else end
            elif match and match[2]:
                start = max(0, size - int(match[2]))
            else:
                start = size
            if not 0 <= start <= end < size:
                self.headers_out(mime, 0, status=416, extras={"Content-Range": f"bytes */{size}"})
                return
            code = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        if mime.startswith("text/html"):
            headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; connect-src 'self'; media-src 'self'; img-src 'self' data:; "
                "base-uri 'none'; frame-ancestors 'none'"
            )
        self.headers_out(mime, end - start + 1, status=code, extras=headers)
        with file.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                block = source.read(min(remaining, 256 * 1024))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    @property
    def library(self):
        return self.server.library

    def do_GET(self):
        try:
            parts = self.route()
            if len(parts) == 1:
                name = parts[0] or "index.html"
                if name in TYPES:
                    self.file_out(ASSETS / name, TYPES[name], audio=name == "demo.mp3")
                    return
            if parts == ["api", "jobs"]:
                self.json_out(self.library.list())
                return
            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                self.json_out(self.library.get(parts[2]))
                return
            if len(parts) == 2 and parts[0] == "audio":
                self.library.get(parts[1])
                self.file_out(self.library.preview(parts[1]), "audio/mpeg", audio=True)
                return
            raise FileNotFoundError
        except (FileNotFoundError, KeyError):
            self.json_out({"error": "找不到文件或稿件。"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        try:
            parts = self.route()
            size = int(self.headers.get("Content-Length", "0"))
            if parts == ["api", "import"]:
                name = unquote(self.headers.get("X-TingGao-Filename", ""))
                if not 0 < size <= 20 * 1024**3 or not name or len(name) > 255:
                    raise ValueError("请选择小于 20 GB 的音视频文件。")
                self.json_out(self.library.add_upload(Path(name).name, self.rfile, size), 201)
                return
            payload = self.read_json(size)
            if parts == ["api", "start"]:
                self.json_out(self.library.enqueue(payload["ids"], payload.get("language", "")))
                return
            if len(parts) == 4 and parts[:2] == ["api", "jobs"]:
                ident, action = parts[2:]
                if action == "cancel":
                    self.json_out(self.library.cancel(ident))
                    return
                if action == "edit":
                    self.json_out(self.library.edit(ident, payload["row"], payload["text"]))
                    return
                if action == "review":
                    self.json_out({"text": self.library.review(ident, payload["row"])})
                    return
            raise FileNotFoundError
        except (FileNotFoundError, KeyError):
            self.json_out({"error": "找不到文件或稿件。"}, 404)
        except (ValueError, TypeError) as error:
            self.json_out({"error": str(error)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            logging.exception("Local request failed")
            self.json_out({"error": "操作失败，请重试。"}, 500)


class Desktop:
    def __init__(self, library):
        self._library = library

    def _bind(self, window):
        self._window = window

    def choose_files(self):
        selected = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("音频和视频 (*.mp3;*.wav;*.m4a;*.flac;*.aac;*.ogg;*.opus;*.mp4;*.mov;*.mkv;*.webm;*.avi)",
                        "所有文件 (*.*)"),
        )
        return [self._library.add(name) for name in selected or ()]

    def save_as(self, ident, kind, sample_rows=None):
        if kind not in {"txt", "srt"}:
            raise ValueError("请选择 TXT 或 SRT。")
        job = self._library.get(ident) if ident != "sample" else {"name": "雨后的街道", "rows": sample_rows}
        if not job["rows"]:
            raise ValueError("当前还没有可导出的文字。")
        filename = Path(job["name"]).stem + "." + kind
        selected = self._window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename=filename,
            file_types=(f"{kind.upper()} 文件 (*.{kind})",),
        )
        if not selected:
            return False
        path = Path(selected[0] if isinstance(selected, (list, tuple)) else selected)
        content = export_text(job["rows"], kind)
        path.write_text(content, encoding="utf-8-sig" if kind == "txt" else "utf-8")
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--state", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--models", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--ready", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--gui-check", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    home = args.state or Path(os.environ["LOCALAPPDATA"]) / "TingGao"
    home.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=home / "tinggao.log", encoding="utf-8", level=logging.WARNING)
    with (home / "instance.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            ctypes.windll.user32.MessageBoxW(0, "听稿已经打开。", "听稿", 0x40)
            return
        library = Library(home, args.models or ROOT / "models")
        server = LocalServer(library)
        Thread(target=server.serve_forever, daemon=True).start()
        if args.ready:
            args.ready.write_text(server.url, encoding="ascii")
        try:
            if args.serve:
                while True:
                    time.sleep(1)
            bridge = Desktop(library)
            window = webview.create_window(
                "听稿", server.url, js_api=bridge, width=1260, height=800,
                min_size=(640, 530), text_select=True,
            )
            bridge._bind(window)
            if args.gui_check:
                def on_gui_ready():
                    result = window.evaluate_js(
                        "({brand:document.querySelector('.topbar .brand').textContent.trim(),"
                        "hasBridge:typeof window.pywebview?.api?.choose_files==='function',"
                        "assets:!!document.querySelector('script[src]')})"
                    )
                    args.gui_check.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    window.destroy()
                window.events.loaded += on_gui_ready
            webview.start(gui="edgechromium", private_mode=True)
        finally:
            server.shutdown()
            server.server_close()
            library.shutdown()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.exception("TingGao failed")
        if "--serve" not in sys.argv:
            ctypes.windll.user32.MessageBoxW(
                0, "听稿启动失败。请确认完整解压程序，且系统已安装 Microsoft Edge WebView2。", "听稿", 0x10,
            )
        raise

