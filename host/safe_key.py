"""SafeKey Windows 主机程序

第一版课程原型：通过 CH340 串口等待单片机认证，再解密本地文件保险箱。
依赖：Python 3.9+、pyserial、cryptography。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import struct
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from tkinter import Tk, StringVar, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"SAFEKEY1"
FRAME_HELLO = b"SKHLLO\x00\x00"
DEVICE_SECRET = b"CHANGE_THIS_DEVICE_SECRET_32B!"
PBKDF2_ROUNDS = 200_000
HEARTBEAT_TIMEOUT = 3.0


def derive_key(salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", DEVICE_SECRET, salt, PBKDF2_ROUNDS, 32)


def make_vault(source: Path, destination: Path) -> None:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError("源路径必须是文件夹")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    temp_zip = Path(tempfile.mktemp(suffix=".zip"))
    try:
        with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in source.rglob("*"):
                if item.is_file():
                    zf.write(item, item.relative_to(source).as_posix())
        plaintext = temp_zip.read_bytes()
        encrypted = AESGCM(derive_key(salt)).encrypt(nonce, plaintext, MAGIC)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(MAGIC + salt + nonce + encrypted)
    finally:
        temp_zip.unlink(missing_ok=True)


def unlock_vault(vault: Path) -> Path:
    raw = vault.read_bytes()
    if len(raw) < len(MAGIC) + 28 or raw[:8] != MAGIC:
        raise ValueError("不是 SafeKey 保险箱文件")
    salt, nonce, encrypted = raw[8:24], raw[24:36], raw[36:]
    plaintext = AESGCM(derive_key(salt)).decrypt(nonce, encrypted, MAGIC)
    out = Path(tempfile.mkdtemp(prefix="SafeKey-unlocked-"))
    zip_path = out / ".payload.zip"
    try:
        zip_path.write_bytes(plaintext)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(out)
    finally:
        zip_path.unlink(missing_ok=True)
    return out


class Device:
    def __init__(self, port_name: str):
        if serial is None:
            raise RuntimeError("缺少 pyserial，请先运行: python -m pip install pyserial")
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
        root.title("SafeKey 本地文件保险箱")
        root.geometry("760x600")
        self.device: Device | None = None
        self.unlocked_dir: Path | None = None
        self.port_var = StringVar(value=self.detect_port())
        self.vault_var = StringVar()
        self.status_var = StringVar(value="未连接单片机")
        self.temp_var = StringVar(value="")
        self.input_var = StringVar(value="尚未收到单片机输入")
        self.log = None
        self.build_ui()
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
        ttk.Label(frm, text="SafeKey 硬件密钥文件保险箱", font=("Microsoft YaHei", 16, "bold")).pack(anchor="w", **pad)
        row = ttk.Frame(frm); row.pack(fill="x", **pad)
        ttk.Label(row, text="串口").pack(side="left")
        ttk.Entry(row, textvariable=self.port_var, width=12).pack(side="left", padx=6)
        ttk.Button(row, text="连接", command=self.connect).pack(side="left")
        ttk.Button(row, text="断开", command=self.disconnect).pack(side="left", padx=6)
        ttk.Label(frm, textvariable=self.status_var, foreground="#164e63").pack(anchor="w", **pad)
        ttk.Label(frm, text="单片机当前输入：", font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", **pad)
        ttk.Label(frm, textvariable=self.input_var, font=("Consolas", 16)).pack(anchor="w", **pad)
        ttk.Label(frm, text="串口调试日志：", font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", **pad)
        self.log = ScrolledText(frm, height=8, state="disabled")
        self.log.pack(fill="both", expand=True, **pad)
        row = ttk.Frame(frm); row.pack(fill="x", **pad)
        ttk.Label(row, text="保险箱文件").pack(side="left")
        ttk.Entry(row, textvariable=self.vault_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="选择", command=self.choose_vault).pack(side="left")
        row = ttk.Frame(frm); row.pack(fill="x", **pad)
        ttk.Button(row, text="从文件夹创建保险箱", command=self.create_vault).pack(side="left")
        ttk.Button(row, text="解锁并打开临时目录", command=self.unlock).pack(side="left", padx=6)
        ttk.Button(row, text="立即锁定", command=self.lock).pack(side="left")
        ttk.Label(frm, textvariable=self.temp_var, wraplength=570).pack(anchor="w", **pad)
        ttk.Label(frm, text="操作：连接后，单片机按 K1 递增当前数字，K2 确认，K3 清空重输。连续失败 3 次锁定 30 秒。", wraplength=570).pack(anchor="w", **pad)

    def connect(self):
        try:
            self.disconnect()
            self.device = Device(self.port_var.get().strip())
            self.status_var.set("已连接，等待单片机认证。请在板上输入 6 位 PIN")
            self.append_log("COM12 已打开，等待单片机复位完成")
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

    def send_hello(self):
        if self.device:
            try:
                self.device.send_hello()
                self.append_log("已发送握手：SKHLLO")
            except Exception as exc:
                self.append_log("发送握手失败：" + str(exc))

    def choose_vault(self):
        name = filedialog.askopenfilename(filetypes=[("SafeKey vault", "*.safevault"), ("全部文件", "*.*")])
        if name: self.vault_var.set(name)

    def create_vault(self):
        source = filedialog.askdirectory(title="选择需要加密的文件夹")
        if not source: return
        dest = filedialog.asksaveasfilename(defaultextension=".safevault", filetypes=[("SafeKey vault", "*.safevault")])
        if not dest: return
        try:
            make_vault(Path(source), Path(dest)); self.vault_var.set(dest)
            messagebox.showinfo("完成", "保险箱已创建。原文件夹保持不变，请自行确认保险箱可解锁后再处理明文副本。")
        except Exception as exc: messagebox.showerror("创建失败", str(exc))

    def unlock(self):
        if not self.device or not self.device.authenticated:
            messagebox.showwarning("需要认证", "请先连接单片机并输入正确 PIN")
            return
        try:
            if self.unlocked_dir: self.lock()
            self.unlocked_dir = unlock_vault(Path(self.vault_var.get()))
            self.temp_var.set("明文临时目录：" + str(self.unlocked_dir))
            self.status_var.set("已解锁。拔出单片机、超时或点击锁定后会删除临时明文目录")
        except Exception as exc: messagebox.showerror("解锁失败", str(exc))

    def lock(self):
        if self.unlocked_dir:
            shutil.rmtree(self.unlocked_dir, ignore_errors=True)
            self.unlocked_dir = None
            self.temp_var.set("")
        if self.device: self.device.authenticated = False

    def tick(self):
        if self.device:
            try:
                for frame in self.device.poll():
                    self.handle_frame(frame)
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
            self.status_var.set("单片机已准备，请输入 6 位 PIN")
            self.input_var.set("------  当前位 0")
            self.append_log("收到 SKRDY，开始输入")
        elif frame.startswith(b"SKKY"):
            pos, digit, confirmed = frame[4], frame[5], frame[6]
            self.input_var.set("已确认 " + str(pos) + "/6，当前数字 " + str(digit))
            self.append_log("按键输入：位置 %d，数字 %d%s" % (pos, digit, "（已确认）" if confirmed else ""))
        elif frame.startswith(b"SKCL"):
            self.input_var.set("------  已清空")
            self.append_log("K3 清空输入")
        elif frame.startswith(b"SKOK"):
            self.status_var.set("认证成功，可以解锁保险箱")
            self.input_var.set("认证成功")
            self.append_log("收到 SKOK，硬件认证成功")
        elif frame.startswith(b"SKER"):
            self.status_var.set("PIN 错误，还可继续尝试")
            self.input_var.set("认证失败")
            self.append_log("收到 SKER，第 %d 次失败" % frame[4])
        elif frame.startswith(b"SKLK"):
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
