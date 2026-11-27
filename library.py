"""Local queue and durable transcript storage."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event, RLock
from uuid import uuid4
import json
import logging
import time

from engines import RATE, Cancelled, Engines, check_cancelled, decode, waveform, write_preview

LANGUAGES = {"", "zh", "zh-accurate", "en", "es", "ja", "ko", "fr", "de", "pt"}
ACTIVE = {"queued", "working", "stopping"}


class Library:
    def __init__(self, directory, models):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state = self.directory / "projects.json"
        original = json.loads(self.state.read_text(encoding="utf-8")) if self.state.exists() else []
        self.projects = {item["id"]: item for item in original}
        self.lock = RLock()
        self.workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recognition")
        self.engine = Engines(models)
        self.stops = {}
        for item in original:
            if item["status"] in ACTIVE:
                item.update(status="cancelled", message="上次转写中断。可重新开始。")
        if original:
            self._save()

    def _save(self):
        staging = self.state.with_suffix(".tmp")
        staging.write_text(json.dumps(list(self.projects.values()), ensure_ascii=False), encoding="utf-8")
        staging.replace(self.state)

    def root(self, ident):
        return self.directory / ident

    def preview(self, ident):
        return self.root(ident) / "preview.mp3"

    def list(self):
        with self.lock:
            return [
                {key: item[key] for key in ("id", "name", "status", "message", "progress", "duration", "revision")}
                for item in self.projects.values()
            ]

    def get(self, ident):
        with self.lock:
            return deepcopy(self.projects[ident])

    def patch(self, ident, *, save=True, **changes):
        with self.lock:
            item = self.projects[ident]
            item.update(changes)
            item["revision"] += 1
            if save:
                self._save()
            return deepcopy(item)

    def add(self, path, *, ident=None, name=None, owned=False):
        source = Path(path).absolute()
        if not source.is_file():
            raise ValueError("找不到选中的文件。")
        ident = ident or uuid4().hex
        project = {
            "id": ident, "name": name or source.name, "source": str(source),
            "owned": owned, "status": "ready", "message": "", "progress": 0,
            "duration": 0, "rows": [], "peaks": [], "language": "", "revision": 1,
        }
        with self.lock:
            self.root(ident).mkdir(exist_ok=True)
            self.projects[ident] = project
            self._save()
        return deepcopy(project)

    def add_upload(self, name, stream, size):
        ident = uuid4().hex
        folder = self.root(ident)
        folder.mkdir()
        suffix = Path(name).suffix[:12]
        path = folder / ("original" + (suffix if suffix.isascii() and suffix[1:].isalnum() else ""))
        try:
            with path.open("wb") as dest:
                remaining = size
                while remaining:
                    block = stream.read(min(remaining, 1024 * 1024))
                    if not block:
                        raise ValueError("文件传输提前结束。请重新导入。")
                    dest.write(block)
                    remaining -= len(block)
            return self.add(path, ident=ident, name=name, owned=True)
        except Exception:
            path.unlink(missing_ok=True)
            folder.rmdir()
            raise

    def enqueue(self, ids, language):
        if language not in LANGUAGES:
            raise ValueError("请选择支持的识别语言。")
        with self.lock:
            for ident in ids:
                if ident not in self.projects:
                    raise KeyError(ident)
            for ident in dict.fromkeys(ids):
                if self.projects[ident]["status"] not in {"ready", "failed", "cancelled"}:
                    continue
                self.patch(ident, status="queued", message="", progress=0)
                self.stops[ident] = Event()
                self.workers.submit(self._execute, ident, language, self.stops[ident])
        return self.list()

    def cancel(self, ident):
        with self.lock:
            if ident in self.stops and self.projects[ident]["status"] in ACTIVE:
                self.stops[ident].set()
                return self.patch(ident, status="stopping", message="正在停止…")
            return self.get(ident)

    def _execute(self, ident, language, stop):
        last = 0.0

        def report(progress):
            nonlocal last
            now = time.monotonic()
            if now - last >= 0.5:
                last = now
                self.patch(ident, save=False, progress=0.12 + 0.87 * progress, message="正在识别语音")

        try:
            check_cancelled(stop)
            item = self.patch(ident, status="working", message="正在读取音轨", progress=.03)
            if not Path(item["source"]).is_file():
                raise ValueError("找不到原始文件，请重新导入。")
            audio = decode(item["source"], stop)
            write_preview(audio, self.preview(ident), stop)
            self.patch(ident, duration=audio.size / RATE, peaks=waveform(audio),
                       progress=.12, message="正在识别语音")
            rows, detected = self.engine.transcribe(audio, language, stop, report)
            check_cancelled(stop)
            self.patch(ident, status="done", progress=1, rows=rows, language=detected,
                       message="" if rows else "这段音轨没有识别到可转写的语音。")
        except Cancelled:
            self.patch(ident, status="cancelled", message="已停止，可重新开始。")
        except Exception as error:
            logging.exception("Transcription failed for %s", ident)
            message = str(error) if isinstance(error, ValueError) else "转写失败。请重试，或尝试 MP3、WAV、MP4。"
            self.patch(ident, status="failed", message=message)
        finally:
            with self.lock:
                if self.stops.get(ident) is stop:
                    self.stops.pop(ident, None)

    def edit(self, ident, row, text):
        with self.lock:
            item = self.get(ident)
            if item["status"] != "done" or not 0 <= row < len(item["rows"]):
                raise ValueError("这段文字已不可用。")
            text = text.strip()
            if not text or len(text) > 20000:
                raise ValueError("请输入 1 到 20,000 个字符。")
            segment = item["rows"][row]
            segment.setdefault("original", segment["text"])
            segment["text"] = text
            return self.patch(ident, rows=item["rows"])

    def review(self, ident, row):
        item = self.get(ident)
        if item["status"] != "done" or not 0 <= row < len(item["rows"]):
            raise ValueError("这段文字已不可用。")
        segment = item["rows"][row]
        return self.engine.review(self.preview(ident), segment["start"], segment["end"])

    def shutdown(self):
        with self.lock:
            for stop in self.stops.values():
                stop.set()
        self.workers.shutdown(wait=True)


def subtitle_time(seconds):
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, tail = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{tail:03}"


def export_text(rows, kind):
    if kind not in {"txt", "srt"}:
        raise ValueError("请选择 TXT 或 SRT。")
    chunks = []
    for index, row in enumerate(rows, start=1):
        if kind == "txt":
            chunks.append(row["text"])
        else:
            start = subtitle_time(row["start"])
            end = subtitle_time(row["end"])
            chunks.append(f"{index}\n{start} --> {end}\n{row['text']}")
    return "\n\n".join(chunks) + "\n"

