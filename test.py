import sys
import cv2
import numpy as np
import mss
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QLabel, QSpinBox, QSystemTrayIcon, QMenu, QDialog
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPoint
from PyQt6.QtGui import QIcon, QPixmap, QImage, QAction, QFont, QColor, QPainter

# -------- Capture Thread --------
class CaptureThread(QThread):
    update_frame = pyqtSignal(np.ndarray)
    error_signal = pyqtSignal(str)

    def __init__(self, monitor_index=1, box_width=200, box_height=150, output_width=1280, output_height=720):
        super().__init__()
        self.monitor_index = monitor_index
        self.box_width = box_width
        self.box_height = box_height
        self.output_width = output_width
        self.output_height = output_height
        self.running = False

    def run(self):
        try:
            with mss.mss() as sct:
                while self.running:
                    if self.monitor_index >= len(sct.monitors):
                        self.error_signal.emit(f"Monitor {self.monitor_index} not available")
                        break

                    monitor = sct.monitors[self.monitor_index]
                    img = np.array(sct.grab(monitor))
                    frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                    h, w, _ = frame.shape
                    cx, cy = w // 2, h // 2
                    x1, y1 = max(0, cx - self.box_width // 2), max(0, cy - self.box_height // 2)
                    x2, y2 = min(w, cx + self.box_width // 2), min(h, cy + self.box_height // 2)

                    cropped = frame[y1:y2, x1:x2]
                    enlarged = cv2.resize(cropped, (self.output_width, self.output_height), interpolation=cv2.INTER_LINEAR)
                    self.update_frame.emit(enlarged)

        except Exception as e:
            self.error_signal.emit(str(e))

    def stop(self):
        self.running = False
        self.wait()


# -------- Zoom Window --------
class ZoomWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Zoomed View (Q to Close)")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setGeometry(200, 200, 1280, 720)
        self.setMinimumSize(200, 150)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.label)
        self.setCentralWidget(central)
        self.show()

        # --- For dragging ---
        self.dragging = False
        self.offset = QPoint()

    def update_frame(self, frame):
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        qt_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qt_img)

        # --- Resize outer window dynamically ---
        self.resize(w, h)

        # --- Scale the label to match window size ---
        self.label.setPixmap(
            pix.scaled(
                self.size(),  # match outer window size
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Q:
            self.close()

    # --- Dragging like floating button ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.offset = event.pos()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(self.pos() + event.pos() - self.offset)

    def mouseReleaseEvent(self, event):
        self.dragging = False


# -------- Control Panel --------
class ControlPanel(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setFixedSize(280, 350)
        self.setStyleSheet("""
            QDialog {background: #1e1e1e; color: #fff; border-radius: 10px;}
            QLabel {font-weight: bold;}
            QPushButton {background: #2b2b2b; color: #fff; border-radius: 5px; padding: 6px;}
            QPushButton:hover {background: #3c3c3c;}
            QSpinBox, QComboBox {background: #2b2b2b; color: #fff; border-radius: 5px; padding: 3px;}
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Select Monitor:"))
        self.monitor_combo = QComboBox()
        self.populate_monitors()
        layout.addWidget(self.monitor_combo)

        # Box size
        box_layout = QHBoxLayout()
        box_layout.addWidget(QLabel("Box W:"))
        self.box_width_spin = QSpinBox()
        self.box_width_spin.setRange(50, 1000)
        self.box_width_spin.setValue(self.parent.settings['box_width'])
        box_layout.addWidget(self.box_width_spin)

        box_layout.addWidget(QLabel("Box H:"))
        self.box_height_spin = QSpinBox()
        self.box_height_spin.setRange(50, 1000)
        self.box_height_spin.setValue(self.parent.settings['box_height'])
        box_layout.addWidget(self.box_height_spin)
        layout.addLayout(box_layout)

        # Output size
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Out W:"))
        self.output_width_spin = QSpinBox()
        self.output_width_spin.setRange(100, 3840)
        self.output_width_spin.setValue(self.parent.settings['output_width'])
        output_layout.addWidget(self.output_width_spin)

        output_layout.addWidget(QLabel("Out H:"))
        self.output_height_spin = QSpinBox()
        self.output_height_spin.setRange(100, 2160)
        self.output_height_spin.setValue(self.parent.settings['output_height'])
        output_layout.addWidget(self.output_height_spin)
        layout.addLayout(output_layout)

        # Buttons
        self.start_btn = QPushButton("▶ Start Capture")
        self.start_btn.clicked.connect(self.toggle_capture)
        layout.addWidget(self.start_btn)

        save_btn = QPushButton("⚙ Save Settings")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)

        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.setLayout(layout)

    def populate_monitors(self):
        try:
            with mss.mss() as sct:
                for i, m in enumerate(sct.monitors):
                    self.monitor_combo.addItem(f"Monitor {i} ({m['width']}x{m['height']})", i)
                self.monitor_combo.setCurrentIndex(self.parent.settings['monitor_index'])
        except Exception:
            self.monitor_combo.addItem("Monitor 0 (Error)", 0)

    def toggle_capture(self):
        if self.parent.capture_thread and self.parent.capture_thread.isRunning():
            self.parent.stop_capture()
            self.start_btn.setText("▶ Start Capture")
        else:
            self.save_settings()
            self.parent.start_capture()
            self.start_btn.setText("⏹ Stop Capture")

    def save_settings(self):
        self.parent.settings.update({
            'monitor_index': self.monitor_combo.currentIndex(),
            'box_width': self.box_width_spin.value(),
            'box_height': self.box_height_spin.value(),
            'output_width': self.output_width_spin.value(),
            'output_height': self.output_height_spin.value()
        })


# -------- Floating Button --------
class FloatingControls(QMainWindow):
    def __init__(self):
        super().__init__()
        self.capture_thread = None
        self.zoom_window = None
        self.settings = {
            'monitor_index': 1,
            'box_width': 200,
            'box_height': 150,
            'output_width': 1280,
            'output_height': 720
        }
        self.init_ui()
        self.init_tray()

    def init_ui(self):
        self.setWindowTitle("Screen Zoom")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(70, 70)

        central = QWidget()
        central.setStyleSheet("""
            QWidget {
                background: #007ACC;
                border-radius: 35px;
            }
            QWidget:hover {
                background: #0096FF;
            }
        """)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(5, 5, 5, 5)

        self.menu_btn = QPushButton("☰")
        self.menu_btn.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        self.menu_btn.setStyleSheet("background: transparent; border: none; color: white;")
        self.menu_btn.clicked.connect(self.show_control_panel)
        layout.addWidget(self.menu_btn)
        self.setCentralWidget(central)

        # Drag support
        self.dragging = False
        self.offset = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.offset = event.pos()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(self.pos() + event.pos() - self.offset)

    def mouseReleaseEvent(self, event):
        self.dragging = False

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))

        tray_menu = QMenu()
        show_action = QAction("Show Controls", self)
        show_action.triggered.connect(self.show)
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.quit_application)
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(lambda reason: self.show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray_icon.show()

    def show_control_panel(self):
        if hasattr(self, 'control_panel') and self.control_panel.isVisible():
            self.control_panel.close()
            return
        self.control_panel = ControlPanel(self)
        self.control_panel.show()
        self.control_panel.move(self.pos().x() + self.width() + 5, self.pos().y())

    def start_capture(self):
        if self.capture_thread and self.capture_thread.isRunning():
            return
        self.capture_thread = CaptureThread(**self.settings)
        self.capture_thread.update_frame.connect(self.show_zoom_window)
        self.capture_thread.error_signal.connect(lambda e: print("Error:", e))
        self.capture_thread.running = True
        self.capture_thread.start()

    def stop_capture(self):
        if self.capture_thread:
            self.capture_thread.stop()
        if self.zoom_window:
            self.zoom_window.close()
            self.zoom_window = None

    def show_zoom_window(self, frame):
        if not self.zoom_window:
            self.zoom_window = ZoomWindow()
        self.zoom_window.update_frame(frame)

    def closeEvent(self, event):
        self.stop_capture()
        event.accept()

    def quit_application(self):
        self.stop_capture()
        QApplication.quit()


# -------- Main --------
def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = FloatingControls()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
