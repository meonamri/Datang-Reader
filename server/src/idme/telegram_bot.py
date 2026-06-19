"""
Telegram bot for IDME per-student absence-reason collection.

Before each session's cutoff the bot DMs every linked class teacher their current
absentee list and lets them tap a reason per student. The chosen reason is stored
in `absence_reasons` (via AbsenceReasonStore); the existing cutoff submission then
picks it up — students left untouched keep the default reason (MALAS KE SEKOLAH).

Design: a minimal requests-based Bot API client using long-polling (getUpdates) in
a daemon thread. This matches the module's existing threading.Timer/daemon-thread
style (scheduler.py), needs no public webhook URL (the container is typically
behind NAT/Tailscale), and avoids an asyncio dependency.

This module is OFF unless IDME_TELEGRAM_ENABLED=true and a bot token is set.
"""

import json
import logging
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from .moeis_codes import (
    COMMON_SEBAB, MOEIS_CATEGORIES, COMPLETE_MOEIS_SEBAB, SEBAB_DESCRIPTIONS,
)

# Telegram caps callback_data at 64 bytes, so we never put names/dates in it —
# only a short opaque entry id plus codes. The entry id resolves to the full
# student record via the bot's in-memory registry.
_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_POLL_TIMEOUT = 30          # long-poll seconds passed to getUpdates
_HTTP_TIMEOUT = _POLL_TIMEOUT + 10
_MAX_BTN_LABEL = 40         # truncate long Malay reason labels on buttons


class TelegramClient:
    """Thin requests wrapper over the Telegram Bot API methods this bot needs."""

    def __init__(self, token: str):
        self.token = token
        self.logger = logging.getLogger(__name__)
        self._session = requests.Session()

    def _call(self, method: str, *, timeout: int = _HTTP_TIMEOUT, **params) -> Optional[dict]:
        """POST a Bot API method, returning the 'result' payload or None on error."""
        url = _API_BASE.format(token=self.token, method=method)
        try:
            resp = self._session.post(url, json=params, timeout=timeout)
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            self.logger.warning(f"Telegram {method} call failed: {e}")
            return None
        if not data.get('ok'):
            self.logger.warning(f"Telegram {method} returned error: {data.get('description')}")
            return None
        return data.get('result')

    def get_me(self) -> Optional[dict]:
        return self._call('getMe', timeout=_HTTP_TIMEOUT)

    def get_updates(self, offset: Optional[int]) -> List[dict]:
        result = self._call(
            'getUpdates', offset=offset, timeout=_POLL_TIMEOUT,
            allowed_updates=['message', 'callback_query'],
        )
        return result or []

    def send_message(self, chat_id, text, reply_markup=None) -> Optional[dict]:
        params = {'chat_id': chat_id, 'text': text}
        if reply_markup is not None:
            params['reply_markup'] = reply_markup
        return self._call('sendMessage', **params)

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None) -> Optional[dict]:
        params = {'chat_id': chat_id, 'message_id': message_id, 'text': text}
        if reply_markup is not None:
            params['reply_markup'] = reply_markup
        return self._call('editMessageText', **params)

    def answer_callback_query(self, callback_query_id, text=None) -> Optional[dict]:
        params = {'callback_query_id': callback_query_id}
        if text:
            params['text'] = text
        return self._call('answerCallbackQuery', **params)


def _truncate(label: str) -> str:
    return label if len(label) <= _MAX_BTN_LABEL else label[:_MAX_BTN_LABEL - 1] + '…'


class IDMETelegramBot:
    """Long-polling Telegram bot: teacher linking, reason prompts, reason capture."""

    def __init__(self, token, teacher_manager, absence_detector, reason_store):
        self.client = TelegramClient(token)
        self.teacher_manager = teacher_manager
        self.absence_detector = absence_detector
        self.reason_store = reason_store
        self.logger = logging.getLogger(__name__)

        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._offset: Optional[int] = None
        self.bot_username: Optional[str] = None

        # entry_id -> student record being reasoned about. Short-lived (one prompt
        # round); a stale tap after a restart is answered with "expired".
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> bool:
        """Verify the token (getMe) and start the poll loop. Returns success."""
        me = self.client.get_me()
        if not me:
            self.logger.error("Telegram bot disabled: getMe failed (bad token or no network)")
            return False
        self.bot_username = me.get('username')
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self.logger.info(f"Telegram bot started as @{self.bot_username}")
        return True

    def stop(self):
        self.running = False

    def _poll_loop(self):
        while self.running:
            try:
                updates = self.client.get_updates(self._offset)
                for update in updates:
                    self._offset = update['update_id'] + 1
                    try:
                        self._dispatch(update)
                    except Exception as e:
                        self.logger.error(f"Error handling Telegram update: {e}")
            except Exception as e:
                # Never let the loop die — back off briefly and retry.
                self.logger.warning(f"Telegram poll error: {e}")
                time.sleep(3)

    # ---- linking deep-link ----------------------------------------------

    def build_link(self, teacher_id: int) -> Optional[str]:
        """Mint a one-time link token for a teacher and return the t.me deep link
        the teacher taps to bind their chat. None if the bot username is unknown."""
        if not self.bot_username:
            return None
        token = secrets.token_urlsafe(8)
        self.teacher_manager.set_telegram_link_token(teacher_id, token)
        return f"https://t.me/{self.bot_username}?start={token}"

    # ---- update dispatch -------------------------------------------------

    def _dispatch(self, update: dict):
        if 'message' in update:
            self._handle_message(update['message'])
        elif 'callback_query' in update:
            self._handle_callback(update['callback_query'])

    def _handle_message(self, message: dict):
        text = (message.get('text') or '').strip()
        chat_id = message['chat']['id']

        if text.startswith('/start'):
            parts = text.split(maxsplit=1)
            token = parts[1].strip() if len(parts) > 1 else ''
            if not token:
                self.client.send_message(
                    chat_id,
                    "Selamat datang ke pembantu kehadiran IDME.\n\n"
                    "Untuk menghubungkan akaun anda, sila gunakan pautan "
                    "\"Link Telegram\" di halaman tetapan IDME sekolah.",
                )
                return
            teacher = self.teacher_manager.link_telegram_chat(token, chat_id)
            if teacher:
                self.client.send_message(
                    chat_id,
                    f"✅ Berjaya dihubungkan sebagai {teacher['name']} "
                    f"({teacher['class_name']}).\n\n"
                    "Anda akan menerima senarai pelajar tidak hadir sebelum waktu "
                    "penghantaran untuk merekod sebab.",
                )
            else:
                self.client.send_message(
                    chat_id,
                    "⚠️ Pautan ini tidak sah atau telah digunakan. Sila jana "
                    "pautan baharu dari halaman tetapan IDME.",
                )
            return

        # Any other message: gentle hint.
        self.client.send_message(
            chat_id,
            "Sila gunakan butang pada mesej senarai pelajar untuk merekod sebab "
            "tidak hadir.",
        )

    def _handle_callback(self, cq: dict):
        data = cq.get('data') or ''
        cq_id = cq['id']
        message = cq.get('message') or {}
        chat_id = message.get('chat', {}).get('id')
        message_id = message.get('message_id')

        parts = data.split('|')
        action = parts[0] if parts else ''

        entry_id = parts[1] if len(parts) > 1 else ''
        with self._lock:
            entry = self._entries.get(entry_id)

        if entry is None:
            self.client.answer_callback_query(
                cq_id, "Sesi tamat tempoh — sila tunggu peringatan seterusnya.")
            return

        if action == 'p' or action == 's':
            # Quick-pick or category-pick: parts = [action, entry_id, sebab_id]
            sebab_id = parts[2] if len(parts) > 2 else ''
            self._record_choice(entry, sebab_id, chat_id, message_id, cq_id)
        elif action == 'm':
            # Open the full category browser.
            self.client.edit_message_text(
                chat_id, message_id, self._prompt_text(entry),
                reply_markup=self._category_keyboard(entry_id),
            )
            self.client.answer_callback_query(cq_id)
        elif action == 'c':
            # Show reasons within a chosen category. parts = [c, entry_id, cat]
            cat = parts[2] if len(parts) > 2 else ''
            self.client.edit_message_text(
                chat_id, message_id, self._prompt_text(entry),
                reply_markup=self._reasons_keyboard(entry_id, cat),
            )
            self.client.answer_callback_query(cq_id)
        elif action == 'b':
            # Back to the quick-pick keyboard.
            self.client.edit_message_text(
                chat_id, message_id, self._prompt_text(entry),
                reply_markup=self._quickpick_keyboard(entry_id),
            )
            self.client.answer_callback_query(cq_id)
        else:
            self.client.answer_callback_query(cq_id)

    def _record_choice(self, entry, sebab_id, chat_id, message_id, cq_id):
        keterangan = SEBAB_DESCRIPTIONS.get(sebab_id)
        if not keterangan:
            self.client.answer_callback_query(cq_id, "Sebab tidak sah.")
            return
        try:
            self.reason_store.upsert_reason(
                class_name=entry['class_name'],
                student_name=entry['student_name'],
                sebab_id=sebab_id,
                scan_date=entry['scan_date'],
                idpelajar=entry.get('idpelajar'),
                set_by=entry.get('teacher_id'),
                source='telegram',
            )
        except Exception as e:
            self.logger.error(f"Failed to store reason from Telegram: {e}")
            self.client.answer_callback_query(cq_id, "Gagal menyimpan. Cuba lagi.")
            return

        self.client.edit_message_text(
            chat_id, message_id,
            f"✅ {entry['student_name']} ({entry['class_name']})\n"
            f"Sebab: {keterangan}",
        )
        self.client.answer_callback_query(cq_id, "Disimpan ✅")

    # ---- prompting -------------------------------------------------------

    def prompt_session(self, session: dict, scan_date: Optional[str] = None) -> int:
        """DM every linked teacher in this session's forms their current absentee
        list. Returns the number of prompt messages sent."""
        from .idme_config import IDMEConfig
        if scan_date is None:
            scan_date = date.today().isoformat()
        forms = set(session['forms'])
        sent = 0

        for teacher in self.teacher_manager.get_all_teachers():
            if IDMEConfig.form_of(teacher['class_name']) not in forms:
                continue
            chat_id = teacher.get('telegram_chat_id')
            if not chat_id:
                self.logger.info(
                    f"Skipping prompt for {teacher['name']} ({teacher['class_name']}): "
                    "no linked Telegram chat"
                )
                continue
            try:
                sent += self._prompt_teacher(teacher, chat_id, scan_date)
            except Exception as e:
                self.logger.error(f"Failed to prompt {teacher['name']}: {e}")

        self.logger.info(
            f"Telegram prompt for {session['name']} session ({scan_date}): "
            f"{sent} messages sent"
        )
        return sent

    def _prompt_teacher(self, teacher, chat_id, scan_date) -> int:
        class_name = teacher['class_name']
        absences = self.absence_detector.detect_absences(class_name, scan_date)
        if not absences:
            self.client.send_message(
                chat_id,
                f"✅ {class_name} ({scan_date}): semua pelajar hadir setakat ini. "
                "Tiada sebab perlu direkod.",
            )
            return 1

        self.client.send_message(
            chat_id,
            f"📋 {class_name} — {len(absences)} pelajar belum hadir ({scan_date}).\n"
            "Pilih sebab bagi setiap pelajar di bawah. Yang tidak dipilih akan "
            "direkod sebagai PONTENG (MALAS KE SEKOLAH).",
        )
        for s in absences:
            entry_id = self._register_entry(teacher, s, scan_date)
            self.client.send_message(
                chat_id, self._prompt_text(self._entries[entry_id]),
                reply_markup=self._quickpick_keyboard(entry_id),
            )
        return len(absences)

    def _register_entry(self, teacher, absence, scan_date) -> str:
        entry_id = secrets.token_urlsafe(5)
        with self._lock:
            self._entries[entry_id] = {
                'teacher_id': teacher['id'],
                'class_name': teacher['class_name'],
                'student_name': absence['student_name'],
                'idpelajar': absence.get('idpelajar'),
                'scan_date': scan_date,
            }
        return entry_id

    # ---- keyboards -------------------------------------------------------

    @staticmethod
    def _prompt_text(entry) -> str:
        return (f"🔴 {entry['student_name']} ({entry['class_name']})\n"
                "Pilih sebab tidak hadir:")

    def _quickpick_keyboard(self, entry_id) -> str:
        rows = [
            [{'text': _truncate(SEBAB_DESCRIPTIONS.get(sid, sid)),
              'callback_data': f"p|{entry_id}|{sid}"}]
            for sid in COMMON_SEBAB
        ]
        rows.append([{'text': '➕ Sebab lain…', 'callback_data': f"m|{entry_id}"}])
        return json.dumps({'inline_keyboard': rows})

    def _category_keyboard(self, entry_id) -> str:
        rows = [
            [{'text': f"{label}", 'callback_data': f"c|{entry_id}|{cat}"}]
            for cat, label in MOEIS_CATEGORIES.items()
        ]
        rows.append([{'text': '⬅️ Kembali', 'callback_data': f"b|{entry_id}"}])
        return json.dumps({'inline_keyboard': rows})

    def _reasons_keyboard(self, entry_id, cat) -> str:
        rows = [
            [{'text': _truncate(info['keterangan']),
              'callback_data': f"s|{entry_id}|{sid}"}]
            for sid, info in COMPLETE_MOEIS_SEBAB.items()
            if info['category'] == cat
        ]
        rows.append([{'text': '⬅️ Kategori', 'callback_data': f"m|{entry_id}"}])
        return json.dumps({'inline_keyboard': rows})


class _PromptSession:
    """One session's prompt timer (mirrors scheduler._Session)."""

    def __init__(self, session: dict):
        self.session = session
        self.name = session['name']
        self.hour, self.minute = map(int, session['prompt_time'].split(':'))
        self.timer: Optional[threading.Timer] = None

    def next_target(self, now: datetime) -> datetime:
        target = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return target


class TelegramPromptScheduler:
    """Fires bot.prompt_session at each session's prompt_time, daily.

    Mirrors IDMEScheduler: one daemon Timer per session, rescheduled after it
    fires. Only sessions with a prompt_time are armed."""

    def __init__(self, bot: IDMETelegramBot, sessions: List[dict]):
        self.bot = bot
        self.sessions = [_PromptSession(s) for s in sessions if s.get('prompt_time')]
        self.running = False
        self.logger = logging.getLogger(__name__)

    def start(self):
        self.running = True
        for ps in self.sessions:
            self._schedule_next(ps)
        if self.sessions:
            times = ', '.join(f"{p.name} {p.hour:02d}:{p.minute:02d}" for p in self.sessions)
            self.logger.info(f"Telegram prompt scheduler started. Daily prompts at — {times}")
        else:
            self.logger.info("Telegram prompt scheduler: no sessions have a prompt time")

    def stop(self):
        self.running = False
        for ps in self.sessions:
            if ps.timer:
                ps.timer.cancel()
                ps.timer = None

    def _schedule_next(self, ps: _PromptSession):
        now = datetime.now()
        target = ps.next_target(now)
        seconds_until = (target - now).total_seconds()
        ps.timer = threading.Timer(seconds_until, self._execute, args=(ps,))
        ps.timer.daemon = True
        ps.timer.start()
        self.logger.info(
            f"Next Telegram prompt ({ps.name}): {target.strftime('%Y-%m-%d %H:%M')} "
            f"({seconds_until / 3600:.1f}h from now)"
        )

    def _execute(self, ps: _PromptSession):
        try:
            self.bot.prompt_session(ps.session)
        except Exception as e:
            self.logger.error(f"Telegram prompt ({ps.name}) failed: {e}")
        if self.running:
            self._schedule_next(ps)
