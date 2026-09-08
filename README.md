# SafeKey V1

SafeKey 是一个基于 STC-B 学习板的本地文件保险箱课程项目。单片机通过 K1/K2/K3 输入 PIN，经 CH340 串口向 Windows 主机报告认证结果，主机再解密指定的本地文件保险箱。

> V1 是可运行的课程原型，不是专业 USB 安全令牌。当前版本使用固定的演示设备密钥，V2 计划升级为挑战-响应认证。

## Features

- IAP15F2K61S2 单片机输入 6 位 PIN
- 数码管显示当前输入数字和位置
- LED、蜂鸣器显示认证状态
- CH340 USB 转串口通信
- Windows Tkinter 主机程序
- AES-256-GCM 文件夹加密
- 失败 3 次后暂时锁定 30 秒
- 单片机断开或心跳超时后自动删除临时明文目录
- 支持普通文件和子目录

## Repository layout

- `source/safekey_main.c`：单片机固件源码
- `STC_Demo.uvproj`：Keil C51 工程
- `source/STCBSP_V3.6.LIB`：课程标准 BSP 库
- `inc/`：课程 BSP 头文件
- `host/safe_key.py`：Windows 主机端 GUI 和保险箱程序
- `host/requirements.txt`：主机端依赖
- `release/SafeKey_V1.hex`：已编译的 V1 固件
- `docs/PROTOCOL.md`：串口协议说明

## Build firmware

1. 使用 Keil C51 打开 `STC_Demo.uvproj`。
2. 确认目标芯片为 `IAP15F2K61S2`，系统时钟为 `11.0592MHz`。
3. 编译工程，生成 `output/BSP_Demo.hex`。
4. 使用 STC-ISP 下载到学习板。

调试阶段 PIN 是 `123456`。修改 PIN 后必须重新编译并重新下载固件。

## Pin input

- K1 让当前数字加 1。
- K2 确认当前数字。
- K3 清空并重新输入。
- 单片机上电后即可接受 PIN；主机连接时会发送握手并清空当前输入。

## Run the Windows host

在 `host` 目录执行：

```text
python -m pip install -r requirements.txt
python safe_key.py
```

连接 CH340 对应的 COM 口，当前测试端口为 `COM12`。串口速率为 `2400bps`。先选择一个普通文件夹创建 `.safevault`，再输入正确 PIN，选择保险箱并解锁。程序把明文解压到临时目录。单片机断开、心跳超过 3 秒未收到或点击“立即锁定”后，程序删除该临时目录。

主机程序窗口中部的“串口调试日志”会显示握手、每次按键、认证成功和失败消息。点击“连接”后，至少应看到“COM12 已打开”和“已发送握手：SKHLLO”；收到单片机回应后会看到“收到 SKRDY，开始输入”。

## Create a vault from the command line

```text
python safe_key.py --create D:\\资料 D:\\SafeKey\\资料.safevault
```

## Security notes

主机程序使用 AES-256-GCM。每个保险箱使用随机 salt 和 nonce，并通过 PBKDF2-HMAC-SHA256 派生 AES 密钥。当前 PIN 负责控制单片机是否返回认证成功，但没有直接参与文件密钥派生；设备密钥仍是课程演示代码中的固定值。因此本项目适合课程演示和本地实验，不应保护高价值或敏感数据。

## V2 roadmap

- 基于随机挑战值的 HMAC-SHA256 挑战-响应认证
- 让 PIN 参与文件密钥派生
- 每个设备独立密钥并保存到 EEPROM
- 加密文件修改后的重新加密
- 更完整的保险箱元数据和恢复机制

## License

本项目使用 MIT License，见 `LICENSE`。
