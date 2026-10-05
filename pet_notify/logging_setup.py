"""Logging 設定：logs/app.log（輪替），含時間戳、層級與完整 traceback。"""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from . import app_paths

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_qt_logger = logging.getLogger("qt")


def setup_logging(level: int = logging.INFO) -> None:
    app_paths.LOGS.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    file_handler = RotatingFileHandler(
        app_paths.LOGS / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # pythonw / 打包後的無主控台模式沒有 stderr
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("unhandled").critical("未處理的例外", exc_info=(exc_type, exc, tb))


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    logging.getLogger("unhandled").critical(
        "執行緒 %s 發生未處理的例外",
        args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def install_qt_message_handler() -> None:
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(msg_type, _context, message):
        _qt_logger.log(levels.get(msg_type, logging.INFO), message)

    qInstallMessageHandler(handler)
