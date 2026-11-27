"""CPU recognition and local audio preview for TingGao."""

import os
from pathlib import Path
from threading import Event, Lock

import av
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions, get_speech_timestamps
import sherpa_onnx

RATE = 16000
THREADS = min(8, max(1, (os.cpu_count() or 2) - 1))


class Cancelled(Exception):
    pass


def check_cancelled(stop):
    if stop.is_set():
        raise Cancelled


def decode(source, stop):
    blocks = []
    resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
    try:
        with av.open(str(source)) as media:
            if not media.streams.audio:
                raise ValueError("这个文件没有音轨。")
            for frame in media.decode(media.streams.audio[0]):
                check_cancelled(stop)
                frame.pts = None
                blocks.extend(part.to_ndarray().reshape(-1) for part in resampler.resample(frame))
            blocks.extend(part.to_ndarray().reshape(-1) for part in resampler.resample(None))
    except av.FFmpegError as error:
        raise ValueError("无法读取这个音视频。请确认文件完整且包含音轨。") from error
    if not blocks:
        raise ValueError("音轨为空。")
    return np.concatenate(blocks)


def write_preview(audio, path, stop):
    staging = path.with_suffix(".partial")
    try:
        with av.open(str(staging), "w", format="mp3") as media:
            stream = media.add_stream("libmp3lame", rate=RATE)
            stream.layout = "mono"
            stream.bit_rate = 48000
            for pos in range(0, audio.size, 16000):
                check_cancelled(stop)
                frame = av.AudioFrame.from_ndarray(audio[None, pos:pos + 16000], format="flt", layout="mono")
                frame.sample_rate = RATE
                for packet in stream.encode(frame):
                    media.mux(packet)
            for packet in stream.encode(None):
                media.mux(packet)
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def waveform(audio):
    bins = np.array_split(audio, min(len(audio), 165))
    peaks = [float(np.sqrt(np.mean(block ** 2))) for block in bins]
    high = max(max(peaks), 0.0001)
    return [round(min(1, peak / high), 3) for peak in peaks]


class Engines:
    def __init__(self, models):
        self.models = Path(models)
        self.whisper = None
        self.paraformer = None
        self.review_lock = Lock()

    def transcribe(self, audio, language, stop, report):
        if language == "zh-accurate":
            return self.transcribe_mandarin(audio, stop, report), "zh"
        if self.whisper is None:
            folder = self.models / "whisper-base"
            if not (folder / "model.bin").is_file():
                raise ValueError("找不到 Whisper Base 模型。请完整解压软件目录。")
            self.whisper = WhisperModel(
                str(folder), device="cpu", compute_type="int8",
                cpu_threads=THREADS, local_files_only=True,
            )
        check_cancelled(stop)
        segments, info = self.whisper.transcribe(
            audio, language=language or None, beam_size=5, vad_filter=True,
        )
        rows = []
        duration = audio.size / RATE
        for segment in segments:
            check_cancelled(stop)
            end = min(duration, segment.end)
            if segment.text.strip() and segment.start < end:
                rows.append({"start": segment.start, "end": end, "text": segment.text.strip()})
            report(min(.99, end / duration))
        return rows, info.language

    def recognize_mandarin(self, audio):
        with self.review_lock:
            if self.paraformer is None:
                folder = self.models / "paraformer"
                if not (folder / "model.int8.onnx").is_file():
                    raise ValueError("找不到 Paraformer 模型。请完整解压软件目录。")
                self.paraformer = sherpa_onnx.OfflineRecognizer.from_paraformer(
                    paraformer=str(folder / "model.int8.onnx"),
                    tokens=str(folder / "tokens.txt"),
                    sample_rate=RATE, num_threads=THREADS,
                )
            reader = self.paraformer.create_stream()
            reader.accept_waveform(RATE, audio)
            self.paraformer.decode_stream(reader)
            return reader.result.text.strip()

    def transcribe_mandarin(self, audio, stop, report):
        check_cancelled(stop)
        options = VadOptions(max_speech_duration_s=16, min_silence_duration_ms=430, speech_pad_ms=200)
        periods = get_speech_timestamps(audio, options, sampling_rate=RATE)
        rows = []
        for period in periods:
            check_cancelled(stop)
            start, end = period["start"], period["end"]
            text = self.recognize_mandarin(audio[start:end])
            if text:
                rows.append({"start": start / RATE, "end": end / RATE, "text": text})
            report(min(.99, end / audio.size))
        return rows

    def review(self, preview, start, end):
        audio = decode(preview, Event())
        section = audio[round(start * RATE):round(end * RATE)]
        if not section.size:
            raise ValueError("这个片段没有可复核的声音。")
        return self.recognize_mandarin(section)

