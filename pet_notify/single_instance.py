"""單一實例：第二個實例啟動時通知第一個實例顯示設定器，然後自行結束。"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

SERVER_NAME = "desktop_pet_notify_single_instance"


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self):
        super().__init__()
        self._server: QLocalServer | None = None

    def try_notify_existing(self) -> bool:
        """若已有實例在執行，送出喚醒訊號並回傳 True。"""
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(500):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()
            log.info("偵測到已在執行的實例，已通知它顯示設定器")
            return True
        return False

    def listen(self) -> None:
        QLocalServer.removeServer(SERVER_NAME)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        if not self._server.listen(SERVER_NAME):
            log.warning("單一實例伺服器啟動失敗：%s", self._server.errorString())

    def _on_connection(self) -> None:
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        sock.readyRead.connect(lambda: self._read(sock))
        sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock: QLocalSocket) -> None:
        if bytes(sock.readAll()).strip() == b"show":
            self.activated.emit()
