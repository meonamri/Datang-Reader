"""
GUI Application for Datang Reader Linux Service

PyQt5-based graphical interface for the attendance kiosk.
"""

import sys
import logging
from typing import Optional
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStatusBar, QSystemTrayIcon, QMenu, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon, QPainter, QPixmap
from .config import Config


logger = logging.getLogger(__name__)


class AttendanceApp(QMainWindow):
    """Main attendance kiosk application window"""

    def __init__(self, service_manager):
        super().__init__()
        self.service_manager = service_manager
        self.init_ui()
        self.start_background_tasks()

    def init_ui(self):
        """Initialize user interface"""
        self.setWindowTitle(Config.WINDOW_TITLE)
        self.setGeometry(100, 100, Config.WINDOW_WIDTH, Config.WINDOW_HEIGHT)

        # Set fullscreen if configured
        if Config.FULLSCREEN:
            self.showFullScreen()

        # Set window style
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

        # Hidden card input field for HID keyboard reader
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

        # System tray icon (optional)
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

        layout.addStretch()

        # Connection status indicator
        self.connection_indicator = QLabel("⚫")
        self.connection_indicator.setFont(QFont("Arial", 24))
        self.connection_indicator.setToolTip("Connection Status")
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

        # API status
        self.api_status = self.create_status_item("API", "●", "#94e2d5")
        layout.addWidget(self.api_status)

        # Queue size
        self.queue_status = self.create_status_item("Queue", "0", "#94e2d5")
        layout.addWidget(self.queue_status)

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

        # Card ID display (optional)
        if Config.SHOW_CARD_ID:
            self.card_id_label = QLabel("")
            self.card_id_label.setFont(QFont("Courier", 16))
            self.card_id_label.setAlignment(Qt.AlignCenter)
            self.card_id_label.setStyleSheet("color: #7f849c; margin-top: 20px;")
            layout.addWidget(self.card_id_label)

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

        # Control buttons
        sync_btn = QPushButton("Sync Queue")
        sync_btn.clicked.connect(self.manual_sync)
        sync_btn.setStyleSheet(self.get_button_style())
        layout.addWidget(sync_btn)

        if not Config.FULLSCREEN:
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

        # Create icon (simple colored circle)
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
        """Start background scanning and update tasks"""
        # Keep card input focused for HID keyboard reader
        self.card_input.setFocus()

        # Timer to ensure input field stays focused
        self.focus_timer = QTimer()
        self.focus_timer.timeout.connect(lambda: self.card_input.setFocus())
        self.focus_timer.start(2000)  # Refocus every 2 seconds

        # Timer for UI updates
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.periodic_update)
        self.update_timer.start(1000)  # Update every second

        # Timer for auto-sync
        self.sync_timer = QTimer()
        self.sync_timer.timeout.connect(self.auto_sync)
        self.sync_timer.start(Config.RETRY_INTERVAL * 1000)

    def periodic_update(self):
        """Periodic UI updates"""
        self.update_time()
        self.update_status_indicators()
        self.update_status_bar()

    def update_time(self):
        """Update time display"""
        current_time = datetime.now().strftime("%H:%M:%S")
        self.time_label.setText(current_time)

    def update_status_indicators(self):
        """Update status indicators"""
        # RFID Reader status
        rfid_connected = self.service_manager.rfid_reader.is_connected
        self.update_status_item(self.rfid_status, "●" if rfid_connected else "○",
                               "#a6e3a1" if rfid_connected else "#f38ba8")

        # API status
        api_connected = self.service_manager.api_client.check_connection()
        self.update_status_item(self.api_status, "●" if api_connected else "○",
                               "#a6e3a1" if api_connected else "#f38ba8")

        # Queue size
        queue_size = self.service_manager.queue.get_queue_size()
        self.update_status_item(self.queue_status, str(queue_size),
                               "#94e2d5" if queue_size == 0 else "#fab387")

        # Connection indicator
        overall_status = rfid_connected and api_connected
        self.connection_indicator.setText("🟢" if overall_status else "🔴")

    def update_status_item(self, widget: QWidget, value: str, color: str):
        """Update status item value and color"""
        value_label = widget.findChild(QLabel, "value")
        if value_label:
            value_label.setText(value)
            value_label.setStyleSheet(f"color: {color};")

    def update_status_bar(self):
        """Update status bar"""
        stats = self.service_manager.queue.get_statistics()
        status_text = f"Pending: {stats.get('pending', 0)} | Synced: {stats.get('synced', 0)}"
        if stats.get('failed', 0) > 0:
            status_text += f" | Failed: {stats['failed']}"
        self.status_bar.showMessage(status_text)

    def on_card_input(self):
        """Handle card ID input from HID keyboard reader"""
        card_id = self.card_input.text().strip()
        self.card_input.clear()  # Clear for next scan

        if card_id:
            # Re-focus immediately for next scan
            self.card_input.setFocus()
            # Process the card
            self.on_card_scanned(card_id)

    def on_card_scanned(self, card_id: str):
        """Handle card scan event"""
        logger.info(f"Card scanned in GUI: {card_id}")

        try:
            # Process attendance
            result = self.service_manager.process_attendance(card_id)

            if result["success"]:
                self.show_success(result.get("message", "Attendance recorded!"))
            else:
                self.show_error(result.get("message", "Failed to record attendance"))

            # Update last scan
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.last_scan_label.setText(f"Last scan: {timestamp} - {card_id[:8]}...")

        except Exception as e:
            logger.error(f"Error processing card scan: {e}")
            self.show_error(f"Error: {str(e)}")

    def show_success(self, message: str):
        """Show success message"""
        self.status_icon.setText("✅")
        self.message_label.setText("Success!")
        self.message_label.setStyleSheet("color: #a6e3a1; margin: 20px;")
        self.sub_message_label.setText(message)

        # Reset after delay
        QTimer.singleShot(Config.SUCCESS_DISPLAY_TIME * 1000, self.reset_display)

    def show_error(self, message: str):
        """Show error message"""
        self.status_icon.setText("❌")
        self.message_label.setText("Error")
        self.message_label.setStyleSheet("color: #f38ba8; margin: 20px;")
        self.sub_message_label.setText(message)

        # Reset after delay
        QTimer.singleShot(Config.ERROR_DISPLAY_TIME * 1000, self.reset_display)

    def reset_display(self):
        """Reset display to ready state"""
        self.status_icon.setText("📱")
        self.message_label.setText("Ready to Scan")
        self.message_label.setStyleSheet("color: #cdd6f4; margin: 20px;")
        self.sub_message_label.setText("Please scan your RFID card")

    def manual_sync(self):
        """Manually trigger queue sync"""
        logger.info("Manual sync triggered")
        stats = self.service_manager.sync_queue()
        message = f"Synced: {stats['synced']}, Failed: {stats['failed']}"
        self.status_bar.showMessage(message, 5000)

    def auto_sync(self):
        """Auto sync queue"""
        queue_size = self.service_manager.queue.get_queue_size()
        if queue_size > 0:
            logger.info(f"Auto-syncing {queue_size} queued records")
            self.service_manager.sync_queue()

    def closeEvent(self, event):
        """Handle window close event"""
        logger.info("Closing application...")

        # Stop service manager
        if hasattr(self.service_manager, 'stop'):
            self.service_manager.stop()

        event.accept()


def run_gui(service_manager):
    """
    Run GUI application

    Args:
        service_manager: Service manager instance
    """
    app = QApplication(sys.argv)
    app.setApplicationName("Datang Reader")

    # Set application-wide font
    app.setFont(QFont("Arial", 12))

    window = AttendanceApp(service_manager)
    window.show()

    sys.exit(app.exec_())
