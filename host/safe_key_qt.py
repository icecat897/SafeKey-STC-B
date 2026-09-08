"""SafeKey V3 Qt 桌面客户端。Qt 随 EXE 打包，不依赖系统 Tcl/Tk。"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from safe_key import Device, make_vault, relock_vault, unlock_vault, verify_vault

try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None


STYLE = """
QWidget { background: #f5f7fb; color: #172033; font-family: "Microsoft YaHei UI"; font-size: 13px; }
QMainWindow { background: #f5f7fb; }
QGroupBox { background: white; border: 1px solid #dce3ef; border-radius: 10px; margin-top: 12px; padding: 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #334155; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px; }
QPushButton { background: #2563eb; color: white; border: 0; border-radius: 7px; padding: 8px 14px; font-weight: 600; }
QPushButton:hover { background: #1d4ed8; }
QPushButton#secondary { background: #e8eef8; color: #244060; }
QPushButton#danger { background: #dc2626; }
QLabel#title { font-size: 25px; font-weight: 700; color: #0f172a; }
QLabel#subtitle { color: #64748b; }
QLabel#status { font-size: 15px; font-weight: 700; color: #0f766e; }
QFrame#card { background: white; border: 1px solid #dce3ef; border-radius: 10px; }
"""


class SafeKeyWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.device: Device | None = None
        self.unlocked_dir: Path | None = None
        self.unlocked_vault: Path | None = None
        self.unlocked_at = 0.0
        self.last_fingerprint = None
        self.dirty = False
        self.setWindowTitle("SafeKey V3 本地文件保险箱")
        self.resize(980, 760)
        self.build_ui()
        self.refresh_ports()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("SafeKey V3")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("STC-B 硬件认证 · AES-GCM 本地文件保险箱")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        status_layout = QGridLayout(card)
        self.status_label = QLabel("未连接单片机")
        self.status_label.setObjectName("status")
        self.device_label = QLabel("设备：离线")
        self.countdown_label = QLabel("自动锁定：--")
        self.vault_info_label = QLabel("保险箱：未选择")
        status_layout.addWidget(self.status_label, 0, 0, 1, 2)
        status_layout.addWidget(self.device_label, 1, 0)
        status_layout.addWidget(self.countdown_label, 1, 1)
        status_layout.addWidget(self.vault_info_label, 2, 0, 1, 2)
        layout.addWidget(card)

        device_box = QGroupBox("硬件密钥")
        device_layout = QGridLayout(device_box)
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        refresh_btn = self.button("刷新串口", self.refresh_ports, "secondary")
        connect_btn = self.button("连接", self.connect_device)
        disconnect_btn = self.button("断开", self.disconnect_device, "secondary")
        self.input_label = QLabel("尚未收到单片机输入")
        device_layout.addWidget(QLabel("串口"), 0, 0)
        device_layout.addWidget(self.port_combo, 0, 1)
        device_layout.addWidget(refresh_btn, 0, 2)
        device_layout.addWidget(connect_btn, 0, 3)
        device_layout.addWidget(disconnect_btn, 0, 4)
        device_layout.addWidget(QLabel("PIN 输入"), 1, 0)
        device_layout.addWidget(self.input_label, 1, 1, 1, 4)
        layout.addWidget(device_box)

        vault_box = QGroupBox("保险箱")
        vault_layout = QGridLayout(vault_box)
        self.vault_edit = QLineEdit()
        self.output_edit = QLineEdit("D:\\SafeKey-Unlocked")
        self.autolock_spin = QSpinBox()
        self.autolock_spin.setRange(10, 86400)
        self.autolock_spin.setValue(300)
        vault_layout.addWidget(QLabel("保险箱文件"), 0, 0)
        vault_layout.addWidget(self.vault_edit, 0, 1, 1, 3)
        vault_layout.addWidget(self.button("选择", self.choose_vault, "secondary"), 0, 4)
        vault_layout.addWidget(self.button("检查完整性", self.check_vault, "secondary"), 0, 5)
        vault_layout.addWidget(QLabel("解锁目录"), 1, 0)
        vault_layout.addWidget(self.output_edit, 1, 1, 1, 3)
        vault_layout.addWidget(QLabel("自动锁定（秒）"), 1, 4)
        vault_layout.addWidget(self.autolock_spin, 1, 5)

        actions = QHBoxLayout()
        actions.addWidget(self.button("创建保险箱", self.create_vault))
        actions.addWidget(self.button("解锁保险箱", self.unlock))
        actions.addWidget(self.button("打开解锁目录", self.open_unlocked_dir, "secondary"))
        actions.addWidget(self.button("保存修改并锁定", self.save_and_lock))
        actions.addWidget(self.button("立即锁定", lambda: self.lock(True), "danger"))
        vault_layout.addLayout(actions, 2, 0, 1, 6)
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        vault_layout.addWidget(self.path_label, 3, 0, 1, 6)
        layout.addWidget(vault_box)

        log_box = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(300)
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_box, 1)

    @staticmethod
    def button(text, callback, style_name=""):
        btn = QPushButton(text)
        if style_name:
            btn.setObjectName(style_name)
        btn.clicked.connect(callback)
        return btn

    def append_log(self, text):
        self.log_view.appendPlainText(time.strftime("[%H:%M:%S] ") + text)

    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = list(list_ports.comports()) if list_ports else []
        self.port_combo.addItems([p.device for p in ports])
        preferred = next((p.device for p in ports if "CH340" in (p.description or "").upper()), None)
        if preferred:
            self.port_combo.setCurrentText(preferred)
        elif current:
            self.port_combo.setCurrentText(current)
        elif not ports:
            self.port_combo.setCurrentText("COM3")

    def connect_device(self):
        try:
            self.disconnect_device()
            port = self.port_combo.currentText().strip()
            self.device = Device(port)
            self.status_label.setText("已连接，请在学习板上输入 6 位 PIN")
            self.device_label.setText("设备：在线 / 等待认证")
            self.append_log(port + " 已打开，等待单片机复位")
            QTimer.singleShot(800, self.send_hello)
        except Exception as exc:
            self.device = None
            QMessageBox.critical(self, "连接失败", str(exc))

    def disconnect_device(self):
        self.lock(False)
        if self.device:
            self.device.close()
            self.device = None
        self.status_label.setText("未连接单片机")
        self.device_label.setText("设备：离线")

    def send_hello(self):
        if self.device:
            try:
                self.device.send_hello()
                self.append_log("已发送握手：SKHLLO")
            except Exception as exc:
                self.append_log("握手失败：" + str(exc))

    def choose_vault(self):
        name, _ = QFileDialog.getOpenFileName(self, "选择保险箱", "", "SafeKey vault (*.safevault);;全部文件 (*)")
        if name:
            self.vault_edit.setText(name)
            self.refresh_vault_info()

    def refresh_vault_info(self):
        try:
            count, size = verify_vault(Path(self.vault_edit.text()))
            self.vault_info_label.setText("保险箱：%s | %d 个条目 | %d 字节" % (Path(self.vault_edit.text()).name, count, size))
        except Exception:
            self.vault_info_label.setText("保险箱：未选择或无法验证")

    def create_vault(self):
        source = QFileDialog.getExistingDirectory(self, "选择需要加密的文件夹")
        if not source:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "保存保险箱", "", "SafeKey vault (*.safevault)")
        if not dest:
            return
        if not dest.lower().endswith(".safevault"):
            dest += ".safevault"
        try:
            source_path, dest_path = Path(source).resolve(), Path(dest).resolve()
            make_vault(source_path, dest_path)
            self.vault_edit.setText(str(dest_path))
            self.refresh_vault_info()
            answer = QMessageBox.question(
                self,
                "是否删除原文件夹",
                "保险箱已创建并通过加密。是否删除原文件夹中的明文？\n\n首次使用建议选择“否”，验证能解锁后再处理原文件夹。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                if source_path == dest_path or source_path in dest_path.parents:
                    raise ValueError("保险箱位于原文件夹内部，已拒绝删除")
                shutil.rmtree(source_path)
                QMessageBox.information(self, "完成", "保险箱已创建，原文件夹已删除")
            else:
                QMessageBox.information(self, "完成", "保险箱已创建，原文件夹已保留")
        except Exception as exc:
            QMessageBox.critical(self, "创建失败", str(exc))

    def unlock(self):
        if not self.device or not self.device.authenticated:
            QMessageBox.warning(self, "需要认证", "请先连接单片机并输入正确 PIN")
            return
        try:
            if self.unlocked_dir:
                self.lock(False)
            self.unlocked_vault = Path(self.vault_edit.text()).resolve()
            self.unlocked_dir = unlock_vault(self.unlocked_vault, Path(self.output_edit.text().strip()))
            self.unlocked_at = time.monotonic()
            self.last_fingerprint = self.directory_fingerprint(self.unlocked_dir)
            self.dirty = False
            self.path_label.setText("已解锁到：" + str(self.unlocked_dir))
            self.status_label.setText("已解锁，可修改文件后保存并锁定")
            self.open_unlocked_dir()
        except Exception as exc:
            QMessageBox.critical(self, "解锁失败", str(exc))

    def open_unlocked_dir(self):
        if not self.unlocked_dir or not self.unlocked_dir.exists():
            QMessageBox.warning(self, "尚未解锁", "请先解锁保险箱")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.unlocked_dir)))

    def check_vault(self):
        try:
            count, size = verify_vault(Path(self.vault_edit.text()))
            self.refresh_vault_info()
            QMessageBox.information(self, "完整性检查通过", "AES-GCM 认证有效\n条目数：%d\n载荷：%d 字节" % (count, size))
        except Exception as exc:
            QMessageBox.critical(self, "完整性检查失败", str(exc))

    @staticmethod
    def directory_fingerprint(directory):
        entries = []
        for item in sorted(directory.rglob("*")):
            if item.is_symlink():
                entries.append((item.relative_to(directory).as_posix(), "symlink"))
            elif item.is_file():
                stat = item.stat()
                entries.append((item.relative_to(directory).as_posix(), stat.st_size, stat.st_mtime_ns))
        return tuple(entries)

    def save_and_lock(self):
        if not self.unlocked_dir or not self.unlocked_vault:
            QMessageBox.warning(self, "尚未解锁", "请先解锁保险箱")
            return
        try:
            relock_vault(self.unlocked_dir, self.unlocked_vault)
            self.lock(False)
            self.status_label.setText("修改已保存，保险箱已锁定")
            self.refresh_vault_info()
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))

    def lock(self, ask_save=False):
        if ask_save and self.unlocked_dir and self.dirty:
            answer = QMessageBox.question(
                self, "检测到修改", "是否先保存修改再锁定？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    relock_vault(self.unlocked_dir, self.unlocked_vault)
                except Exception as exc:
                    QMessageBox.critical(self, "保存失败", str(exc))
                    return False
        self.cleanup_unlocked_dir()
        self.unlocked_vault = None
        self.unlocked_at = 0.0
        self.last_fingerprint = None
        self.dirty = False
        self.path_label.setText("")
        self.countdown_label.setText("自动锁定：--")
        if self.device:
            self.device.authenticated = False
        return True

    def cleanup_unlocked_dir(self):
        if not self.unlocked_dir:
            return
        target = self.unlocked_dir
        self.unlocked_dir = None
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.append_log("解锁目录清理失败：" + str(exc))

    def tick(self):
        if not self.device:
            return
        try:
            for frame in self.device.poll():
                self.handle_frame(frame)
            if self.unlocked_dir:
                current = self.directory_fingerprint(self.unlocked_dir)
                if current != self.last_fingerprint:
                    self.dirty = True
                    self.last_fingerprint = current
                    self.path_label.setText("解锁目录已有修改，请保存修改后再锁定")
                timeout = self.autolock_spin.value()
                remaining = max(0, timeout - int(time.monotonic() - self.unlocked_at))
                self.countdown_label.setText("自动锁定：%d 秒" % remaining)
                if remaining == 0:
                    self.lock(False)
                    self.status_label.setText("达到自动锁定时间，保险箱已锁定")
            if not self.device.authenticated and self.unlocked_dir:
                self.lock(False)
                self.status_label.setText("硬件密钥离线或认证失效，保险箱已锁定")
        except Exception as exc:
            self.lock(False)
            self.device_label.setText("设备：离线")
            self.status_label.setText("单片机连接异常，保险箱已锁定")
            self.append_log("串口异常：" + str(exc))

    def handle_frame(self, frame):
        if frame.startswith(b"SKRDY"):
            self.device_label.setText("设备：在线 / 等待认证")
            self.input_label.setText("已输入 0/6")
            self.append_log("单片机已准备")
        elif frame.startswith(b"SKKY"):
            self.input_label.setText("已输入 %d/6，数字仅在学习板显示" % frame[4])
        elif frame.startswith(b"SKBK"):
            self.input_label.setText("已回退到第 %d 位" % frame[4])
        elif frame.startswith(b"SKCL"):
            self.input_label.setText("输入已清空")
        elif frame.startswith(b"SKOK"):
            self.device_label.setText("设备：在线 / 已认证")
            self.status_label.setText("认证成功，可以解锁保险箱")
            self.input_label.setText("认证成功")
            self.append_log("硬件 PIN 认证成功")
        elif frame.startswith(b"SKER"):
            self.device_label.setText("设备：在线 / PIN 错误")
            self.input_label.setText("认证失败，第 %d 次" % frame[4])
        elif frame.startswith(b"SKLK"):
            self.device_label.setText("设备：在线 / 暂时锁定")
            self.input_label.setText("失败过多，锁定 30 秒")

    def closeEvent(self, event):
        self.lock(False)
        if self.device:
            self.device.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = SafeKeyWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
