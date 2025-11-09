#!/usr/bin/env python3
"""
GUI Input Client for Datang Reader (Docker Deployment)

Beautiful PyQt5 GUI that captures RFID card scans and forwards to Docker container.
Uses the same design as the main datang_reader.py GUI.
"""

import sys
import time
import logging
from datetime import datetime
from typing import Optional
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStatusBar, QSystemTrayIcon, QMenu, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QIcon, QPainter, QPixmap

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
                    data = result.get('data', {})  # Extract data field
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


class AttendanceApp(QMainWindow):
    """Main GUI window for Input Client"""

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

        self.init_ui()
        self.start_background_tasks()

    def init_ui(self):
        """Initialize user interface"""
        self.setWindowTitle("Datang Reader - Input Client")
        self.setGeometry(100, 100, 900, 700)

        # Set window style (Catppuccin Mocha theme)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QLabel {
                color: #cdd6f4;
            }
        """)

        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(40, 40, 40, 40)

        # Header
        header = self.create_header()
        main_layout.addWidget(header)

        # Status panel
        self.status_panel = self.create_status_panel()
        main_layout.addWidget(self.status_panel)

        # Main display area
        self.main_display = self.create_main_display()
        main_layout.addWidget(self.main_display, stretch=1)

        # Card input field for HID keyboard reader
        self.card_input = QLineEdit()
        self.card_input.setPlaceholderText("Card scanner input (auto-focus)")
        self.card_input.returnPressed.connect(self.on_card_input)
        self.card_input.setStyleSheet("""
            QLineEdit {
                background-color: #313244;
                color: #9399b2;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 5px;
                font-size: 12px;
            }
        """)
        self.card_input.setMaximumHeight(30)
        main_layout.addWidget(self.card_input)

        # Footer with stats
        footer = self.create_footer()
        main_layout.addWidget(footer)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.update_status_bar()

        # System tray icon
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.create_system_tray()

    def create_header(self) -> QWidget:
        """Create header section"""
        header = QFrame()
        header.setFixedHeight(100)
        header.setStyleSheet("QFrame { background-color: #313244; border-radius: 10px; }")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(30, 20, 30, 20)

        # Title
        title = QLabel("Datang Reader")
        title.setFont(QFont("Arial", 32, QFont.Bold))
        title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("Input Client")
        subtitle.setFont(QFont("Arial", 14))
        subtitle.setStyleSheet("color: #7f849c;")
        layout.addWidget(subtitle)

        layout.addStretch()

        # Container connection status indicator
        self.connection_indicator = QLabel("⚫")
        self.connection_indicator.setFont(QFont("Arial", 24))
        self.connection_indicator.setToolTip("Docker Container Status")
        layout.addWidget(self.connection_indicator)

        # Time display
        self.time_label = QLabel()
        self.time_label.setFont(QFont("Arial", 20))
        self.update_time()
        layout.addWidget(self.time_label)

        return header

    def create_status_panel(self) -> QWidget:
        """Create status panel"""
        panel = QFrame()
        panel.setFixedHeight(80)
        panel.setStyleSheet("QFrame { background-color: #313244; border-radius: 10px; }")

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(30)

        # RFID Reader status
        self.rfid_status = self.create_status_item("RFID Reader", "●", "#94e2d5")
        layout.addWidget(self.rfid_status)

        # Container status
        self.container_status = self.create_status_item("Container", "●", "#f38ba8")
        layout.addWidget(self.container_status)

        # Queue size (from container)
        self.queue_status = self.create_status_item("Queue", "0", "#94e2d5")
        layout.addWidget(self.queue_status)

        # Scan statistics
        self.scan_stats = self.create_status_item("Scans", "0/0", "#a6e3a1")
        layout.addWidget(self.scan_stats)

        layout.addStretch()

        return panel

    def create_status_item(self, label_text: str, value: str, color: str) -> QWidget:
        """Create status item widget"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        label = QLabel(label_text + ":")
        label.setFont(QFont("Arial", 14))
        layout.addWidget(label)

        value_label = QLabel(value)
        value_label.setFont(QFont("Arial", 14, QFont.Bold))
        value_label.setStyleSheet(f"color: {color};")
        value_label.setObjectName("value")
        layout.addWidget(value_label)

        return widget

    def create_main_display(self) -> QWidget:
        """Create main display area"""
        display = QFrame()
        display.setStyleSheet("QFrame { background-color: #313244; border-radius: 10px; }")

        layout = QVBoxLayout(display)
        layout.setAlignment(Qt.AlignCenter)

        # Icon/Status
        self.status_icon = QLabel("📱")
        self.status_icon.setFont(QFont("Arial", 120))
        self.status_icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_icon)

        # Message
        self.message_label = QLabel("Ready to Scan")
        self.message_label.setFont(QFont("Arial", 36, QFont.Bold))
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet("color: #cdd6f4; margin: 20px;")
        layout.addWidget(self.message_label)

        # Sub-message
        self.sub_message_label = QLabel("Please scan your RFID card")
        self.sub_message_label.setFont(QFont("Arial", 20))
        self.sub_message_label.setAlignment(Qt.AlignCenter)
        self.sub_message_label.setStyleSheet("color: #9399b2;")
        layout.addWidget(self.sub_message_label)

        # Attendee Name Label
        self.name_label = QLabel("")
        self.name_label.setFont(QFont("Arial", 28, QFont.Bold))
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet("color: #89b4fa; margin-top: 10px;")
        self.name_label.setVisible(False)  # Hidden by default
        layout.addWidget(self.name_label)

        # Section Label
        self.section_label = QLabel("")
        self.section_label.setFont(QFont("Arial", 18))
        self.section_label.setAlignment(Qt.AlignCenter)
        self.section_label.setStyleSheet("color: #a6adc8; margin-top: 5px;")
        self.section_label.setVisible(False)  # Hidden by default
        layout.addWidget(self.section_label)

        return display

    def create_footer(self) -> QWidget:
        """Create footer with controls"""
        footer = QFrame()
        footer.setFixedHeight(60)
        footer.setStyleSheet("QFrame { background-color: #313244; border-radius: 10px; }")

        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 10, 20, 10)

        # Last scan info
        self.last_scan_label = QLabel("No scans yet")
        self.last_scan_label.setFont(QFont("Arial", 12))
        self.last_scan_label.setStyleSheet("color: #9399b2;")
        layout.addWidget(self.last_scan_label)

        layout.addStretch()

        # Container URL
        url_label = QLabel(f"Container: {self.container_url}")
        url_label.setFont(QFont("Arial", 10))
        url_label.setStyleSheet("color: #7f849c;")
        layout.addWidget(url_label)

        # Quit button
        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(self.close)
        quit_btn.setStyleSheet(self.get_button_style("#f38ba8"))
        layout.addWidget(quit_btn)

        return footer

    def get_button_style(self, color: str = "#89b4fa") -> str:
        """Get button stylesheet"""
        return f"""
            QPushButton {{
                background-color: {color};
                color: #1e1e2e;
                border: none;
                border-radius: 5px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
            QPushButton:pressed {{
                background-color: {color}aa;
            }}
        """

    def create_system_tray(self):
        """Create system tray icon"""
        self.tray_icon = QSystemTrayIcon(self)

        # Create icon (colored circle)
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor("#89b4fa"))
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
            f"Total: {self.total_scans} | Success: {self.successful_scans} | Failed: {self.failed_scans}"
        )

    def on_health_status(self, is_healthy: bool, status_data: dict):
        """Update connection status display"""
        self.container_online = is_healthy

        # Update connection indicator
        if is_healthy:
            self.connection_indicator.setText("🟢")
            self.connection_indicator.setStyleSheet("color: #a6e3a1;")

            # Update container status
            value_label = self.container_status.findChild(QLabel, "value")
            if value_label:
                value_label.setText("●")
                value_label.setStyleSheet("color: #a6e3a1;")

            # Update queue size from container status
            if status_data and 'queue_size' in status_data:
                self.container_queue_size = status_data['queue_size']
                queue_label = self.queue_status.findChild(QLabel, "value")
                if queue_label:
                    queue_label.setText(str(self.container_queue_size))
        else:
            self.connection_indicator.setText("🔴")
            self.connection_indicator.setStyleSheet("color: #f38ba8;")

            # Update container status
            value_label = self.container_status.findChild(QLabel, "value")
            if value_label:
                value_label.setText("●")
                value_label.setStyleSheet("color: #f38ba8;")

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
            self.show_scan_result(False, f"Invalid: {error}", card_id)
            self.failed_scans += 1
            self.total_scans += 1
            self.update_status_bar()
            return

        # Update display - scanning
        self.status_icon.setText("🔄")
        self.message_label.setText("Processing...")
        self.message_label.setStyleSheet("color: #f9e2af;")
        self.sub_message_label.setText(f"Card: {card_id[:8]}...")

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
        self.show_scan_result(success, message, card_id, online, name, section)
        self.update_status_bar()

        # Update last scan label
        status_text = "✓" if success else "✗"
        mode_text = "ONLINE" if online else "OFFLINE" if success else "FAILED"
        self.last_scan_label.setText(f"Last scan: {timestamp} | {status_text} {mode_text}")

        # Update scan stats
        stats_label = self.scan_stats.findChild(QLabel, "value")
        if stats_label:
            stats_label.setText(f"{self.successful_scans}/{self.total_scans}")

        # Reset display after 3 seconds
        QTimer.singleShot(3000, self.reset_display)

    def show_scan_result(self, success: bool, message: str, card_id: str, 
                         online: bool = False, name: str = "", section: str = ""):
        """Show scan result on main display"""
        if success:
            self.status_icon.setText("✅")
            self.message_label.setText("Attendance Recorded")
            self.message_label.setStyleSheet("color: #a6e3a1;")
            mode = "ONLINE" if online else "QUEUED"
            self.sub_message_label.setText(f"{mode} - {message}")
            
            # Display name if available
            if name:
                self.name_label.setText(name)
                self.name_label.setVisible(True)
            else:
                self.name_label.setVisible(False)
            
            # Display section if available
            if section:
                self.section_label.setText(f"Section: {section}")
                self.section_label.setVisible(True)
            else:
                self.section_label.setVisible(False)
        else:
            self.status_icon.setText("❌")
            self.message_label.setText("Error")
            self.message_label.setStyleSheet("color: #f38ba8;")
            self.sub_message_label.setText(message)
            # Hide name and section on error
            self.name_label.setVisible(False)
            self.section_label.setVisible(False)

    def reset_display(self):
        """Reset main display to ready state"""
        self.status_icon.setText("📱")
        self.message_label.setText("Ready to Scan")
        self.message_label.setStyleSheet("color: #cdd6f4;")
        self.sub_message_label.setText("Please scan your RFID card")
        
        # Hide name and section labels
        self.name_label.setVisible(False)
        self.section_label.setVisible(False)

    def closeEvent(self, event):
        """Handle window close"""
        if self.health_thread:
            self.health_thread.stop()
            self.health_thread.wait()
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

    # Create and show main window
    window = AttendanceApp(args.url)
    window.show()

    # Run application
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
