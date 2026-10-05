"""主控：建立並串接所有元件。"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from .cal.models import CalendarEvent, local_now
from .cal.sync_worker import AuthState, CalendarController
from .config import ConfigManager
from .pet.pet_window import PetWindow
from .pet.skins.base import SLEEP
from .reminders import daily_brief
from .reminders.gatekeeper import Route
from .reminders.health import MESSAGES as HEALTH_MESSAGES
from .reminders.health import HealthReminder
from .reminders.notifier import Notification, NotificationCenter
from .reminders.pomodoro import Phase, Pomodoro
from .reminders.scheduler import Reminder, ReminderScheduler, describe_remaining
from .sound import SoundPlayer, ensure_builtin_sounds
from .state import StateManager
from .tray import Tray, render_icon
from .win_sys import SystemProbe

log = logging.getLogger(__name__)

PET_REWARD_COOLDOWN = 60.0
EVENT_BUBBLE_TIMEOUT = 600
PET_LINES = ["嘿嘿～", "好舒服～", "喵～", "再摸一下嘛！", "最喜歡你了！", "今天也辛苦了～"]


def _fmt_countdown(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class PetApp(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self._qapp = qapp
        # 介面是淺色系配色，固定使用淺色主題，避免 Windows 深色模式下出現白底白字
        qapp.styleHints().setColorScheme(Qt.ColorScheme.Light)
        ensure_builtin_sounds()
        self.config = ConfigManager()
        self.state = StateManager()
        self.probe = SystemProbe()
        self.sound = SoundPlayer(self.config)
        self.calendar = CalendarController(self.config)
        self.pomodoro = Pomodoro(self.config)
        self.pet = PetWindow(
            self.config,
            badge_provider=self._badge,
            pomodoro_focus=lambda: self.pomodoro.phase == Phase.FOCUS,
            pomodoro_running=lambda: self.pomodoro.running,
        )
        self.tray = Tray(render_icon(self.config.settings.color), self.pet.isVisible, lambda: self.pomodoro.running)
        self.notifier = NotificationCenter(self.config, self.probe, self.sound, self.pet.isVisible)
        self.scheduler = ReminderScheduler(self.config, self.state, lambda: self.calendar.events)
        self.health = HealthReminder(self.config, self.probe, lambda: self.pet.behavior.state == SLEEP)
        self._settings_window = None
        self._countdowns: dict[str, CalendarEvent] = {}
        self._last_pet_reward = 0.0
        self._wire()

    # ---- 串接 ----
    def _wire(self) -> None:
        self.notifier.present.connect(self.pet.show_notification)
        self.notifier.toast.connect(self.tray.toast)
        self.scheduler.reminder.connect(self._on_reminder)
        self.scheduler.woke_up.connect(self.calendar.sync)
        self.scheduler.tick.connect(self._on_tick)
        self.calendar.events_changed.connect(self._on_events)
        self.calendar.auth_state_changed.connect(self._on_auth)
        self.pomodoro.phase_finished.connect(self._on_pomodoro_finished)
        self.health.remind.connect(self._on_health)
        self.state.level_up.connect(self._on_level_up)
        self.config.changed.connect(self._on_config)

        self.pet.settings_requested.connect(self.open_settings)
        self.pet.sync_requested.connect(self.calendar.sync)
        self.pet.pomodoro_toggle_requested.connect(self.toggle_pomodoro)
        self.pet.upcoming_requested.connect(self._show_upcoming)
        self.pet.hide_requested.connect(lambda: self.config.update(pet_visible=False))
        self.pet.quit_requested.connect(self.quit)
        self.pet.petted.connect(self._on_petted)

        self.tray.settings_requested.connect(self.open_settings)
        self.tray.toggle_pet_requested.connect(
            lambda: self.config.update(pet_visible=not self.config.settings.pet_visible))
        self.tray.sync_requested.connect(self.calendar.sync)
        self.tray.pomodoro_toggle_requested.connect(self.toggle_pomodoro)
        self.tray.quit_requested.connect(self.quit)

    def start(self) -> None:
        self.tray.show()
        if self.config.settings.pet_visible:
            self.pet.show()
        self.calendar.start()
        self.scheduler.start()
        self.health.start()
        log.info("桌寵啟動完成（Lv.%d）", self.state.state.level)

    def quit(self) -> None:
        log.info("使用者結束程式")
        self.calendar.shutdown()
        self.pet.save_position()
        self.state.save()
        self.pet.bubble.hide()
        self.tray.hide()
        self._qapp.quit()

    # ---- 設定器 ----
    def open_settings(self) -> None:
        if self._settings_window is None:
            from .ui.settings_window import SettingsWindow

            self._settings_window = SettingsWindow(self.config, self.state, self.calendar, self.sound, self.pomodoro,
                                                   show_agenda=self.show_agenda)
        self._settings_window.show_and_raise()

    def toggle_pomodoro(self) -> None:
        if self.pomodoro.running:
            self.pomodoro.stop()
            self.pet.say("番茄鐘停止了，休息一下吧～")
        else:
            self.pomodoro.start()
            self.pet.say(f"開始專注 {self.config.settings.pomodoro_focus} 分鐘！我會安靜陪你～")

    def _on_config(self, keys: set) -> None:
        if "pet_visible" in keys:
            if self.config.settings.pet_visible:
                self.pet.show()
                self.pet.say("我回來囉！")
            else:
                self.pet.dismiss_all()
                self.pet.hide()
                self.tray.toast("桌寵躲起來了", "提醒照常運作，從系統匣圖示可以叫牠回來。")
        if "color" in keys:
            self.tray.setIcon(render_icon(self.config.settings.color))

    # ---- 行事曆提醒 ----
    def _countdown_key(self, ev: CalendarEvent) -> str:
        return f"{ev.id}|{ev.start.isoformat()}"

    def _on_reminder(self, r: Reminder) -> None:
        ev = r.event
        now = local_now()
        remaining = r.remaining_seconds(now)
        when = describe_remaining(remaining)
        lines = [f"🕒 {ev.start:%H:%M}–{ev.end:%H:%M}　{when}"]
        if ev.location and not ev.meeting_url:
            lines.append(f"📍 {ev.location}")

        buttons = [("知道了", lambda: self._acknowledge(r))]
        if remaining > 60:
            buttons.append(("晚 5 分鐘", lambda: self.scheduler.snooze(ev, 5)))
        if ev.meeting_url:
            buttons.append(("開啟會議", lambda: QDesktopServices.openUrl(QUrl(ev.meeting_url))))

        self._countdowns[self._countdown_key(ev)] = ev
        self.notifier.submit(Notification(
            kind="event",
            title=f"⏰ {ev.title}",
            text="\n".join(lines),
            buttons=buttons,
            urgency=1 - max(0.0, min(1.0, remaining / 600)),
            expires_at=ev.start + timedelta(minutes=5),
            timeout_s=EVENT_BUBBLE_TIMEOUT,
            toast=True,
        ))

    def _acknowledge(self, r: Reminder) -> None:
        points = 2 if r.first_stage else 1
        self.state.add_affection(points, "準時處理提醒" if r.first_stage else "處理提醒")
        self.pet.say(random.choice(["收到！加油喔～", "好的，記得準時喔！", "交給你囉！"]), 3)

    def _badge(self) -> tuple[str, str, float] | None:
        now = local_now()
        upcoming = [ev for ev in self._countdowns.values() if ev.start > now]
        if upcoming:
            ev = min(upcoming, key=lambda e: e.start)
            remaining = (ev.start - now).total_seconds()
            return _fmt_countdown(remaining), "event", 1 - max(0.0, min(1.0, remaining / 600))
        if self.pomodoro.running:
            return _fmt_countdown(self.pomodoro.remaining_seconds()), "pomodoro", 0.0
        return None

    def _on_events(self, events: list[CalendarEvent]) -> None:
        valid = {self._countdown_key(ev): ev for ev in events}
        self._countdowns = {k: valid[k] for k in self._countdowns if k in valid}

    def _on_auth(self, state: AuthState, message: str) -> None:
        if state == AuthState.SIGNED_OUT and self.calendar.loaded_once is False:
            self.pet.say("還沒連結 Google 日曆喔～\n右鍵 →「開啟設定器」登入吧！", 8)
        elif state == AuthState.NO_CREDENTIALS:
            self.pet.say("找不到 credentials.json，\n請看 README 設定 Google 日曆～", 8)

    def _show_upcoming(self) -> None:
        now = local_now()
        events = [e for e in self.calendar.events if e.end > now][:3]
        if self.calendar.auth_state == AuthState.NO_CREDENTIALS and not events:
            text = "還沒連結 Google 日曆，右鍵開啟設定器看看吧！"
        elif not events:
            text = "接下來 30 天都沒有行程喔！"
        else:
            parts = []
            for e in events:
                when = f"{e.start:%m/%d} 全天" if e.all_day else f"{e.start:%m/%d %H:%M}"
                parts.append(f"・{when}　{e.title}")
            text = "\n".join(parts)
        self.pet.say(text, 8, title="接下來的行程")

    # ---- 每 15 秒 ----
    def _on_tick(self, now: datetime) -> None:
        self._countdowns = {k: ev for k, ev in self._countdowns.items()
                            if ev.start > now - timedelta(seconds=30)}
        s = self.config.settings
        st = self.state.state
        today = now.date().isoformat()
        route = None

        def can_show() -> bool:
            nonlocal route
            if route is None:
                route = self.notifier.current_route()
            return route == Route.SHOW and self.pet.isVisible()

        if 6 <= now.hour < 10 and st.last_greet_date != today and can_show():
            self.state.set_date_flag("last_greet_date", today)
            self.pet.greet()
            self.pet.say("早安！今天也一起加油吧～", 4)

        # 定時列出今日行程：時間到就送出（不打擾規則交給通知中心處理）
        due = daily_brief.due_agenda_times(now, s.agenda_times, st.agenda_fired)
        for hhmm in due:
            self.state.mark_agenda_fired(hhmm, today)
        if due:
            log.info("定時今日行程：%s", ", ".join(due))
            self.show_agenda(now, label=due[-1])
            self.state.set_date_flag("last_brief_date", today)  # 已經列過今天行程，晨報就不重複

        if (daily_brief.should_show(now, st.last_brief_date, s.daily_brief)
                and self.calendar.loaded_once and can_show()):
            self.state.set_date_flag("last_brief_date", today)
            self.notifier.submit(Notification(
                kind="brief", title="☀️ 今日行程", text=daily_brief.compose(self.calendar.events, now),
                sound=False, timeout_s=20, buttons=[("好的！", lambda: None)],
            ))

        if now.hour == 12 and now.minute < 30 and st.last_lunch_date != today and can_show():
            self.state.set_date_flag("last_lunch_date", today)
            self.notifier.submit(Notification(
                kind="health", title="🍱 午餐時間", text="午餐時間到囉～記得好好吃飯！", sound=False, timeout_s=15,
            ))

    def show_agenda(self, now: datetime | None = None, label: str = "") -> None:
        """列出今天所有行程（定時通知與設定器的預覽按鈕共用）。"""
        now = now or local_now()
        if self.calendar.auth_state == AuthState.NO_CREDENTIALS and not self.calendar.events:
            text = "還沒連結 Google 日曆，到設定器的「行事曆」分頁登入後，我就能幫你列出今天的行程！"
        else:
            text = daily_brief.compose_agenda(self.calendar.events, now)
        title = f"📋 今日行程（{label}）" if label else "📋 今日行程"
        self.notifier.submit(Notification(
            kind="agenda", title=title, text=text, timeout_s=60, buttons=[("好的！", lambda: None)],
            expires_at=now + timedelta(minutes=daily_brief.AGENDA_GRACE_MINUTES),
        ))

    # ---- 番茄鐘 / 健康 / 好感度 ----
    def _on_pomodoro_finished(self, done: Phase, nxt: Phase) -> None:
        s = self.config.settings
        if done == Phase.FOCUS:
            self.state.add_affection(2, "完成番茄鐘")
            self.pet.celebrate()
            minutes = s.pomodoro_long_break if nxt == Phase.LONG_BREAK else s.pomodoro_short_break
            title, text = "🍅 專注完成！", f"辛苦了！休息 {minutes} 分鐘吧～"
        else:
            title, text = "🍅 休息結束", f"繼續專注 {s.pomodoro_focus} 分鐘，加油！"
        self.notifier.submit(Notification(
            kind="pomodoro", title=title, text=text, timeout_s=30,
            buttons=[("好！", lambda: None), ("停止番茄鐘", self.pomodoro.stop)],
            expires_at=local_now() + timedelta(minutes=10),
        ))

    def _on_health(self, kind: str) -> None:
        title, text = HEALTH_MESSAGES[kind]
        icon = "💧" if kind == "water" else "🙆"
        self.notifier.submit(Notification(
            kind="health", title=f"{icon} {title}", text=text, timeout_s=30,
            buttons=[("好的！", lambda: self.state.add_affection(1, f"健康提醒：{kind}"))],
            expires_at=local_now() + timedelta(minutes=30),
        ))

    def _on_petted(self) -> None:
        now = time.monotonic()
        if now - self._last_pet_reward >= PET_REWARD_COOLDOWN:
            self._last_pet_reward = now
            self.state.add_affection(1, "摸摸頭")
        if random.random() < 0.4:
            self.pet.say(random.choice(PET_LINES), 2)

    def _on_level_up(self, level: int, unlocks: list) -> None:
        self.pet.celebrate()
        text = f"解鎖了：{'、'.join(unlocks)}\n到設定器的「桌寵」分頁換上看看吧！" if unlocks else "謝謝你一直陪著我！"
        self.notifier.submit(Notification(kind="level", title=f"🎉 升級到 Lv.{level}！", text=text, timeout_s=15))
