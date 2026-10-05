"""桌寵小提醒 進入點。

用法：
    .venv\\Scripts\\python main.py              一般啟動
    .venv\\Scripts\\python main.py --settings   啟動並開啟設定器
    .venv\\Scripts\\python main.py --debug      輸出 DEBUG 等級 log
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys

from pet_notify import app_paths
from pet_notify.logging_setup import install_qt_message_handler, setup_logging

log = logging.getLogger("main")


def _install_ctrl_c(pet_app) -> None:
    """讓主控台的 Ctrl+C 可以結束程式。

    Qt 事件迴圈在 C++ 裡執行，Python 收到 SIGINT 後要等直譯器拿回控制權才會處理；
    用一個空的 QTimer 定期讓出控制權，訊號處理函式才有機會執行。
    """
    from PySide6.QtCore import QTimer

    def on_sigint(_signum, _frame):
        log.info("收到 Ctrl+C，準備結束")
        pet_app.quit()

    signal.signal(signal.SIGINT, on_sigint)
    timer = QTimer(pet_app)
    timer.timeout.connect(lambda: None)
    timer.start(200)


def main() -> int:
    parser = argparse.ArgumentParser(description="桌寵小提醒")
    parser.add_argument("--settings", action="store_true", help="啟動後開啟設定器")
    parser.add_argument("--debug", action="store_true", help="輸出 DEBUG log")
    args = parser.parse_args()

    app_paths.ensure_dirs()
    setup_logging(logging.DEBUG if args.debug else logging.INFO)
    log.info("==== 桌寵小提醒 啟動 ====（資料夾：%s）", app_paths.ROOT)

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon

        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        qapp = QApplication(sys.argv)
        qapp.setApplicationName("DesktopPetNotify")
        qapp.setQuitOnLastWindowClosed(False)
        install_qt_message_handler()

        from pet_notify.single_instance import SingleInstance

        single = SingleInstance()
        if single.try_notify_existing():
            return 0
        single.listen()

        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("系統匣不可用，部分功能（系統通知）可能無法使用")

        from pet_notify.app import PetApp

        pet_app = PetApp(qapp)
        single.activated.connect(pet_app.open_settings)
        _install_ctrl_c(pet_app)
        pet_app.start()
        if args.settings:
            pet_app.open_settings()

        code = qapp.exec()
        log.info("==== 桌寵小提醒 結束（code=%s）====", code)
        return code
    except Exception:
        log.exception("啟動失敗")
        return 1


if __name__ == "__main__":
    sys.exit(main())
