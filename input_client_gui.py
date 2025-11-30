#!/usr/bin/env python3
"""
GUI Input Client for Datang Reader (Docker Deployment)

Modern PyQt5 GUI with SMK Sultan Ahmad Tajuddin branding.
Optimized for OrangePi Zero 3 embedded display.
"""

import sys
import time
import logging
import signal
import re
from datetime import datetime
from typing import Optional
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStatusBar, QSystemTrayIcon, QMenu, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QIcon, QPainter, QPixmap

from src.config import Config

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not found.", file=sys.stderr)
    print("Install it with: pip install requests", file=sys.stderr)
    sys.exit(1)


# Configuration
DEFAULT_CONTAINER_URL = "http://localhost:8080"
MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 5

# Modern Color Palette - Teal and Navy theme
COLORS = {
    # Base colors - teal background with dark blue-gray cards
    'bg_primary': '#313647',           # Teal background
    'bg_secondary': '#26667F',         # Light mint for secondary areas
    'bg_card': '#305669',              # Dark blue-gray card background
    'bg_elevated': '#263f4d',          # Darker blue-gray for elevated surfaces

    # Text colors - light text on dark cards
    'text_primary': '#ffffff',         # White for dark cards
    'text_secondary': '#e0f2f1',       # Light mint tint
    'text_muted': '#b0bec5',           # Light gray

    # Accent colors - terracotta as primary accent
    'accent_green': '#2ecc71',         # Vibrant green (keep for success states)
    'accent_yellow': '#f1c40f',        # Bright yellow (keep for warnings)
    'accent_red': '#e74c3c',           # Alert red (keep for errors)
    'accent_terracotta': '#C1785A',    # Terracotta for highlights

    # Status colors
    'success': '#4caf50',              # Success green
    'warning': '#ff9800',              # Warning orange
    'error': '#f44336',                # Error red
    'info': '#00bcd4',                 # Info cyan

    # UI elements
    'border_subtle': '#B7E5CD',        # Light mint borders
    'border_accent': '#C1785A',        # Terracotta accent borders
    'shadow': 'rgba(0, 0, 0, 0.2)',    # Medium shadow
}


class InputClient:
    """RFID input client that forwards card scans to Docker container"""

    def __init__(self, container_url: str):
        self.container_url = container_url.rstrip('/')
        self.card_endpoint = f"{self.container_url}/card"
        self.health_endpoint = f"{self.container_url}/health"
        self.status_endpoint = f"{self.container_url}/status"
        self.logger = logging.getLogger('InputClient')

    def check_container_health(self) -> bool:
        """Check if container is reachable and healthy"""
        try:
            response = requests.get(self.health_endpoint, timeout=REQUEST_TIMEOUT)
            return response.status_code == 200
        except Exception:
            return False

    def get_container_status(self) -> dict:
        """Get container status information"""
        try:
            response = requests.get(self.status_endpoint, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return {}

    def send_card_scan(self, card_id: str) -> tuple[bool, str, bool, dict]:
        """
        Send card scan to Docker container

        Args:
            card_id: RFID card ID to scan

        Returns:
            (success: bool, message: str, online: bool, data: dict)
        """
        try:
            payload = {"card_id": card_id}
            response = requests.post(
                self.card_endpoint,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    online = result.get('online', False)
                    message = result.get('message', 'Recorded')
                    data = result.get('data', {})
                    return True, message, online, data
                else:
                    return False, result.get('message', 'Unknown error'), False, {}
            else:
                return False, f"HTTP {response.status_code}", False, {}

        except requests.exceptions.Timeout:
            return False, "Request timeout - container not responding", False, {}
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to container", False, {}
        except Exception as e:
            return False, f"Error: {str(e)}", False, {}

    @staticmethod
    def validate_card_id(card_id: str) -> tuple[bool, str]:
        """Validate card ID format"""
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
            # Ensure status_data is never None (race condition when network drops)
            if status_data is None:
                status_data = {}
            self.health_status.emit(is_healthy, status_data)
            time.sleep(5)  # Check every 5 seconds

    def stop(self):
        self.running = False


class StatusIndicator(QWidget):
    """Modern circular status indicator with pulse animation"""

    def __init__(self, size=16, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color = QColor(COLORS['text_muted'])
        self._active = False

    def set_status(self, active: bool, color: str):
        """Update indicator status"""
        self._active = active
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event):
        """Custom paint for circular indicator"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw outer glow if active
        if self._active:
            glow_color = QColor(self._color)
            glow_color.setAlpha(80)
            painter.setBrush(glow_color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, self.width(), self.height())

        # Draw main circle
        painter.setBrush(self._color)
        painter.setPen(Qt.NoPen)
        margin = 3 if self._active else 0
        painter.drawEllipse(margin, margin, self.width() - 2*margin, self.height() - 2*margin)


class ModernCard(QFrame):
    """Modern card widget with subtle elevation"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border-radius: 12px;
                border: none;
            }}
        """)


class PulseAnimation:
    """Lightweight pulse/breathing animation for text elements

    Optimized for ARM hardware - uses timer-based stylesheet updates
    instead of QPropertyAnimation to minimize CPU usage.
    """

    def __init__(self, widget: QLabel, min_opacity: float = 0.8,
                 max_opacity: float = 1.0, fps: int = 12):
        """
        Initialize pulse animation

        Args:
            widget: QLabel to animate
            min_opacity: Minimum opacity (0.0-1.0)
            max_opacity: Maximum opacity (0.0-1.0)
            fps: Frames per second (lower = less CPU, 10-15 recommended for ARM)
        """
        self.widget = widget
        self.min_opacity = min_opacity
        self.max_opacity = max_opacity
        self.fps = fps

        # Animation state
        self.current_opacity = max_opacity
        self.direction = -1  # -1 = fading out, 1 = fading in
        self.step_size = 0.05  # Opacity change per frame

        # Timer for animation updates
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_opacity)

        # Store original stylesheet
        self.base_style = widget.styleSheet()

    def start(self):
        """Start the pulse animation"""
        if not self.timer.isActive():
            # Update base style to current stylesheet (in case it changed)
            self.base_style = self.widget.styleSheet()
            # Reset animation state
            self.current_opacity = self.max_opacity
            self.direction = -1
            # Start timer
            interval_ms = int(1000 / self.fps)
            self.timer.start(interval_ms)

    def stop(self):
        """Stop the pulse animation and reset to full opacity"""
        self.timer.stop()
        self._apply_opacity(self.max_opacity)

    def _update_opacity(self):
        """Update opacity for next frame (called by timer)"""
        # Update opacity value
        self.current_opacity += (self.direction * self.step_size)

        # Reverse direction at boundaries
        if self.current_opacity <= self.min_opacity:
            self.current_opacity = self.min_opacity
            self.direction = 1  # Start fading in
        elif self.current_opacity >= self.max_opacity:
            self.current_opacity = self.max_opacity
            self.direction = -1  # Start fading out

        # Apply to widget
        self._apply_opacity(self.current_opacity)

    def _apply_opacity(self, opacity: float):
        """Apply opacity to widget via stylesheet

        Args:
            opacity: Opacity value (0.0-1.0)
        """
        # Convert to 0-255 range for CSS rgba
        alpha = int(opacity * 255)

        # Apply opacity via color with alpha channel
        # Preserve margin styles from base stylesheet
        # Use white text color (RGB: 255, 255, 255) for dark cards
        style = self.base_style
        if 'color:' in style:
            # Replace existing color while preserving other styles
            style = re.sub(
                r'color:\s*[^;]+;',
                f'color: rgba(255, 255, 255, {alpha});',
                style
            )
        else:
            # Append color to existing styles
            style += f' color: rgba(255, 255, 255, {alpha});'

        self.widget.setStyleSheet(style)


class AttendanceApp(QMainWindow):
    """Main GUI window for Input Client with modern design"""

    def __init__(self, container_url: str):
        super().__init__()
        self.client = InputClient(container_url)
        self.container_url = container_url

        # Statistics
        self.total_scans = 0
        self.successful_scans = 0
        self.failed_scans = 0
        self.last_scan_time = None
        self.container_online = False
        self.container_queue_size = 0

        # Threads
        self.health_thread = None

        # Pulse animation for ready state
        self.pulse_animation = None  # Created after UI init

        self.init_ui()
        self.start_background_tasks()

    def init_ui(self):
        """Initialize user interface with modern design"""
        self.setWindowTitle("SMK Sultan Ahmad Tajuddin - Attendance System")
        self.setGeometry(100, 100, Config.WINDOW_WIDTH, Config.WINDOW_HEIGHT)

        # Set fullscreen if configured
        if Config.FULLSCREEN:
            self.showFullScreen()

        # Set main window style
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {COLORS['bg_primary']};
            }}
            QLabel {{
                color: {COLORS['text_primary']};
            }}
        """)

        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # Top bar (compact header with logo and system info)
        top_bar = self.create_top_bar()
        main_layout.addWidget(top_bar)

        # Main content area
        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        # Left sidebar - Status cards
        sidebar = self.create_sidebar()
        content_layout.addWidget(sidebar)

        # Center - Main display
        center_display = self.create_center_display()
        content_layout.addLayout(center_display, stretch=1)

        main_layout.addLayout(content_layout, stretch=1)

        # Card input field for HID keyboard reader (minimal visibility)
        self.card_input = QLineEdit()
        self.card_input.setPlaceholderText("Scan RFID card...")
        self.card_input.returnPressed.connect(self.on_card_input)
        self.card_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border: 1px solid {COLORS['bg_elevated']};
            }}
        """)
        self.card_input.setMaximumHeight(32)
        main_layout.addWidget(self.card_input)

        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {COLORS['bg_secondary']};
                color: {COLORS['text_secondary']};
                border-top: 1px solid {COLORS['border_subtle']};
                padding: 4px 10px;
                font-size: 11px;
            }}
        """)
        self.setStatusBar(self.status_bar)
        self.update_status_bar()

        # System tray icon
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.create_system_tray()

        # Initialize display to ready state (starts pulse animation)
        self.reset_display()

    def create_top_bar(self) -> QWidget:
        """Create compact top bar with logo and key info"""
        bar = ModernCard()
        bar.setFixedHeight(80)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)

        # Logo section
        logo_container = QWidget()
        logo_layout = QHBoxLayout(logo_container)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(12)

        logo_label = QLabel()
        try:
            logo_pixmap = QPixmap("/home/meon/Desktop/Datang/Datang-Reader/logo/Logo SMKSAT trans.png")
            if not logo_pixmap.isNull():
                scaled_logo = logo_pixmap.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                logo_label.setPixmap(scaled_logo)
            else:
                logo_label.setText("🎓")
                logo_label.setStyleSheet("font-size: 40px;")
        except Exception:
            logo_label.setText("🎓")
            logo_label.setStyleSheet("font-size: 40px;")

        logo_label.setFixedSize(60, 60)
        logo_label.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(logo_label)

        # Title section
        title_container = QWidget()
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        school_name = QLabel("SMK SULTAN AHMAD TAJUDDIN")
        school_name.setFont(QFont("Arial", 14, QFont.Bold))
        school_name.setStyleSheet(f"color: {COLORS['text_primary']};")
        title_layout.addWidget(school_name)

        system_name = QLabel("RFID Attendance System")
        system_name.setFont(QFont("Arial", 11))
        system_name.setStyleSheet(f"color: {COLORS['text_secondary']};")
        title_layout.addWidget(system_name)

        motto = QLabel("HIDUP BERJASA")
        motto.setFont(QFont("Arial", 9, QFont.Bold))
        motto.setStyleSheet(f"color: {COLORS['accent_yellow']}; letter-spacing: 1px;")
        title_layout.addWidget(motto)

        logo_layout.addWidget(title_container)
        layout.addWidget(logo_container)

        layout.addStretch()

        # Right section - Time and connection
        right_section = QWidget()
        right_layout = QVBoxLayout(right_section)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Time
        self.time_label = QLabel()
        self.time_label.setFont(QFont("Arial", 20, QFont.Bold))
        self.time_label.setStyleSheet(f"color: {COLORS['text_primary']};")
        self.time_label.setAlignment(Qt.AlignRight)
        self.update_time()
        right_layout.addWidget(self.time_label)

        # Connection status
        connection_widget = QWidget()
        connection_layout = QHBoxLayout(connection_widget)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        connection_layout.setSpacing(8)

        connection_label = QLabel("Server")
        connection_label.setFont(QFont("Arial", 10))
        connection_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        connection_layout.addWidget(connection_label)

        self.connection_indicator = StatusIndicator(12)
        self.connection_indicator.set_status(False, COLORS['error'])
        connection_layout.addWidget(self.connection_indicator)

        right_layout.addWidget(connection_widget)

        layout.addWidget(right_section)

        return bar

    def create_sidebar(self) -> QWidget:
        """Create left sidebar with status cards"""
        sidebar = QWidget()
        sidebar.setFixedWidth(240)

        layout = QVBoxLayout(sidebar)
        layout.setSpacing(15)
        layout.setContentsMargins(0, 0, 0, 0)

        # Statistics card
        stats_card = ModernCard()
        stats_layout = QVBoxLayout(stats_card)
        stats_layout.setContentsMargins(20, 20, 20, 20)
        stats_layout.setSpacing(15)

        stats_title = QLabel("Today's Statistics")
        stats_title.setFont(QFont("Arial", 12, QFont.Bold))
        stats_title.setStyleSheet(f"color: {COLORS['text_primary']};")
        stats_layout.addWidget(stats_title)

        # Total scans
        self.total_stat = self.create_stat_row("Total Scans", "0", COLORS['text_primary'])
        stats_layout.addWidget(self.total_stat)

        # Successful scans
        self.success_stat = self.create_stat_row("Successful", "0", COLORS['success'])
        stats_layout.addWidget(self.success_stat)

        # Failed scans
        self.failed_stat = self.create_stat_row("Failed", "0", COLORS['error'])
        stats_layout.addWidget(self.failed_stat)

        stats_layout.addStretch()
        layout.addWidget(stats_card)

        # System status card
        status_card = ModernCard()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(20, 20, 20, 20)
        status_layout.setSpacing(15)

        status_title = QLabel("System Status")
        status_title.setFont(QFont("Arial", 12, QFont.Bold))
        status_title.setStyleSheet(f"color: {COLORS['text_primary']};")
        status_layout.addWidget(status_title)

        # RFID reader status
        self.rfid_status = self.create_status_row("RFID Reader", "Ready", COLORS['success'])
        status_layout.addWidget(self.rfid_status)

        # Container status
        self.container_status = self.create_status_row("Container", "Offline", COLORS['error'])
        status_layout.addWidget(self.container_status)

        # Queue status
        self.queue_status = self.create_status_row("Queue", "Empty", COLORS['text_muted'])
        status_layout.addWidget(self.queue_status)

        status_layout.addStretch()
        layout.addWidget(status_card)

        layout.addStretch()

        # Exit button
        exit_btn = QPushButton("Exit System")
        exit_btn.clicked.connect(self.close)
        exit_btn.setFixedHeight(36)
        exit_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_elevated']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 8px;
                padding: 8px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['error']};
                border-color: {COLORS['error']};
            }}
            QPushButton:pressed {{
                background-color: #a93226;
            }}
        """)
        layout.addWidget(exit_btn)

        return sidebar

    def create_stat_row(self, label: str, value: str, color: str) -> QWidget:
        """Create statistics row"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        label_widget = QLabel(label)
        label_widget.setFont(QFont("Arial", 10))
        label_widget.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(label_widget)

        layout.addStretch()

        value_widget = QLabel(value)
        value_widget.setFont(QFont("Arial", 14, QFont.Bold))
        value_widget.setStyleSheet(f"color: {color};")
        value_widget.setObjectName("value")
        layout.addWidget(value_widget)

        return row

    def create_status_row(self, label: str, status: str, color: str) -> QWidget:
        """Create status row with indicator"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        label_widget = QLabel(label)
        label_widget.setFont(QFont("Arial", 10))
        label_widget.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(label_widget)

        layout.addStretch()

        indicator = StatusIndicator(10)
        indicator.set_status(color == COLORS['success'], color)
        indicator.setObjectName("indicator")
        layout.addWidget(indicator)

        status_widget = QLabel(status)
        status_widget.setFont(QFont("Arial", 10, QFont.Bold))
        status_widget.setStyleSheet(f"color: {color};")
        status_widget.setObjectName("status")
        layout.addWidget(status_widget)

        return row

    def update_stat_value(self, widget: QWidget, value: str):
        """Update stat row value"""
        value_label = widget.findChild(QLabel, "value")
        if value_label:
            value_label.setText(value)

    def update_status_row(self, widget: QWidget, status: str, color: str):
        """Update status row"""
        status_label = widget.findChild(QLabel, "status")
        indicator = widget.findChild(StatusIndicator, "indicator")

        if status_label:
            status_label.setText(status)
            status_label.setStyleSheet(f"color: {color};")

        if indicator:
            indicator.set_status(color == COLORS['success'], color)

    def create_center_display(self) -> QVBoxLayout:
        """Create center display area"""
        layout = QVBoxLayout()
        layout.setSpacing(16)

        # Main scan result card
        self.main_card = ModernCard()
        self.main_card.setMinimumHeight(400)

        card_layout = QVBoxLayout(self.main_card)
        card_layout.setAlignment(Qt.AlignCenter)
        card_layout.setSpacing(25)
        card_layout.setContentsMargins(30, 50, 30, 50)

        # Status icon (hidden by default, shown during scan results)
        self.status_icon = QLabel()
        self.status_icon.setFont(QFont("Arial", 80))
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setVisible(False)  # Hidden initially
        self.status_icon.setStyleSheet("background: transparent;")
        card_layout.addWidget(self.status_icon)

        # Main message
        self.message_label = QLabel("Ready to Scan")
        self.message_label.setFont(QFont("Arial", 38, QFont.Bold))
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet(f"color: {COLORS['text_primary']}; margin: 20px 0px;")
        self.message_label.setWordWrap(True)
        card_layout.addWidget(self.message_label)

        # Sub-message
        self.sub_message_label = QLabel("Place your RFID card on the reader")
        self.sub_message_label.setFont(QFont("Arial", 15))
        self.sub_message_label.setAlignment(Qt.AlignCenter)
        self.sub_message_label.setStyleSheet(f"color: {COLORS['text_secondary']}; margin-top: 5px;")
        self.sub_message_label.setWordWrap(True)
        card_layout.addWidget(self.sub_message_label)

        # Create pulse animation for message label (if enabled)
        if Config.ENABLE_PULSE_ANIMATION:
            self.pulse_animation = PulseAnimation(
                self.message_label,
                min_opacity=0.4,
                max_opacity=1.0,
                fps=Config.PULSE_ANIMATION_FPS
            )

        # Attendee info card
        self.attendee_card = ModernCard()
        self.attendee_card.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS['accent_green']},
                    stop:1 #229954
                );
                border-radius: 12px;
                border: 2px solid {COLORS['accent_terracotta']};
            }}
        """)
        self.attendee_card.setVisible(False)
        self.attendee_card.setFixedHeight(120)

        attendee_layout = QVBoxLayout(self.attendee_card)
        attendee_layout.setSpacing(8)
        attendee_layout.setContentsMargins(25, 15, 25, 15)

        # Attendee name
        self.name_label = QLabel("")
        self.name_label.setFont(QFont("Arial", 24, QFont.Bold))
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet("color: white;")
        attendee_layout.addWidget(self.name_label)

        # Section
        self.section_label = QLabel("")
        self.section_label.setFont(QFont("Arial", 14))
        self.section_label.setAlignment(Qt.AlignCenter)
        self.section_label.setStyleSheet(f"color: {COLORS['accent_terracotta']};")
        attendee_layout.addWidget(self.section_label)

        card_layout.addWidget(self.attendee_card)

        layout.addWidget(self.main_card, stretch=1)

        # Last scan info bar
        last_scan_bar = ModernCard()
        last_scan_bar.setFixedHeight(50)

        scan_layout = QHBoxLayout(last_scan_bar)
        scan_layout.setContentsMargins(20, 10, 20, 10)

        scan_icon = QLabel("🕐")
        scan_icon.setFont(QFont("Arial", 18))
        scan_layout.addWidget(scan_icon)

        self.last_scan_label = QLabel("No scans yet")
        self.last_scan_label.setFont(QFont("Arial", 12))
        self.last_scan_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        scan_layout.addWidget(self.last_scan_label)

        scan_layout.addStretch()

        container_label = QLabel(f"Container: {self.container_url}")
        container_label.setFont(QFont("Arial", 9))
        container_label.setStyleSheet(f"color: {COLORS['text_muted']};")
        scan_layout.addWidget(container_label)

        layout.addWidget(last_scan_bar)

        return layout

    def create_system_tray(self):
        """Create system tray icon"""
        self.tray_icon = QSystemTrayIcon(self)

        # Create icon
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor(COLORS['accent_green']))
        painter.drawEllipse(4, 4, 24, 24)
        painter.end()

        self.tray_icon.setIcon(QIcon(pixmap))

        # Create menu
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self.show)
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def start_background_tasks(self):
        """Start background tasks"""
        # Keep card input focused for HID keyboard reader
        self.card_input.setFocus()

        # Timer to ensure input field stays focused
        self.focus_timer = QTimer()
        self.focus_timer.timeout.connect(lambda: self.card_input.setFocus())
        self.focus_timer.start(2000)  # Refocus every 2 seconds

        # Timer for UI updates
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.update_time)
        self.ui_timer.start(1000)  # Update every second

        # Health check thread
        self.health_thread = HealthCheckThread(self.client)
        self.health_thread.health_status.connect(self.on_health_status)
        self.health_thread.start()

    def update_time(self):
        """Update time display"""
        current_time = datetime.now().strftime("%H:%M:%S")
        self.time_label.setText(current_time)

    def update_status_bar(self):
        """Update status bar"""
        self.status_bar.showMessage(
            f"  Total: {self.total_scans}  |  Success: {self.successful_scans}  |  Failed: {self.failed_scans}  "
        )

    def on_health_status(self, is_healthy: bool, status_data: dict):
        """Update connection status display"""
        self.container_online = is_healthy

        if is_healthy:
            # Update connection indicator
            self.connection_indicator.set_status(True, COLORS['success'])

            # Update container status
            self.update_status_row(
                self.container_status,
                "Online",
                COLORS['success']
            )

            # Update queue size from container status
            if status_data and 'queue_size' in status_data:
                self.container_queue_size = status_data['queue_size']
                if self.container_queue_size > 0:
                    queue_text = f"{self.container_queue_size} pending"
                    queue_color = COLORS['warning']
                else:
                    queue_text = "Empty"
                    queue_color = COLORS['success']

                self.update_status_row(
                    self.queue_status,
                    queue_text,
                    queue_color
                )
        else:
            # Update connection indicator
            self.connection_indicator.set_status(False, COLORS['error'])

            # Update container status
            self.update_status_row(
                self.container_status,
                "Offline",
                COLORS['error']
            )

    def on_card_input(self):
        """Handle card scan from RFID reader"""
        card_id = self.card_input.text().strip()
        self.card_input.clear()

        if card_id:
            self.process_card(card_id)

    def process_card(self, card_id: str):
        """Process a card scan"""
        timestamp = datetime.now().strftime('%H:%M:%S')

        # Validate
        is_valid, error = self.client.validate_card_id(card_id)
        if not is_valid:
            self.show_scan_result(False, f"Invalid Card: {error}", "", "", False)
            self.failed_scans += 1
            self.total_scans += 1
            self.update_statistics()
            return

        # Update display - scanning
        self.status_icon.setText("🔄")
        self.status_icon.setVisible(True)
        self.message_label.setText("Processing...")
        self.message_label.setStyleSheet(f"color: {COLORS['warning']}; margin: 20px 0px;")
        self.sub_message_label.setText(f"Card: {card_id[:8]}...")
        self.attendee_card.setVisible(False)

        # Stop pulse animation during processing
        if self.pulse_animation:
            self.pulse_animation.stop()

        # Send to container
        QApplication.processEvents()  # Update UI
        success, message, online, data = self.client.send_card_scan(card_id)

        # Extract name and section from data
        name = data.get('name', '') if data else ''
        section = data.get('section', '') if data else ''

        # Update statistics
        self.total_scans += 1
        if success:
            self.successful_scans += 1
        else:
            self.failed_scans += 1

        self.last_scan_time = timestamp

        # Show result
        self.show_scan_result(success, message, name, section, online)
        self.update_statistics()

        # Update last scan label
        status_icon = "✓" if success else "✗"
        mode_text = "ONLINE" if online else "OFFLINE" if success else "FAILED"
        mode_color = COLORS['success'] if online else COLORS['warning'] if success else COLORS['error']
        self.last_scan_label.setText(f"Last scan: {timestamp}  •  {status_icon} {mode_text}")
        self.last_scan_label.setStyleSheet(f"color: {mode_color}; font-weight: bold;")

        # Reset display after 4 seconds
        QTimer.singleShot(4000, self.reset_display)

    def update_statistics(self):
        """Update all statistics displays"""
        self.update_stat_value(self.total_stat, str(self.total_scans))
        self.update_stat_value(self.success_stat, str(self.successful_scans))
        self.update_stat_value(self.failed_stat, str(self.failed_scans))
        self.update_status_bar()

    def show_scan_result(self, success: bool, message: str, name: str = "",
                         section: str = "", online: bool = False):
        """Show scan result on main display"""
        if success:
            # Success state
            self.status_icon.setText("✅")
            self.status_icon.setVisible(True)
            self.message_label.setText("Attendance Recorded")
            self.message_label.setStyleSheet(f"color: {COLORS['success']}; margin: 20px 0px;")

            mode = "ONLINE" if online else "QUEUED (Offline)"
            mode_color = COLORS['success'] if online else COLORS['warning']
            self.sub_message_label.setText(mode)
            self.sub_message_label.setStyleSheet(f"color: {mode_color}; font-weight: bold; margin-top: 5px;")

            # Show attendee info if available
            if name or section:
                self.name_label.setText(name if name else "Unknown")
                self.section_label.setText(f"Section: {section}" if section else "")
                self.attendee_card.setVisible(True)
            else:
                self.attendee_card.setVisible(False)
        else:
            # Error state
            self.status_icon.setText("❌")
            self.status_icon.setVisible(True)
            self.message_label.setText("Error")
            self.message_label.setStyleSheet(f"color: {COLORS['error']}; margin: 20px 0px;")
            self.sub_message_label.setText(message)
            self.sub_message_label.setStyleSheet(f"color: {COLORS['error']}; margin-top: 5px;")
            self.attendee_card.setVisible(False)

    def reset_display(self):
        """Reset main display to ready state"""
        self.status_icon.setVisible(False)  # Hide icon in ready state
        self.message_label.setText("Ready to Scan")
        self.message_label.setStyleSheet(f"color: {COLORS['text_primary']}; margin: 20px 0px;")
        self.sub_message_label.setText("Place your RFID card on the reader")
        self.sub_message_label.setStyleSheet(f"color: {COLORS['text_secondary']}; margin-top: 5px;")
        self.attendee_card.setVisible(False)

        # Reset last scan label color
        self.last_scan_label.setStyleSheet(f"color: {COLORS['text_secondary']};")

        # Start pulse animation in ready state
        if self.pulse_animation and Config.ENABLE_PULSE_ANIMATION:
            self.pulse_animation.start()

    def closeEvent(self, event):
        """Handle window close"""
        if self.health_thread:
            self.health_thread.stop()
            self.health_thread.wait()
        if self.pulse_animation:
            self.pulse_animation.stop()
        event.accept()


def main():
    """Main entry point"""
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

    # Create application
    app = QApplication(sys.argv)

    # Setup signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Timer to allow Python to process signals (needed for Ctrl+C to work)
    timer = QTimer()
    timer.start(500)  # Check every 500ms
    timer.timeout.connect(lambda: None)  # Allow signal processing

    # Create and show main window
    window = AttendanceApp(args.url)
    window.show()

    # Run application
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
