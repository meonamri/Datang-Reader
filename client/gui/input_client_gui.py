#!/usr/bin/env python3
"""
GUI Input Client for Datang Reader (Docker Deployment)

Apple-inspired kiosk UI for the SMKSAT RFID reader.
Single-stage layout: top strip · centered hero "puck" · bottom status strip.
Tuned for OrangePi Zero 3 (Mali-G31, ARM Cortex-A53) — capped animation FPS,
cached pens/brushes, no GPU blur effects, single timer per animated widget.
"""

import sys
import time
import math
import logging
import signal
import os
import json
import subprocess
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QSystemTrayIcon, QMenu, QLineEdit, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QRectF, QPointF
from PyQt5.QtGui import (
    QFont, QFontMetrics, QColor, QIcon, QPainter, QPixmap, QPen, QBrush,
    QPainterPath, QRadialGradient,
)

from config import Config

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not found.", file=sys.stderr)
    print("Install it with: pip install requests", file=sys.stderr)
    sys.exit(1)


# Configuration
DEFAULT_CONTAINER_URL = Config.CONTAINER_URL
MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 5
STATS_FILE = os.path.expanduser("~/.datang_stats.json")

# Apple-inspired midnight palette (translated from Kiosk.html design tokens)
COLORS = {
    # Base — deep midnight grading toward warm black
    'bg_0':        '#07090d',
    'bg_1':        '#0c1018',
    'bg_2':        '#11161f',

    # Text
    'fg_0':        '#ffffff',
    'fg_1':        'rgba(255, 255, 255, 0.78)',
    'fg_2':        'rgba(255, 255, 255, 0.52)',
    'fg_3':        'rgba(255, 255, 255, 0.32)',
    'fg_4':        'rgba(255, 255, 255, 0.16)',

    # Hairlines
    'line_1':      'rgba(255, 255, 255, 0.08)',
    'line_2':      'rgba(255, 255, 255, 0.14)',

    # State accents (iOS-inspired)
    'gold':        '#f5cd00',
    'green':       '#34c759',
    'red':         '#ff453a',
    'amber':       '#ff9f0a',
}

STATE_COLOR = {
    'idle':       QColor('#f5cd00'),
    'processing': QColor('#ff9f0a'),
    'success':    QColor('#34c759'),
    'error':      QColor('#ff453a'),
}


def malay_greeting(now: datetime) -> str:
    """Time-of-day Malay greeting for the success state."""
    h = now.hour
    if h < 12:
        return "Selamat Pagi"
    if h < 15:
        return "Selamat Tengah Hari"
    if h < 19:
        return "Selamat Petang"
    return "Selamat Malam"


class InputClient:
    """RFID input client that forwards card scans to Docker container"""

    def __init__(self, container_url: str):
        self.container_url = container_url.rstrip('/')
        self.card_endpoint = f"{self.container_url}/card"
        self.health_endpoint = f"{self.container_url}/health"
        self.status_endpoint = f"{self.container_url}/status"
        self.logger = logging.getLogger('InputClient')

    def check_container_health(self) -> bool:
        try:
            response = requests.get(self.health_endpoint, timeout=REQUEST_TIMEOUT)
            return response.status_code == 200
        except Exception:
            return False

    def get_container_status(self) -> dict:
        try:
            response = requests.get(self.status_endpoint, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return {}

    def send_card_scan(self, card_id: str) -> tuple:
        try:
            response = requests.post(
                self.card_endpoint,
                json={"card_id": card_id},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    return (
                        True,
                        result.get('message', 'Recorded'),
                        result.get('online', False),
                        result.get('data', {}) or {},
                    )
                return False, result.get('message', 'Unknown error'), False, {}
            return False, f"HTTP {response.status_code}", False, {}
        except requests.exceptions.Timeout:
            return False, "Request timeout - container not responding", False, {}
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to container", False, {}
        except Exception as e:
            return False, f"Error: {str(e)}", False, {}

    @staticmethod
    def validate_card_id(card_id: str) -> tuple:
        card_id = card_id.strip()
        if not card_id:
            return False, "Empty card ID"
        if not card_id.isdigit():
            return False, "Card ID must be all digits"
        if len(card_id) != 10:
            return False, f"Card ID must be 10 digits (got {len(card_id)})"
        return True, ""


class HealthCheckThread(QThread):
    """Background thread for periodic health checks"""
    health_status = pyqtSignal(bool, dict)

    def __init__(self, client: InputClient):
        super().__init__()
        self.client = client
        self.running = True

    def run(self):
        while self.running:
            is_healthy = self.client.check_container_health()
            status_data = self.client.get_container_status() if is_healthy else {}
            if status_data is None:
                status_data = {}
            self.health_status.emit(is_healthy, status_data)
            time.sleep(5)

    def stop(self):
        self.running = False


class RfidPuck(QWidget):
    """The kiosk hero — three concentric rings around a glass core with a state glyph.

    All animation runs on a single QTimer. Idle: gentle 4.4s breathe at ~20 fps.
    Processing: rotating arc at ~30 fps. Success/Error: static (timer paused).
    """

    SPIN_FPS = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = 'idle'
        self._phase = 0.0
        self._spin_deg = 0.0
        self._t0 = time.monotonic()

        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        # Cached pens (Qt construction is not free on ARM)
        self._pen_hair = QPen(QColor(255, 255, 255, 36), 1.2)
        self._pen_hair2 = QPen(QColor(255, 255, 255, 20), 1.2)
        self._pen_hair3 = QPen(QColor(255, 255, 255, 12), 1.2)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._restart_timer()

    def set_state(self, state: str):
        if state == self._state:
            return
        self._state = state
        self._spin_deg = 0.0
        self._restart_timer()
        self.update()

    def sizeHint(self):
        return self.minimumSize()

    def _restart_timer(self):
        if self._state == 'idle':
            if Config.ENABLE_PULSE_ANIMATION:
                self._timer.start(1000 // Config.PULSE_ANIMATION_FPS)
            else:
                self._timer.stop()
                self.update()
        elif self._state == 'processing':
            self._timer.start(1000 // self.SPIN_FPS)
        else:
            self._timer.stop()
            self.update()

    def _tick(self):
        now = time.monotonic()
        if self._state == 'idle':
            self._phase = (math.sin((now - self._t0) * (2 * math.pi) / 4.4) + 1.0) * 0.5
        elif self._state == 'processing':
            self._spin_deg = (self._spin_deg + 360.0 / (self.SPIN_FPS * 1.4)) % 360.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2.0, h / 2.0

        scale = 1.0 + (0.035 * self._phase if self._state == 'idle' else 0.0)
        r_outer = (side / 2.0) * scale * 0.98
        r_mid = r_outer * 0.85
        r_inner = r_outer * 0.69
        r_core = r_outer * 0.60

        accent = STATE_COLOR[self._state]

        # ring 1 (outermost)
        if self._state in ('success', 'error'):
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 90), 1.4)
        elif self._state == 'idle':
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), int(15 + 55 * self._phase)), 1.4)
        else:
            pen = self._pen_hair
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r_outer, r_outer)

        # ring 2 (mid) — spinner during processing
        if self._state == 'processing':
            p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 60), 1.4))
            p.drawEllipse(QPointF(cx, cy), r_mid, r_mid)
            arc_pen = QPen(QColor(accent), 2.4)
            arc_pen.setCapStyle(Qt.RoundCap)
            p.setPen(arc_pen)
            rect = QRectF(cx - r_mid, cy - r_mid, r_mid * 2, r_mid * 2)
            start_angle = int(-self._spin_deg * 16)
            span = int(95 * 16)
            p.drawArc(rect, start_angle, span)
        else:
            if self._state in ('success', 'error'):
                p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 56), 1.2))
            elif self._state == 'idle':
                p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), int(10 + 36 * self._phase)), 1.2))
            else:
                p.setPen(self._pen_hair2)
            p.drawEllipse(QPointF(cx, cy), r_mid, r_mid)

        # ring 3 (inner faint)
        p.setPen(self._pen_hair3)
        p.drawEllipse(QPointF(cx, cy), r_inner, r_inner)

        # glass core
        grad = QRadialGradient(cx - r_core * 0.25, cy - r_core * 0.30, r_core * 1.2)
        if self._state == 'success':
            grad.setColorAt(0.0, QColor(52, 199, 89, 64))
            grad.setColorAt(1.0, QColor(52, 199, 89, 6))
            border = QColor(52, 199, 89, 90)
        elif self._state == 'error':
            grad.setColorAt(0.0, QColor(255, 69, 58, 64))
            grad.setColorAt(1.0, QColor(255, 69, 58, 6))
            border = QColor(255, 69, 58, 90)
        else:
            grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), int(10 + 32 * self._phase)))
            grad.setColorAt(1.0, QColor(255, 255, 255, 4))
            border = QColor(accent.red(), accent.green(), accent.blue(), int(22 + 44 * self._phase))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(border, 1.2))
        p.drawEllipse(QPointF(cx, cy), r_core, r_core)

        # glyph
        glyph_r = r_core * 0.46
        gpen = QPen(accent if self._state != 'idle' else QColor('#ffffff'))
        gpen.setWidthF(max(1.6, glyph_r * 0.10))
        gpen.setCapStyle(Qt.RoundCap)
        gpen.setJoinStyle(Qt.RoundJoin)
        p.setPen(gpen)
        p.setBrush(Qt.NoBrush)

        if self._state == 'success':
            path = QPainterPath()
            path.moveTo(cx - glyph_r * 0.75, cy + glyph_r * 0.05)
            path.lineTo(cx - glyph_r * 0.10, cy + glyph_r * 0.65)
            path.lineTo(cx + glyph_r * 0.85, cy - glyph_r * 0.60)
            p.drawPath(path)
        elif self._state == 'error':
            p.drawLine(QPointF(cx - glyph_r * 0.7, cy - glyph_r * 0.7),
                       QPointF(cx + glyph_r * 0.7, cy + glyph_r * 0.7))
            p.drawLine(QPointF(cx + glyph_r * 0.7, cy - glyph_r * 0.7),
                       QPointF(cx - glyph_r * 0.7, cy + glyph_r * 0.7))
        elif self._state == 'processing':
            p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 70),
                          gpen.widthF()))
            p.drawEllipse(QPointF(cx, cy), glyph_r * 0.78, glyph_r * 0.78)
            p.setPen(gpen)
            rect = QRectF(cx - glyph_r * 0.78, cy - glyph_r * 0.78,
                          glyph_r * 1.56, glyph_r * 1.56)
            p.drawArc(rect, int(-self._spin_deg * 16), int(95 * 16))
        else:
            # idle: stylised RFID waves — centre dot + three arcs
            p.setBrush(QBrush(accent))
            p.setPen(Qt.NoPen)
            dot_r = glyph_r * 0.16
            p.drawEllipse(QPointF(cx - glyph_r * 0.30, cy), dot_r, dot_r)

            wave_pen = QPen()
            wave_pen.setWidthF(gpen.widthF())
            wave_pen.setCapStyle(Qt.RoundCap)
            alpha = int(140 + 90 * self._phase)
            wave_pen.setColor(QColor(accent.red(), accent.green(), accent.blue(), alpha))
            p.setPen(wave_pen)
            p.setBrush(Qt.NoBrush)
            for r_mult in (0.55, 0.85, 1.15):
                r = glyph_r * r_mult
                rect = QRectF(cx - glyph_r * 0.30 - r, cy - r, r * 2, r * 2)
                p.drawArc(rect, int(-45 * 16), int(90 * 16))

        p.end()


class AttendanceApp(QMainWindow):
    """Datang Reader kiosk — Apple-inspired single-stage layout."""

    def __init__(self, container_url: str):
        super().__init__()
        self.client = InputClient(container_url)
        self.container_url = container_url

        # Statistics
        self.total_scans = 0
        self.successful_scans = 0
        self.failed_scans = 0
        self.last_scan_time = None
        self.last_scan_ok = None
        self.container_online = False
        self.container_queue_size = 0

        self._load_stats()

        self.consecutive_unhealthy = 0
        self.health_thread = None

        self.init_ui()
        self.start_background_tasks()

    def init_ui(self):
        self.setWindowTitle("SMK Sultan Ahmad Tajuddin — Datang Reader")
        self.setGeometry(100, 100, Config.WINDOW_WIDTH, Config.WINDOW_HEIGHT)
        if Config.FULLSCREEN:
            self.showFullScreen()

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {COLORS['bg_0']};
                color: {COLORS['fg_0']};
                font-family: "Helvetica Neue", "Inter",
                             "Noto Sans", "DejaVu Sans", "Arial", sans-serif;
            }}
            QLineEdit#cardInput {{
                background: rgba(255,255,255,0.04);
                color: rgba(255,255,255,0.40);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 10px;
            }}
            QFrame#hair {{
                background: rgba(255,255,255,0.08);
                max-height: 1px;
                min-height: 1px;
                border: none;
            }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_topbar())
        outer.addWidget(self._hairline())
        outer.addWidget(self._build_stage(), stretch=1)
        outer.addWidget(self._hairline())
        outer.addWidget(self._build_statusbar())


        if QSystemTrayIcon.isSystemTrayAvailable():
            self.create_system_tray()

        self.set_hero_state('idle')

    def _hairline(self) -> QFrame:
        line = QFrame()
        line.setObjectName("hair")
        line.setFrameShape(QFrame.NoFrame)
        line.setFixedHeight(1)
        return line

    # -------------------------------------------------------------- top strip
    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background: transparent;")
        bar.setFixedHeight(72)

        grid = QGridLayout(bar)
        grid.setContentsMargins(40, 14, 40, 14)
        grid.setHorizontalSpacing(20)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)

        # brand (left)
        brand = QWidget()
        brand.setStyleSheet("background: transparent;")
        brand_l = QHBoxLayout(brand)
        brand_l.setContentsMargins(0, 0, 0, 0)
        brand_l.setSpacing(14)

        crest = QLabel()
        crest.setFixedSize(38, 38)
        crest.setStyleSheet("background: transparent;")
        crest.setAlignment(Qt.AlignCenter)
        logo_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "assets", "logo", "Logo SMKSAT trans.png",
        )
        pm = QPixmap(logo_path)
        if not pm.isNull():
            crest.setPixmap(pm.scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            crest.setText("SAT")
            crest.setStyleSheet(f"color: {COLORS['gold']}; font-weight: 600; font-size: 11px;")
        brand_l.addWidget(crest)

        brand_text = QWidget()
        brand_text.setStyleSheet("background: transparent;")
        bt_l = QVBoxLayout(brand_text)
        bt_l.setContentsMargins(0, 0, 0, 0)
        bt_l.setSpacing(4)

        name = QLabel("SMK SULTAN AHMAD TAJUDDIN")
        name.setStyleSheet(
            f"color: {COLORS['fg_0']}; font-size: 13px; font-weight: 600;"
            f" letter-spacing: 1.2px; background: transparent;"
        )
        sub = QLabel("ATTENDANCE · DATANG READER")
        sub.setStyleSheet(
            f"color: {COLORS['fg_2']}; font-size: 10px; font-weight: 400;"
            f" letter-spacing: 1.6px; background: transparent;"
        )
        bt_l.addWidget(name)
        bt_l.addWidget(sub)

        brand_l.addWidget(brand_text)
        brand_l.addStretch()
        grid.addWidget(brand, 0, 0, alignment=Qt.AlignVCenter | Qt.AlignLeft)

        # motto (center)
        self.motto_label = QLabel("HIDUP BERJASA")
        self.motto_label.setAlignment(Qt.AlignCenter)
        self.motto_label.setStyleSheet(
            f"color: {COLORS['gold']}; font-size: 12px; font-weight: 700;"
            f" letter-spacing: 4px; background: transparent;"
        )
        grid.addWidget(self.motto_label, 0, 1, alignment=Qt.AlignVCenter | Qt.AlignHCenter)

        # meta (right): clock + date + signal
        meta = QWidget()
        meta.setStyleSheet("background: transparent;")
        meta_l = QHBoxLayout(meta)
        meta_l.setContentsMargins(0, 0, 0, 0)
        meta_l.setSpacing(18)
        meta_l.addStretch()

        date_box = QWidget()
        date_box.setStyleSheet("background: transparent;")
        db_l = QVBoxLayout(date_box)
        db_l.setContentsMargins(0, 0, 0, 0)
        db_l.setSpacing(4)
        self.time_label = QLabel("--:--:--")
        self.time_label.setAlignment(Qt.AlignRight)
        self.time_label.setStyleSheet(
            f"color: {COLORS['fg_0']}; font-size: 18px; font-weight: 500;"
            f" background: transparent;"
        )
        self.date_label = QLabel("")
        self.date_label.setAlignment(Qt.AlignRight)
        self.date_label.setStyleSheet(
            f"color: {COLORS['fg_2']}; font-size: 10px; font-weight: 500;"
            f" letter-spacing: 2px; background: transparent;"
        )
        db_l.addWidget(self.time_label)
        db_l.addWidget(self.date_label)
        meta_l.addWidget(date_box)

        signal_box = QWidget()
        signal_box.setStyleSheet("background: transparent;")
        sb_l = QHBoxLayout(signal_box)
        sb_l.setContentsMargins(0, 0, 0, 0)
        sb_l.setSpacing(8)
        self.signal_dot = QLabel()
        self.signal_dot.setFixedSize(10, 10)
        self.signal_dot.setStyleSheet(
            f"background: {COLORS['red']}; border-radius: 5px;"
        )
        self.signal_text = QLabel("QUEUED")
        self.signal_text.setStyleSheet(
            f"color: {COLORS['fg_2']}; font-size: 11px; font-weight: 600;"
            f" letter-spacing: 2px; background: transparent;"
        )
        sb_l.addWidget(self.signal_dot)
        sb_l.addWidget(self.signal_text)
        meta_l.addWidget(signal_box)

        grid.addWidget(meta, 0, 2, alignment=Qt.AlignVCenter | Qt.AlignRight)
        self.update_time()
        return bar

    # ---------------------------------------------------------- hero / stage
    def _build_stage(self) -> QWidget:
        stage = QWidget()
        stage.setStyleSheet("background: transparent;")
        v = QVBoxLayout(stage)
        v.setContentsMargins(40, 24, 40, 24)
        v.setSpacing(0)
        v.addStretch(2)

        self.puck = RfidPuck()
        # Keep the puck compressible: on success the taller attendee_box
        # replaces the one-line subline, so the stage needs vertical slack or
        # the bottom overflows on a 720p kiosk panel (fits at idle, not on
        # success). A 240px floor frees ~80px versus the old rigid 320.
        self.puck.setMinimumSize(240, 240)
        self.puck.setMaximumSize(480, 480)
        puck_row = QHBoxLayout()
        puck_row.addStretch()
        puck_row.addWidget(self.puck)
        puck_row.addStretch()
        v.addLayout(puck_row)

        v.addSpacing(40)

        self.headline_label = QLabel("Tap your card")
        self.headline_label.setAlignment(Qt.AlignCenter)
        self.headline_label.setStyleSheet(self._headline_qss(COLORS['fg_0']))
        v.addWidget(self.headline_label)

        v.addSpacing(16)

        self.subline_label = QLabel("Place your RFID card on the reader to check in")
        self.subline_label.setAlignment(Qt.AlignCenter)
        self.subline_label.setWordWrap(True)
        self.subline_label.setStyleSheet(
            f"color: {COLORS['fg_2']}; font-size: 18px; font-weight: 400;"
            f" background: transparent;"
        )
        v.addWidget(self.subline_label)

        # Attendee detail (shown only on success)
        self.attendee_box = QWidget()
        self.attendee_box.setStyleSheet("background: transparent;")
        ab_l = QVBoxLayout(self.attendee_box)
        ab_l.setContentsMargins(0, 14, 0, 0)
        ab_l.setSpacing(10)

        self.name_label = QLabel("")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet(
            f"color: {COLORS['fg_0']}; font-size: 44px; font-weight: 500;"
            f" letter-spacing: -1px; background: transparent;"
        )
        ab_l.addWidget(self.name_label)

        meta_row = QWidget()
        meta_row.setStyleSheet("background: transparent;")
        mr_l = QHBoxLayout(meta_row)
        mr_l.setContentsMargins(0, 0, 0, 0)
        mr_l.setSpacing(14)
        mr_l.addStretch()
        self.section_label = QLabel("")
        self.section_label.setStyleSheet(
            f"color: {COLORS['fg_1']}; font-size: 16px; font-weight: 400;"
            f" background: transparent;"
        )
        sep = QLabel()
        sep.setFixedSize(4, 4)
        sep.setStyleSheet(
            f"background: {COLORS['fg_3']}; border-radius: 2px;"
        )
        self.checkin_label = QLabel("")
        self.checkin_label.setStyleSheet(
            f"color: {COLORS['green']}; font-size: 16px; font-weight: 500;"
            f" background: transparent;"
        )
        mr_l.addWidget(self.section_label)
        mr_l.addWidget(sep, alignment=Qt.AlignVCenter)
        mr_l.addWidget(self.checkin_label)
        mr_l.addStretch()
        ab_l.addWidget(meta_row)

        v.addWidget(self.attendee_box)
        self.attendee_box.setVisible(False)

        v.addStretch(3)
        return stage

    @staticmethod
    def _headline_qss(color: str, px: int = 72) -> str:
        return (
            f"color: {color}; font-size: {px}px; font-weight: 300;"
            f" letter-spacing: -2.5px; background: transparent;"
        )

    def _apply_headline(self, text: str, color: str):
        """Set the hero headline, shrinking the font so it never overflows the
        fixed-width kiosk panel.

        The 72px headline holds variable-length strings: Malay greetings
        ("Selamat Tengah Hari" wants 1321px) and any fallback text. On a 1280px
        panel these exceed the width and clip horizontally. We pick the largest
        size up to 72px that fits the stage's inner width, so headlines scale
        down instead of running off the edges. Width is the only axis touched —
        the line count stays at one, so the vertical budget is unaffected.
        """
        self._headline_text = text
        self._headline_color = color
        self.headline_label.setText(text)
        # Stage content margins are 40px on each side (see _build_stage).
        avail = max(self.width() - 80, 200)
        f = QFont(self.headline_label.font())
        px = 72
        while px > 34:
            f.setPixelSize(px)
            if QFontMetrics(f).horizontalAdvance(text) <= avail:
                break
            px -= 2
        self.headline_label.setStyleSheet(self._headline_qss(color, px))

    def resizeEvent(self, event):
        # Re-fit the headline whenever the panel size changes (e.g. the
        # switch to fullscreen after show, or a resolution change).
        super().resizeEvent(event)
        if getattr(self, "_headline_text", None) is not None:
            self._apply_headline(self._headline_text, self._headline_color)

    # ------------------------------------------------------------- statusbar
    def _build_statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background: transparent;")
        bar.setFixedHeight(64)
        grid = QGridLayout(bar)
        grid.setContentsMargins(40, 10, 40, 10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)

        # stats group (left)
        stats = QWidget()
        stats.setStyleSheet("background: transparent;")
        s_l = QHBoxLayout(stats)
        s_l.setContentsMargins(0, 0, 0, 0)
        s_l.setSpacing(28)
        self.total_value, total_row = self._stat_row("Scans today", COLORS['fg_0'])
        self.success_value, success_row = self._stat_row("Recorded", COLORS['green'])
        self.failed_value, failed_row = self._stat_row("Failed", COLORS['red'])
        s_l.addWidget(total_row)
        s_l.addWidget(success_row)
        s_l.addWidget(failed_row)
        s_l.addStretch()
        grid.addWidget(stats, 0, 0, alignment=Qt.AlignVCenter | Qt.AlignLeft)

        # last scan (center)
        self.last_scan_label = QLabel("Awaiting first scan")
        self.last_scan_label.setAlignment(Qt.AlignCenter)
        self.last_scan_label.setStyleSheet(
            f"color: {COLORS['fg_2']}; font-size: 11px; font-weight: 500;"
            f" letter-spacing: 1.6px; background: transparent;"
        )
        grid.addWidget(self.last_scan_label, 0, 1, alignment=Qt.AlignVCenter | Qt.AlignHCenter)

        # right column: card input (top) + host label (bottom)
        right_col = QWidget()
        right_col.setStyleSheet("background: transparent;")
        rc_l = QVBoxLayout(right_col)
        rc_l.setContentsMargins(0, 0, 0, 0)
        rc_l.setSpacing(4)

        self.card_input = QLineEdit()
        self.card_input.setObjectName("cardInput")
        self.card_input.setPlaceholderText("Scan card…")
        self.card_input.returnPressed.connect(self.on_card_input)
        self.card_input.setMaximumHeight(22)
        self.card_input.setFixedWidth(160)
        rc_l.addWidget(self.card_input, alignment=Qt.AlignRight)

        self.host_label = QLabel(self._host_string())
        self.host_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.host_label.setStyleSheet(
            f"color: {COLORS['fg_3']}; font-size: 11px; font-weight: 400;"
            f" font-family: 'SF Mono', Menlo, Consolas, monospace;"
            f" background: transparent;"
        )
        rc_l.addWidget(self.host_label, alignment=Qt.AlignRight)

        grid.addWidget(right_col, 0, 2, alignment=Qt.AlignVCenter | Qt.AlignRight)

        self._refresh_stats_labels()
        return bar

    def _stat_row(self, label: str, value_color: str):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        l = QHBoxLayout(row)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(8)
        value = QLabel("0")
        value.setStyleSheet(
            f"color: {value_color}; font-size: 14px; font-weight: 600;"
            f" background: transparent;"
        )
        caption = QLabel(label.upper())
        caption.setStyleSheet(
            f"color: {COLORS['fg_2']}; font-size: 11px; font-weight: 500;"
            f" letter-spacing: 1.6px; background: transparent;"
        )
        l.addWidget(value)
        l.addWidget(caption)
        return value, row

    def _host_string(self) -> str:
        url = self.container_url
        for prefix in ("https://", "http://"):
            if url.startswith(prefix):
                url = url[len(prefix):]
                break
        return url.rstrip('/')

    # ---------------------------------------------------------- state machine
    def set_hero_state(self, state: str, *, headline: str = None,
                       subline: str = None, name: str = "",
                       section: str = "", checkin_time: str = ""):
        """Update the hero composition for a given state.

        States: 'idle' | 'processing' | 'success' | 'error'.
        Callers pass any text overrides; defaults match the design.
        """
        self.puck.set_state(state)

        if state == 'idle':
            self._apply_headline(headline or "Tap your card", COLORS['fg_0'])
            self.subline_label.setText(subline or "Place your RFID card on the reader to check in")
            self.subline_label.setStyleSheet(
                f"color: {COLORS['fg_2']}; font-size: 18px; font-weight: 400;"
                f" background: transparent;"
            )
            self.subline_label.setVisible(True)
            self.attendee_box.setVisible(False)
        elif state == 'processing':
            self._apply_headline(headline or "Reading…", COLORS['amber'])
            self.subline_label.setText(subline or "Verifying your card with the server")
            self.subline_label.setStyleSheet(
                f"color: {COLORS['fg_2']}; font-size: 18px; font-weight: 400;"
                f" background: transparent;"
            )
            self.subline_label.setVisible(True)
            self.attendee_box.setVisible(False)
        elif state == 'success':
            self._apply_headline(headline or malay_greeting(datetime.now()), COLORS['green'])
            self.subline_label.setVisible(False)
            self.name_label.setText(name or "—")
            self.section_label.setText(section or "")
            self.checkin_label.setText(
                f"Checked in · {checkin_time}" if checkin_time else ""
            )
            self.attendee_box.setVisible(True)
        elif state == 'error':
            self._apply_headline(headline or "Card not recognised", COLORS['red'])
            self.subline_label.setText(subline or "Please report to the front office")
            self.subline_label.setStyleSheet(
                f"color: {COLORS['red']}; font-size: 18px; font-weight: 400;"
                f" background: transparent;"
            )
            self.subline_label.setVisible(True)
            self.attendee_box.setVisible(False)

    # ----------------------------------------------------------- system tray
    def create_system_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor(COLORS['green']))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, 4, 24, 24)
        painter.end()
        self.tray_icon.setIcon(QIcon(pixmap))

        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self.show)
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    # --------------------------------------------------------- background ops
    def start_background_tasks(self):
        self.card_input.setFocus()

        self.focus_timer = QTimer()
        self.focus_timer.timeout.connect(lambda: self.card_input.setFocus())
        self.focus_timer.start(2000)

        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.update_time)
        self.ui_timer.start(1000)

        self.daily_reset_timer = QTimer()
        self.daily_reset_timer.timeout.connect(self._check_daily_reset)
        self.daily_reset_timer.start(60_000)

        self.health_thread = HealthCheckThread(self.client)
        self.health_thread.health_status.connect(self.on_health_status)
        self.health_thread.start()

    def update_time(self):
        now = datetime.now()
        self.time_label.setText(now.strftime("%H:%M:%S"))
        self.date_label.setText(now.strftime("%A %d %B").upper())

    def on_health_status(self, is_healthy: bool, status_data: dict):
        self.container_online = is_healthy
        if is_healthy:
            self.consecutive_unhealthy = 0
            self.signal_dot.setStyleSheet(
                f"background: {COLORS['green']}; border-radius: 5px;"
            )
            self.signal_text.setText("ONLINE")
            self.signal_text.setStyleSheet(
                f"color: {COLORS['fg_1']}; font-size: 11px; font-weight: 600;"
                f" letter-spacing: 2px; background: transparent;"
            )
            if status_data and 'queue_size' in status_data:
                self.container_queue_size = status_data['queue_size']
        else:
            self.consecutive_unhealthy += 1
            self.signal_dot.setStyleSheet(
                f"background: {COLORS['red']}; border-radius: 5px;"
            )
            self.signal_text.setText("QUEUED")
            self.signal_text.setStyleSheet(
                f"color: {COLORS['fg_2']}; font-size: 11px; font-weight: 600;"
                f" letter-spacing: 2px; background: transparent;"
            )
            if self.consecutive_unhealthy >= 30:
                logging.getLogger('AttendanceApp').warning(
                    "Server unreachable for 30 consecutive polls — rebooting system"
                )
                subprocess.run(["sudo", "reboot"])

    # ----------------------------------------------------------- scan handler
    def on_card_input(self):
        card_id = self.card_input.text().strip()
        self.card_input.clear()
        if card_id:
            self.process_card(card_id)

    def process_card(self, card_id: str):
        timestamp_full = datetime.now().strftime('%H:%M:%S')
        timestamp_short = datetime.now().strftime('%H:%M')

        is_valid, error = self.client.validate_card_id(card_id)
        if not is_valid:
            self.failed_scans += 1
            self.total_scans += 1
            self.last_scan_time = timestamp_short
            self.last_scan_ok = False
            self.set_hero_state('error', headline="Invalid card", subline=error)
            self._refresh_stats_labels()
            self._update_last_scan_label()
            QTimer.singleShot(4000, self.reset_display)
            return

        # Processing UI — show before network call
        self.set_hero_state('processing')
        QApplication.processEvents()

        success, message, online, data = self.client.send_card_scan(card_id)
        name = (data or {}).get('name', '') or ''
        section = (data or {}).get('section', '') or ''

        self.total_scans += 1
        if success:
            self.successful_scans += 1
        else:
            self.failed_scans += 1

        self.last_scan_time = timestamp_short
        self.last_scan_ok = success

        if success:
            self.set_hero_state(
                'success',
                name=name or "Welcome",
                section=section,
                checkin_time=timestamp_full,
            )
        else:
            # The server message can be arbitrarily long (e.g. "Request
            # timeout - container not responding"). Keep it out of the 72px
            # headline (which would clip horizontally) and show it in the
            # word-wrapped subline instead.
            self.set_hero_state('error', headline="Scan failed",
                                subline=message or "Please try again or report to the office")

        self._refresh_stats_labels()
        self._update_last_scan_label()
        QTimer.singleShot(4000, self.reset_display)

    def reset_display(self):
        self.set_hero_state('idle')

    # ---------------------------------------------------------------- stats
    def _refresh_stats_labels(self):
        self.total_value.setText(str(self.total_scans))
        self.success_value.setText(str(self.successful_scans))
        self.failed_value.setText(str(self.failed_scans))
        self._save_stats()

    def _update_last_scan_label(self):
        if self.last_scan_time is None:
            self.last_scan_label.setText("Awaiting first scan")
            return
        if self.last_scan_ok and self.container_online:
            status = "Online"
        elif self.last_scan_ok:
            status = "Queued"
        else:
            status = "Failed"
        self.last_scan_label.setText(
            f"LAST SCAN · {self.last_scan_time} · {status.upper()}"
        )

    def _load_stats(self):
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            with open(STATS_FILE, "r") as f:
                data = json.load(f)
            if data.get("date") == today:
                self.total_scans = data.get("total_scans", 0)
                self.successful_scans = data.get("successful_scans", 0)
                self.failed_scans = data.get("failed_scans", 0)
            else:
                self._save_stats()
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            self._save_stats()

    def _save_stats(self):
        data = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_scans": self.total_scans,
            "successful_scans": self.successful_scans,
            "failed_scans": self.failed_scans,
        }
        try:
            with open(STATS_FILE, "w") as f:
                json.dump(data, f)
        except OSError as e:
            logging.warning(f"Could not save daily stats: {e}")

    def _check_daily_reset(self):
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            with open(STATS_FILE, "r") as f:
                data = json.load(f)
            if data.get("date") != today:
                self.total_scans = 0
                self.successful_scans = 0
                self.failed_scans = 0
                self._refresh_stats_labels()
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    # -------------------------------------------------------------- lifecycle
    def closeEvent(self, event):
        if self.health_thread:
            self.health_thread.stop()
            self.health_thread.wait()
        event.accept()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='GUI RFID Input Client for Dockerized Datang Reader'
    )
    parser.add_argument(
        '--url',
        default=DEFAULT_CONTAINER_URL,
        help=f'Container URL (default: {DEFAULT_CONTAINER_URL})'
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    window = AttendanceApp(args.url)
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
