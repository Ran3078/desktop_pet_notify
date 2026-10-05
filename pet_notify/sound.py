"""提醒音效：內建音效以 wave 模組產生，播放用 QSoundEffect。"""
from __future__ import annotations

import logging
import math
import struct
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QSoundEffect

from . import app_paths

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100
BUILTIN_SOUNDS = {"chime": "叮咚", "bell": "小鈴鐺", "pop": "啵"}


def _write_wav(path: Path, samples: list[float]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32000)) for s in samples))


def _tone(freq: float, dur: float, decay: float, harmonics=((1, 1.0),)) -> list[float]:
    n = int(SAMPLE_RATE * dur)
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = math.exp(-decay * t) * min(1.0, t * 200)  # 5ms 起音，避免爆音
        out.append(env * sum(a * math.sin(2 * math.pi * freq * h * t) for h, a in harmonics))
    return out


def _mix(*parts: tuple[float, list[float]], total: float) -> list[float]:
    buf = [0.0] * int(SAMPLE_RATE * total)
    for offset, samples in parts:
        start = int(SAMPLE_RATE * offset)
        for i, s in enumerate(samples):
            if start + i < len(buf):
                buf[start + i] += s
    peak = max(1e-6, max(abs(s) for s in buf))
    return [s / peak * 0.8 for s in buf]


def _generate(name: str) -> list[float]:
    if name == "chime":
        return _mix((0.0, _tone(1046.5, 0.6, 5)), (0.18, _tone(784.0, 0.8, 4)), total=1.0)
    if name == "bell":
        bell = ((1, 1.0), (2.76, 0.4), (5.4, 0.2))
        return _mix((0.0, _tone(1318.5, 0.9, 6, bell)), (0.25, _tone(1318.5, 0.9, 6, bell)), total=1.2)
    if name == "pop":
        n = int(SAMPLE_RATE * 0.18)
        out, phase = [], 0.0
        for i in range(n):
            t = i / SAMPLE_RATE
            freq = 900 - 2500 * t  # 音高快速下滑
            phase += 2 * math.pi * freq / SAMPLE_RATE
            out.append(math.sin(phase) * math.exp(-18 * t))
        return _mix((0.0, out), total=0.2)
    raise ValueError(name)


def ensure_builtin_sounds() -> None:
    app_paths.SOUNDS.mkdir(parents=True, exist_ok=True)
    for name in BUILTIN_SOUNDS:
        path = app_paths.SOUNDS / f"{name}.wav"
        if not path.exists():
            _write_wav(path, _generate(name))
            log.info("已產生內建音效：%s", path.name)


def sound_path(name: str, custom_path: str) -> Path | None:
    if name == "custom":
        p = Path(custom_path) if custom_path else None
        if p and p.exists():
            return p
        log.warning("自訂音效不存在：%r，改用內建音效", custom_path)
        name = "chime"
    return app_paths.SOUNDS / f"{name}.wav"


class SoundPlayer(QObject):
    def __init__(self, config):
        super().__init__()
        self._config = config
        self._effect = QSoundEffect(self)
        self._effect.statusChanged.connect(self._on_status)

    def _on_status(self) -> None:
        if self._effect.status() == QSoundEffect.Status.Error:
            log.error("音效載入失敗：%s", self._effect.source().toLocalFile())

    def play(self, force: bool = False) -> None:
        s = self._config.settings
        if not (s.sound_enabled or force):
            return
        self.preview(s.sound_name, s.custom_sound_path, s.volume)

    def preview(self, name: str, custom_path: str, volume: float) -> None:
        path = sound_path(name, custom_path)
        if path is None:
            return
        url = QUrl.fromLocalFile(str(path))
        if self._effect.source() != url:
            self._effect.setSource(url)
        self._effect.setVolume(max(0.0, min(1.0, volume)))
        self._effect.play()
