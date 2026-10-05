"""可取消的 OAuth 本機授權流程。

google_auth_oauthlib 的 run_local_server() 會一直阻塞到瀏覽器回傳結果或逾時；
使用者直接關掉授權分頁時，程式無從得知，只能乾等。這裡改成每 0.5 秒檢查一次取消旗標，
讓使用者可以在設定器按「取消登入」後立刻重試。
"""
from __future__ import annotations

import logging
import threading
import time
import webbrowser
import wsgiref.simple_server
import wsgiref.util
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)

POLL_SECONDS = 0.5
DEFAULT_TIMEOUT = 180

_PAGE = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><title>桌寵小提醒</title>
<style>body{{font-family:"Microsoft JhengHei UI",sans-serif;background:#FFF7F9;color:#4A3B3F;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{background:#fff;border:1px solid #F0C9D5;border-radius:16px;padding:32px 40px;text-align:center}}
h1{{font-size:22px;margin:0 0 8px}}</style></head>
<body><div class="card"><h1>{title}</h1><p>{body}</p></div></body></html>"""


class AuthCancelled(Exception):
    """使用者取消登入。"""


class AuthDenied(Exception):
    """使用者在 Google 授權頁面按了拒絕。"""


class AuthTimeout(Exception):
    """等太久沒有收到授權結果。"""


class _RedirectApp:
    def __init__(self):
        self.result_uri: str | None = None

    def __call__(self, environ, start_response):
        uri = wsgiref.util.request_uri(environ)
        query = parse_qs(urlparse(uri).query)
        # 瀏覽器可能會順便要 /favicon.ico 之類的東西，只接受帶 code 或 error 的請求
        if "code" not in query and "error" not in query:
            start_response("404 Not Found", [("Content-type", "text/plain; charset=utf-8")])
            return [b"not found"]
        self.result_uri = uri
        if "error" in query:
            title, body = "已取消授權", "桌寵沒有取得日曆權限。可以關閉這個分頁，回到設定器重新登入。"
        else:
            title, body = "授權完成 🎉", "可以關閉這個分頁，回到桌寵囉！"
        start_response("200 OK", [("Content-type", "text/html; charset=utf-8")])
        return [_PAGE.format(title=title, body=body).encode("utf-8")]


class _QuietHandler(wsgiref.simple_server.WSGIRequestHandler):
    # 瀏覽器會預先建立連線但不送資料，沒有逾時的話會卡在讀取，取消也無法生效
    timeout = 2

    def log_message(self, format, *args):  # noqa: A002 - 覆寫父類別簽名
        log.debug("OAuth 回呼：" + format, *args)


class _QuietServer(wsgiref.simple_server.WSGIServer):
    def handle_error(self, request, client_address):
        # 閒置連線逾時屬於正常狀況，記 debug 就好，不要把 traceback 印到主控台
        log.debug("OAuth 回呼連線錯誤（%s）", client_address, exc_info=True)


def run_cancellable_flow(flow, cancel: threading.Event, timeout: float = DEFAULT_TIMEOUT):
    """開瀏覽器授權並等待回傳；cancel 被設定時拋出 AuthCancelled。回傳 Credentials。"""
    app = _RedirectApp()
    server = wsgiref.simple_server.make_server("127.0.0.1", 0, app, server_class=_QuietServer, handler_class=_QuietHandler)
    try:
        flow.redirect_uri = f"http://127.0.0.1:{server.server_port}/"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        log.info("開啟瀏覽器進行 Google 授權（本機 port %d）", server.server_port)
        webbrowser.open(auth_url, new=1, autoraise=True)

        server.timeout = POLL_SECONDS
        deadline = time.monotonic() + timeout
        while app.result_uri is None:
            if cancel.is_set():
                raise AuthCancelled()
            if time.monotonic() > deadline:
                raise AuthTimeout()
            server.handle_request()

        query = parse_qs(urlparse(app.result_uri).query)
        if "error" in query:
            raise AuthDenied(query["error"][0])
        # oauthlib 要求 https，本機回呼是 http，比照官方做法替換
        flow.fetch_token(authorization_response=app.result_uri.replace("http://", "https://", 1))
        return flow.credentials
    finally:
        server.server_close()
