# SafeKey V3

SafeKey 是一个基于 STC-B 学习板的本地文件保险箱课程项目。学习板负责通过 K1/K2/K3 输入并验证 PIN，Windows 客户端通过 CH340 串口接收认证结果，认证成功后才允许解锁本地保险箱。

> 本项目面向课程验收和本地实验，不是专业 USB 安全令牌，不应保护高价值数据或唯一备份。

## 给同学的最快使用方法

运行条件：Windows 10/11 64 位、STC-B 学习板、可传输数据的 USB 线。使用仓库中的成品 EXE 不需要安装 Python、Conda 或 PyQt。

1. 用 STC-ISP 将 `release\SafeKey_V1.hex` 下载到学习板。这个文件名沿用 V1，但固件与 V3 客户端兼容。
2. 连接学习板，确认设备管理器中出现 `USB-SERIAL CH340 (COMx)`。
3. 双击 `release\SafeKey_V3.exe`。
4. 点击“刷新串口”。程序会优先选择 CH340；不同电脑上的 COM 编号不同，不要照抄 COM12/COM13。
5. 点击“连接”，等待约 1 秒，然后在学习板上输入调试 PIN `123456`。
6. K1 调整当前数字，K2 确认并进入下一位，K3 回退一位。
7. 选择一个普通测试文件夹创建 `.safevault`。首次测试时，在删除原文件夹的询问中选择“否”。
8. 认证成功后选择保险箱并解锁。修改文件后点击“保存修改并锁定”。

默认解锁目录优先使用 `D:\SafeKey-Unlocked`；如果电脑没有 D 盘，程序会自动改用当前用户的 `Documents\SafeKey-Unlocked`。也可以在界面中自行修改。

## 主要功能

- 学习板输入 6 位 PIN，数码管实时显示当前输入。
- PIN 错误 3 次后锁定 30 秒。
- LED 和蜂鸣器反馈认证状态。
- 自动识别并优先选择 CH340 串口，通信参数为 2400 baud、8N1。
- PyQt6 Windows 图形界面，可直接运行单文件 EXE。
- AES-256-GCM 文件夹加密，随机 salt 和 nonce。
- 安全 ZIP 解压，拒绝路径穿越和符号链接。
- 保险箱完整性检查、修改后重新加密、临时文件原子替换。
- 设备断开、心跳超时或倒计时结束后自动锁定并清理解锁目录。
- 创建保险箱后由用户决定是否删除原文件夹。

## 固件烧录与编译

直接验收只需烧录 `release\SafeKey_V1.hex`。如需重新编译：

1. 使用 Keil C51/uVision 5 打开 `STC_Demo.uvproj`。
2. 目标芯片选择 `IAP15F2K61S2`。
3. 系统时钟保持 `11.0592MHz`。
4. 编译后使用 STC-ISP 下载生成的 HEX，点击下载后让学习板重新上电。

PIN 定义位于 `source\safekey_main.c`：

```c
#define PIN_CODE "123456"
```

修改 PIN 后必须重新编译并烧录固件。

## 从源码运行 Windows 客户端

推荐使用 Python 3.11 的独立 Conda 环境：

```powershell
conda create -n safekey-build python=3.11 pip -y
conda activate safekey-build
python -m pip install -r host\requirements-build.txt
python host\safe_key_qt.py
```

客户端依赖版本固定在 `host\requirements-build.txt`，减少不同电脑上 PyQt、cryptography 和 PyInstaller 的二进制兼容问题。

## 重新生成 EXE

激活已安装依赖的环境后，在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

脚本优先使用当前激活的 Conda 环境，也兼容默认位置的 Miniconda、Anaconda 或已经正确安装依赖的系统 Python。生成结果位于 `dist\SafeKey_V3.exe`。

构建完成后可运行内置自检。退出码 `0` 表示打包后的 Qt、pyserial、ctypes/ffi、COM 枚举和 AES-GCM 均可加载：

```powershell
$result = Start-Process .\dist\SafeKey_V3.exe -ArgumentList '--self-test' -Wait -PassThru
$result.ExitCode
```

运行主机端回归测试：

```powershell
cd host
python -m unittest test_safe_key.py
```

测试覆盖 Unicode/子目录加解密、恶意 ZIP 路径拦截、修改后重新加密和密文篡改检测。

## 常见问题

### 串口列表中没有 CH340

- 检查 USB 线是否支持数据传输。
- 在设备管理器中检查是否存在黄色感叹号；必要时安装 CH340/CH341 驱动。
- 关闭 STC-ISP、串口助手和其他占用串口的软件，再点击“刷新串口”。
- COM 编号由每台电脑动态分配，只选择描述含 `CH340` 或 `USB-SERIAL` 的端口。

### 点击连接后没有收到 SKRDY

- 确认烧录的是本仓库提供的 SafeKey 固件。
- 确认客户端和固件都使用 2400 baud。
- 点击连接后等待约 1 秒；打开 CH340 可能使学习板复位。
- 尝试重新插拔学习板，然后刷新串口并连接。

### EXE 被占用或打不开

- 先在任务管理器中结束旧的 `SafeKey_V3.exe`，再替换文件。
- 确保使用 `release\SafeKey_V3.exe`，不要运行旧压缩包中的版本。
- 如需反馈问题，请截图完整错误信息，并附上 Windows 版本及 CH340 对应的 COM 编号。

## 项目结构

- `source\safekey_main.c`：单片机固件源码。
- `STC_Demo.uvproj`：Keil C51 工程。
- `source\STCBSP_V3.6.LIB`、`inc\`：课程标准 BSP。
- `host\safe_key.py`：加密、保险箱和串口核心逻辑。
- `host\safe_key_qt.py`：V3 图形界面与运行时自检入口。
- `host\test_safe_key.py`：主机端回归测试。
- `docs\PROTOCOL.md`：串口协议。
- `release\SafeKey_V1.hex`：可直接烧录的固件。
- `release\SafeKey_V3.exe`：可直接运行的 Windows 64 位客户端。

## 安全边界与后续方向

当前固件返回固定的认证成功帧，设备密钥也属于课程演示实现，因此仍存在串口重放和主机端逆向风险。后续可升级为随机挑战值的 HMAC-SHA256 挑战—响应认证、让 PIN 参与密钥派生，并为每块学习板生成独立密钥。

## License

本项目使用 MIT License，见 `LICENSE`。
