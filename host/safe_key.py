"""SafeKey Windows 主机程序

第一版课程原型：通过 CH340 串口等待单片机认证，再解密本地文件保险箱。
依赖：Python 3.9+、pyserial、cryptography。
"""
from __future__ import annotations

import argparse
import atexit
import base64
import hashlib
import io
import json
import os
import shutil
import struct
import tempfile
import threading
import time
import zipfile
import webbrowser
from pathlib import Path
try:
    from tkinter import Tk, StringVar, filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError:
    # Qt 正式版只复用本文件中的加密与串口核心；打包时无需 Tcl/Tk。
    Tk = StringVar = filedialog = messagebox = ttk = ScrolledText = None

SERIAL_IMPORT_ERROR = None
try:
    import serial
    from serial.tools import list_ports
except ImportError as exc:
    serial = None
    list_ports = None
    SERIAL_IMPORT_ERROR = exc

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC_V1 = b"SAFEKEY1"
MAGIC = b"SAFEKEY2"
FRAME_HELLO = b"SKHLLO\x00\x00"
DEVICE_SECRET = b"CHANGE_THIS_DEVICE_SECRET_32B!"
PBKDF2_ROUNDS = 200_000
HEARTBEAT_TIMEOUT = 3.0


def default_output_root():
    """优先使用 D 盘；没有 D 盘时回退到当前用户的 Documents。"""
    drive_d = Path("D:/")
    if drive_d.exists():
        return drive_d / "SafeKey-Unlocked"
    documents = Path.home() / "Documents"
    return documents / "SafeKey-Unlocked"


def derive_key(salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", DEVICE_SECRET, salt, PBKDF2_ROUNDS, 32)


def make_vault(source: Path, destination: Path) -> None:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError("源路径必须是文件夹")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
        temp_zip = Path(handle.name)
    try:
        with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in source.rglob("*"):
                if item.is_symlink():
                    raise ValueError("源文件夹不支持符号链接")
                if item.is_file():
                    zf.write(item, item.relative_to(source).as_posix())
        plaintext = temp_zip.read_bytes()
        encrypted = AESGCM(derive_key(salt)).encrypt(nonce, plaintext, MAGIC)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # 先写临时文件，再替换目标，避免程序中断留下半个保险箱。
        staged = destination.with_name(destination.name + ".tmp")
        staged.write_bytes(MAGIC + salt + nonce + encrypted)
        staged.replace(destination)
    finally:
        temp_zip.unlink(missing_ok=True)


def unlock_vault(vault: Path, output_root: Path | None = None) -> Path:
    raw = vault.read_bytes()
    if len(raw) < 36 or raw[:8] not in (MAGIC_V1, MAGIC):
        raise ValueError("不是 SafeKey 保险箱文件")
    file_magic = raw[:8]
    salt, nonce, encrypted = raw[8:24], raw[24:36], raw[36:]
    plaintext = AESGCM(derive_key(salt)).decrypt(nonce, encrypted, file_magic)
    if output_root is None:
        out = Path(tempfile.mkdtemp(prefix="SafeKey-unlocked-"))
    else:
        output_root = output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        out = output_root / (vault.stem + "-unlocked")
        if out.exists():
            raise ValueError("解锁目录已存在，请先锁定并清理上一次的目录")
        out.mkdir()
    zip_path = out / ".payload.zip"
    try:
        zip_path.write_bytes(plaintext)
        with zipfile.ZipFile(zip_path) as zf:
            safe_extract(zf, out)
    finally:
        zip_path.unlink(missing_ok=True)
    return out


def verify_vault(vault: Path) -> tuple[int, int]:
    """验证保险箱认证标签和 ZIP 结构，返回文件数与解密数据大小。"""
    raw = vault.read_bytes()
    if len(raw) < 36 or raw[:8] not in (MAGIC_V1, MAGIC):
        raise ValueError("不是 SafeKey 保险箱文件")
    file_magic = raw[:8]
    salt, nonce, encrypted = raw[8:24], raw[24:36], raw[36:]
    plaintext = AESGCM(derive_key(salt)).decrypt(nonce, encrypted, file_magic)
    with zipfile.ZipFile(io.BytesIO(plaintext)) as zf:
        if zf.testzip() is not None:
            raise ValueError("保险箱 ZIP 数据损坏")
        return len(zf.infolist()), len(plaintext)


def relock_vault(unlocked_dir: Path, vault: Path) -> None:
    """将临时明文目录重新打包并加密，完成修改保存。"""
    if not unlocked_dir.is_dir():
        raise ValueError("临时目录不存在")
    make_vault(unlocked_dir, vault)


def safe_extract(zf: zipfile.ZipFile, destination: Path) -> None:
    """只解压到目标目录内部，拒绝路径穿越和符号链接。"""
    root = destination.resolve()
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("保险箱包含非法路径")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError("保险箱不支持符号链接")
        target = (root / relative).resolve()
        if target != root and root not in target.parents:
            raise ValueError("保险箱路径越界")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as source, target.open("wb") as sink:
            shutil.copyfileobj(source, sink)


class Device:
    def __init__(self, port_name: str):
        if serial is None:
            detail = "：%s" % SERIAL_IMPORT_ERROR if SERIAL_IMPORT_ERROR else ""
            raise RuntimeError("串口组件加载失败%s" % detail)
        # 课程现有串口 1 工程使用 2400bps，必须与单片机保持一致。
        self.port = serial.Serial(port_name, 2400, timeout=0.1)
        self.buffer = bytearray()
        self.last_alive = time.monotonic()
        self.authenticated = False
        self.ready = False

    def close(self):
        if self.port and self.port.is_open:
            self.port.close()

    def send_hello(self):
        self.port.write(FRAME_HELLO)

    def poll(self):
        data = self.port.read(self.port.in_waiting or 1)
        if data:
            self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 8:
            if self.buffer[:2] != b"SK":
                del self.buffer[0]
                continue
            frames.append(bytes(self.buffer[:8]))
            del self.buffer[:8]
        for frame in frames:
            if frame.startswith(b"SKRDY"):
                self.ready = True
            elif frame.startswith(b"SKOK"):
                self.authenticated = True
                self.last_alive = time.monotonic()
            elif frame.startswith(b"SKER") or frame.startswith(b"SKLK"):
                self.authenticated = False
            elif frame.startswith(b"SKALIVE"):
                self.last_alive = time.monotonic()
        if time.monotonic() - self.last_alive > HEARTBEAT_TIMEOUT:
            self.authenticated = False
        return frames


class SafeKeyApp:
    def __init__(self, root: Tk):
        self.root = root
        root.title("SafeKey V3 本地文件保险箱")
        root.geometry("920x720")
        self.device: Device | None = None
        self.unlocked_dir: Path | None = None
        self.unlocked_vault: Path | None = None
        self.unlocked_at = 0.0
        self.last_fingerprint = None
        self.dirty = False
        self.port_var = StringVar(value=self.detect_port())
        self.vault_var = StringVar()
        self.status_var = StringVar(value="未连接单片机")
        self.device_state_var = StringVar(value="设备：离线")
        self.vault_info_var = StringVar(value="保险箱：未选择")
        self.countdown_var = StringVar(value="自动锁定：--")
        self.temp_var = StringVar(value="")
        self.input_var = StringVar(value="尚未收到单片机输入")
        self.autolock_var = StringVar(value="300")
        self.output_root_var = StringVar(value=str(default_output_root()))
        self.log = None
        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        atexit.register(self.cleanup_unlocked_dir)
        self.root.after(300, self.tick)

    @staticmethod
    def detect_port() -> str:
        if list_ports is None:
            return "COM3"
        ports = list(list_ports.comports())
        for p in ports:
            if "CH340" in (p.description or "").upper() or "USB-SERIAL" in (p.description or "").upper():
                return p.device
        return ports[0].device if ports else "COM3"

    def build_ui(self):
        pad = {"padx": 10, "pady": 7}
        frm = ttk.Frame(self.root, padding=12); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="SafeKey V2 硬件密钥文件保险箱", font=("Microsoft YaHei", 16, "bold")).pack(anchor="w", **pad)
        row = ttk.Frame(frm); row.pack(fill="x", **pad)
        ttk.Label(row, text="串口").pack(side="left")
        ttk.Entry(row, textvariable=self.port_var, width=12).pack(side="left", padx=6)
        ttk.Button(row, text="连接", command=self.connect).pack(side="left")
        ttk.Button(row, text="断开", command=self.disconnect).pack(side="left", padx=6)
        status_box = ttk.LabelFrame(frm, text="安全状态", padding=8)
        status_box.pack(fill="x", **pad)
        ttk.Label(status_box, textvariable=self.status_var, font=("Microsoft YaHei", 11, "bold")).pack(anchor="w")
        ttk.Label(status_box, textvariable=self.device_state_var).pack(side="left", padx=(0, 24))
        ttk.Label(status_box, textvariable=self.countdown_var).pack(side="left")
        ttk.Label(frm, textvariable=self.vault_info_var, foreground="#475569").pack(anchor="w", **pad)
        ttk.Label(frm, text="单片机当前输入：", font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", **pad)
        ttk.Label(frm, textvariable=self.input_var, font=("Consolas", 16)).pack(anchor="w", **pad)
        ttk.Label(frm, text="串口调试日志：", font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", **pad)
        self.log = ScrolledText(frm, height=8, state="disabled")
        self.log.pack(fill="both", expand=True, **pad)
        row = ttk.Frame(frm); row.pack(fill="x", **pad)
        ttk.Label(row, text="保险箱文件").pack(side="left")
        ttk.Entry(row, textvariable=self.vault_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="选择", command=self.choose_vault).pack(side="left")
        ttk.Button(row, text="检查完整性", command=self.check_vault).pack(side="left", padx=6)
        ttk.Label(row, text="自动锁定(秒)").pack(side="left", padx=(12, 3))
        ttk.Entry(row, textvariable=self.autolock_var, width=7).pack(side="left")
        row = ttk.Frame(frm); row.pack(fill="x", **pad)
        ttk.Label(row, text="解锁到 D 盘目录").pack(side="left")
        ttk.Entry(row, textvariable=self.output_root_var).pack(side="left", fill="x", expand=True, padx=6)
        row = ttk.Frame(frm); row.pack(fill="x", **pad)
        ttk.Button(row, text="从文件夹创建保险箱", command=self.create_vault).pack(side="left")
        ttk.Button(row, text="解锁并打开临时目录", command=self.unlock).pack(side="left", padx=6)
        ttk.Button(row, text="打开临时目录", command=self.open_unlocked_dir).pack(side="left")
        ttk.Button(row, text="保存修改并锁定", command=self.save_and_lock).pack(side="left", padx=6)
        ttk.Button(row, text="立即锁定", command=lambda: self.lock(ask_save=True)).pack(side="left")
        ttk.Label(frm, textvariable=self.temp_var, wraplength=570).pack(anchor="w", **pad)
        ttk.Label(frm, text="操作：连接后，单片机按 K1 递增当前数字，K2 确认，K3 清空重输。连续失败 3 次锁定 30 秒。", wraplength=570).pack(anchor="w", **pad)

    def connect(self):
        try:
            self.disconnect()
            self.device = Device(self.port_var.get().strip())
            self.status_var.set("已连接，等待单片机认证。请在板上输入 6 位 PIN")
            self.device_state_var.set("设备：在线 / 等待认证")
            self.append_log(self.port_var.get().strip() + " 已打开，等待单片机复位完成")
            # 打开 CH340 可能触发单片机复位，延迟后再发握手，避免丢帧。
            self.root.after(800, self.send_hello)
        except Exception as exc:
            self.device = None
            messagebox.showerror("连接失败", str(exc))

    def disconnect(self):
        self.lock()
        if self.device:
            self.device.close()
            self.device = None
        self.status_var.set("未连接单片机")
        self.device_state_var.set("设备：离线")

    def send_hello(self):
        if self.device:
            try:
                self.device.send_hello()
                self.append_log("已发送握手：SKHLLO")
            except Exception as exc:
                self.append_log("发送握手失败：" + str(exc))

    def choose_vault(self):
        name = filedialog.askopenfilename(filetypes=[("SafeKey vault", "*.safevault"), ("全部文件", "*.*")])
        if name:
            self.vault_var.set(name)
            self.refresh_vault_info()

    def refresh_vault_info(self):
        try:
            count, size = verify_vault(Path(self.vault_var.get()))
            self.vault_info_var.set("保险箱：%s | %d 个条目 | 载荷 %d 字节" % (Path(self.vault_var.get()).name, count, size))
        except Exception:
            self.vault_info_var.set("保险箱：未选择或无法验证")

    def create_vault(self):
        source = filedialog.askdirectory(title="选择需要加密的文件夹")
        if not source: return
        dest = filedialog.asksaveasfilename(defaultextension=".safevault", filetypes=[("SafeKey vault", "*.safevault")])
        if not dest: return
        try:
            source_path, dest_path = Path(source).resolve(), Path(dest).resolve()
            make_vault(source_path, dest_path)
            self.vault_var.set(str(dest_path))
            self.refresh_vault_info()
            delete_source = messagebox.askyesno(
                "是否删除原文件夹",
                "保险箱已创建成功。是否删除原文件夹中的明文？\n\n"
                "建议先成功解锁验证后再删除。此操作不可由 SafeKey 恢复。",
            )
            if delete_source:
                if source_path == dest_path or source_path in dest_path.parents:
                    raise ValueError("保险箱文件位于原文件夹内部，已拒绝删除原文件夹")
                shutil.rmtree(source_path)
                messagebox.showinfo("完成", "保险箱已创建，原文件夹已删除")
            else:
                messagebox.showinfo("完成", "保险箱已创建，原文件夹保留")
        except Exception as exc: messagebox.showerror("创建失败", str(exc))

    def unlock(self):
        if not self.device or not self.device.authenticated:
            messagebox.showwarning("需要认证", "请先连接单片机并输入正确 PIN")
            return
        try:
            if self.unlocked_dir: self.lock()
            self.unlocked_vault = Path(self.vault_var.get()).resolve()
            self.unlocked_dir = unlock_vault(
                self.unlocked_vault, Path(self.output_root_var.get().strip())
            )
            self.unlocked_at = time.monotonic()
            self.last_fingerprint = self.directory_fingerprint(self.unlocked_dir)
            self.dirty = False
            self.temp_var.set("明文临时目录：" + str(self.unlocked_dir))
            self.status_var.set("已解锁。可打开临时目录修改文件，完成后点击‘保存修改并锁定’")
            self.device_state_var.set("设备：在线 / 已认证")
        except Exception as exc: messagebox.showerror("解锁失败", str(exc))

    def open_unlocked_dir(self):
        if not self.unlocked_dir or not self.unlocked_dir.exists():
            messagebox.showwarning("尚未解锁", "请先解锁保险箱")
            return
        if hasattr(os, "startfile"):
            os.startfile(str(self.unlocked_dir))
        else:
            webbrowser.open(self.unlocked_dir.as_uri())

    def check_vault(self):
        try:
            count, size = verify_vault(Path(self.vault_var.get()))
            self.refresh_vault_info()
            messagebox.showinfo("完整性检查通过", "认证标签有效\n条目数：%d\n解密载荷：%d 字节" % (count, size))
            self.append_log("保险箱完整性检查通过：%d 个条目" % count)
        except Exception as exc:
            messagebox.showerror("完整性检查失败", str(exc))
            self.append_log("保险箱完整性检查失败：" + str(exc))

    @staticmethod
    def directory_fingerprint(directory: Path):
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
            messagebox.showwarning("尚未解锁", "请先解锁保险箱")
            return
        try:
            relock_vault(self.unlocked_dir, self.unlocked_vault)
            self.lock()
            self.status_var.set("修改已保存，保险箱已锁定")
            messagebox.showinfo("保存完成", "修改已重新加密保存，临时明文目录已清理")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def lock(self, ask_save=False):
        if ask_save and self.unlocked_dir and self.dirty:
            choice = messagebox.askyesnocancel("检测到未保存修改", "是否先保存修改再锁定？")
            if choice is None:
                return False
            if choice:
                try:
                    relock_vault(self.unlocked_dir, self.unlocked_vault)
                except Exception as exc:
                    messagebox.showerror("保存失败", str(exc))
                    return False
        self.cleanup_unlocked_dir()
        self.unlocked_vault = None
        self.unlocked_at = 0.0
        self.last_fingerprint = None
        self.dirty = False
        self.countdown_var.set("自动锁定：--")
        if self.device: self.device.authenticated = False
        return True

    def cleanup_unlocked_dir(self):
        if not self.unlocked_dir:
            return
        target = self.unlocked_dir
        self.unlocked_dir = None
        self.temp_var.set("")
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.append_log("临时明文目录清理失败：" + str(exc))

    def close_app(self):
        self.lock()
        if self.device:
            self.device.close()
            self.device = None
        self.root.destroy()

    def tick(self):
        if self.device:
            try:
                for frame in self.device.poll():
                    self.handle_frame(frame)
                if self.unlocked_dir:
                    current = self.directory_fingerprint(self.unlocked_dir)
                    if current != self.last_fingerprint:
                        self.dirty = True
                        self.last_fingerprint = current
                        self.temp_var.set("临时目录已修改：请保存修改后再锁定")
                    try:
                        timeout = max(10, int(self.autolock_var.get()))
                    except ValueError:
                        timeout = 300
                    remaining = max(0, timeout - int(time.monotonic() - self.unlocked_at))
                    self.countdown_var.set("自动锁定：%d 秒" % remaining)
                    if time.monotonic() - self.unlocked_at >= timeout:
                        self.lock()
                        self.status_var.set("达到自动锁定时间，保险箱已锁定")
                        self.append_log("达到自动锁定时间，已清理临时明文目录")
                else:
                    self.countdown_var.set("自动锁定：--")
                if self.device.authenticated and self.unlocked_dir is None:
                    self.status_var.set("认证成功，可选择保险箱并解锁")
                elif not self.device.authenticated and self.unlocked_dir:
                    self.lock(); self.status_var.set("硬件密钥离线或认证失效，保险箱已锁定")
            except Exception:
                self.lock(); self.status_var.set("单片机已断开，保险箱已锁定")
        self.root.after(300, self.tick)

    def append_log(self, message: str):
        if self.log is None: return
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def handle_frame(self, frame: bytes):
        if frame.startswith(b"SKRDY"):
            self.device_state_var.set("设备：在线 / 等待认证")
            self.status_var.set("单片机已准备，请输入 6 位 PIN")
            self.input_var.set("------  当前位 0")
            self.append_log("收到 SKRDY，开始输入")
        elif frame.startswith(b"SKKY"):
            pos, confirmed = frame[4], frame[6]
            self.input_var.set("已输入 " + str(pos) + "/6，当前数字已隐藏")
            self.append_log("按键输入：位置 %d%s" % (pos, "（已确认）" if confirmed else ""))
        elif frame.startswith(b"SKCL"):
            self.input_var.set("------  已清空")
            self.append_log("K3 清空输入")
        elif frame.startswith(b"SKBK"):
            self.input_var.set("已回退到第 %d 位，当前数字已隐藏" % frame[4])
            self.append_log("K3 回退到位置 %d" % frame[4])
        elif frame.startswith(b"SKOK"):
            self.device_state_var.set("设备：在线 / 已认证")
            self.status_var.set("认证成功，可以解锁保险箱")
            self.input_var.set("认证成功")
            self.append_log("收到 SKOK，硬件认证成功")
        elif frame.startswith(b"SKER"):
            self.device_state_var.set("设备：在线 / PIN 错误")
            self.status_var.set("PIN 错误，还可继续尝试")
            self.input_var.set("认证失败")
            self.append_log("收到 SKER，第 %d 次失败" % frame[4])
        elif frame.startswith(b"SKLK"):
            self.device_state_var.set("设备：在线 / 暂时锁定")
            self.status_var.set("失败次数过多，单片机暂时锁定")
            self.input_var.set("已锁定 30 秒")
            self.append_log("收到 SKLK，进入暂时锁定")
        elif frame.startswith(b"SKALIVE"):
            if not self.device.authenticated:
                self.status_var.set("单片机在线，请输入 6 位 PIN")
            self.append_log("收到在线心跳")


def main():
    parser = argparse.ArgumentParser(description="SafeKey 本地文件保险箱")
    parser.add_argument("--create", nargs=2, metavar=("SOURCE_DIR", "VAULT_FILE"), help="创建保险箱")
    args = parser.parse_args()
    if args.create:
        make_vault(Path(args.create[0]), Path(args.create[1])); print("created", args.create[1]); return
    root = Tk(); SafeKeyApp(root); root.mainloop()


if __name__ == "__main__": main()
