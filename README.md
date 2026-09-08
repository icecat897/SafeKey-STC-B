# SafeKey V3

SafeKey 是一个基于 STC-B 学习板的本地文件保险箱课程项目。单片机通过 K1/K2/K3 输入 PIN，经 CH340 串口向 Windows 主机报告认证结果，主机再解密指定的本地文件保险箱。

> V3 是面向课程验收的完整桌面版本，不是专业 USB 安全令牌。当前版本仍使用固定的演示设备密钥，后续可升级为挑战-响应认证。

## Features

- IAP15F2K61S2 单片机输入 6 位 PIN
- 数码管显示当前输入数字和位置
- LED、蜂鸣器显示认证状态
- CH340 USB 转串口通信
- Windows PyQt6 图形主机程序
- AES-256-GCM 文件夹加密
- 失败 3 次后暂时锁定 30 秒
- 单片机断开或心跳超时后自动删除临时明文目录
- PIN 输入默认脱敏显示
- 解锁时拒绝路径穿越和符号链接
- 主机端提供保险箱回归测试
- 支持解锁后修改文件并重新加密保存
- 保险箱写入采用临时文件原子替换，降低中断损坏风险
- 支持保险箱完整性检查和可配置自动锁定
- 图形界面显示设备、保险箱和自动锁定状态
- 可直接打包为 Windows EXE，无需打开终端运行
- 支持普通文件和子目录

## Repository layout

- `source/safekey_main.c`：单片机固件源码
- `STC_Demo.uvproj`：Keil C51 工程
- `source/STCBSP_V3.6.LIB`：课程标准 BSP 库
- `inc/`：课程 BSP 头文件
- `host/safe_key.py`：保险箱、加密和串口核心逻辑
- `host/safe_key_qt.py`：V3 Windows 图形界面入口
- `host/requirements.txt`：主机端依赖
- `host/requirements-build.txt`：EXE 构建依赖
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
- K3 回退到上一位；在第 0 位时将当前数字归零。
- 单片机上电后即可接受 PIN；主机连接时会发送握手并清空当前输入。

## Run the Windows host

在 `host` 目录执行：

```text
python -m pip install -r requirements-build.txt
python safe_key_qt.py
```

运行主机端测试：

```text
python -m unittest test_safe_key.py
```

生成 Windows EXE 时建议使用独立的 Conda 环境，避免系统 Python、Tcl/Tk 或其他软件的 DLL 污染打包结果：

```text
conda create -n safekey-build python=3.11 pip -y
conda activate safekey-build
python -m pip install -r host\requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

成品生成在 `dist\SafeKey_V3.exe`。仓库已提供可直接运行的 `release\SafeKey_V3.exe`，用户电脑无需安装 Python。首次运行仍需连接学习板并选择正确 COM 口。

解锁后可以点击“打开解锁目录”修改文件，完成后点击“保存修改并锁定”。默认解锁目录为 D 盘的 `SafeKey-Unlocked`，不再使用系统临时目录；保险箱格式升级为 `SAFEKEY2`，仍兼容读取 V1 文件。

创建保险箱成功后，程序会询问是否删除原文件夹。选择“是”才会删除，选择“否”则保留原文件夹。建议首次验证时选择“否”，确认保险箱能够成功解锁后再删除明文副本。

“检查完整性”会验证 AES-GCM 认证标签和 ZIP 结构；“自动锁定(秒)”默认 300 秒，测试时可以设置为 10 秒。临时目录发生修改后，界面会提示保存修改。

连接 CH340 对应的 COM 口，串口速率为 `2400bps`。先选择一个普通文件夹创建 `.safevault`，再输入正确 PIN，选择保险箱并解锁。程序默认把明文解锁到 D 盘目录。单片机断开、心跳超过 3 秒未收到、达到自动锁定时间或点击“立即锁定”后，程序删除该解锁目录。

主机程序窗口中部的“串口调试日志”会显示握手、每次按键、认证成功和失败消息。点击“连接”后，至少应看到“COM12 已打开”和“已发送握手：SKHLLO”；收到单片机回应后会看到“收到 SKRDY，开始输入”。

## Create a vault from the command line

```text
python safe_key.py --create D:\\资料 D:\\SafeKey\\资料.safevault
```

## Security notes

主机程序使用 AES-256-GCM。每个保险箱使用随机 salt 和 nonce，并通过 PBKDF2-HMAC-SHA256 派生 AES 密钥。当前 PIN 负责控制单片机是否返回认证成功，但没有直接参与文件密钥派生；设备密钥仍是课程演示代码中的固定值。因此本项目适合课程演示和本地实验，不应保护高价值或敏感数据。

## Security boundary

V3 适合课程验收和本地实验，不适合保护高价值或唯一备份数据。当前设备密钥仍由主机程序管理，固定 `SKOK` 仍然存在重放风险；V3 的重点是可用性、文件安全处理和可验证的异常行为。

## Roadmap

- 基于随机挑战值的 HMAC-SHA256 挑战-响应认证
- 让 PIN 参与文件密钥派生
- 每个设备独立密钥并保存到 EEPROM
- 加密文件修改后的重新加密
- 更完整的保险箱元数据和恢复机制

## License

本项目使用 MIT License，见 `LICENSE`。
