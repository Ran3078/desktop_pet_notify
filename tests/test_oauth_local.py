import socket
import threading
import time
import unittest
import urllib.request
from unittest import mock
from urllib.parse import urlparse

from pet_notify.cal import oauth_local
from pet_notify.cal.oauth_local import AuthCancelled, AuthDenied, AuthTimeout, run_cancellable_flow


class FakeFlow:
    def __init__(self):
        self.redirect_uri = None
        self.fetched = None
        self.credentials = "CREDS"
        self.ready = threading.Event()

    def authorization_url(self, **kwargs):
        return "https://accounts.example/auth", "state"

    def fetch_token(self, authorization_response):
        self.fetched = authorization_response


class OAuthLocalTest(unittest.TestCase):
    def setUp(self):
        self.flow = FakeFlow()
        # 不要真的開瀏覽器：記錄被呼叫，並通知測試可以開始打本機回呼
        patcher = mock.patch.object(oauth_local.webbrowser, "open", side_effect=lambda *a, **k: self.flow.ready.set())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cancel = threading.Event()
        self.result = {}

    def start_flow(self, timeout=10):
        def target():
            started = time.monotonic()
            try:
                self.result["value"] = run_cancellable_flow(self.flow, self.cancel, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                self.result["error"] = exc
            self.result["elapsed"] = time.monotonic() - started

        t = threading.Thread(target=target, daemon=True)
        t.start()
        self.assertTrue(self.flow.ready.wait(5), "瀏覽器應該被開啟")
        return t

    def port(self):
        return urlparse(self.flow.redirect_uri).port

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port()}{path}", timeout=5) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, ""

    def test_closed_tab_then_cancel(self):
        t = self.start_flow()
        time.sleep(0.3)  # 使用者關掉分頁，什麼都沒送回來
        cancel_at = time.monotonic()
        self.cancel.set()
        t.join(3)
        self.assertFalse(t.is_alive())
        self.assertIsInstance(self.result["error"], AuthCancelled)
        self.assertLess(time.monotonic() - cancel_at, 1.5)

    def test_cancel_while_browser_holds_idle_connection(self):
        t = self.start_flow()
        # 模擬瀏覽器預先建立連線但不送任何資料
        idle = socket.create_connection(("127.0.0.1", self.port()))
        self.addCleanup(idle.close)
        time.sleep(0.2)
        self.cancel.set()
        t.join(8)
        self.assertFalse(t.is_alive(), "閒置連線不應讓取消永遠卡住")
        self.assertIsInstance(self.result["error"], AuthCancelled)

    def test_access_denied(self):
        t = self.start_flow()
        status, body = self.get("/?error=access_denied&state=state")
        t.join(3)
        self.assertEqual(status, 200)
        self.assertIn("已取消授權", body)
        self.assertIsInstance(self.result["error"], AuthDenied)

    def test_favicon_ignored_then_success(self):
        t = self.start_flow()
        status, _ = self.get("/favicon.ico")
        self.assertEqual(status, 404)
        self.assertTrue(t.is_alive(), "favicon 不應結束授權流程")
        status, body = self.get("/?code=abc&state=state")
        t.join(3)
        self.assertEqual(status, 200)
        self.assertIn("授權完成", body)
        self.assertEqual(self.result["value"], "CREDS")
        self.assertTrue(self.flow.fetched.startswith("https://127.0.0.1:"))
        self.assertIn("code=abc", self.flow.fetched)

    def test_timeout(self):
        t = self.start_flow(timeout=1)
        t.join(4)
        self.assertIsInstance(self.result["error"], AuthTimeout)


if __name__ == "__main__":
    unittest.main()
