# SafeKey V1 串口协议

串口参数：2400 baud，8 data bits，no parity，1 stop bit。

所有数据帧固定为 8 字节，使用 ASCII 命令和 0 填充。

| Direction | Frame | Meaning |
|---|---|---|
| Host -> device | `SKHLLO\\0\\0` | 握手 |
| Device -> host | `SKRDY\\0\\0\\0` | 设备准备好 |
| Device -> host | `SKKY pos digit flag 0` | 按键输入事件 |
| Device -> host | `SKCL\\0\\0\\0\\0` | 清空输入 |
| Device -> host | `SKOK\\0\\0\\0\\0` | PIN 正确 |
| Device -> host | `SKER count 0 0 0` | PIN 错误 |
| Device -> host | `SKLK 30 0 0 0` | 暂时锁定 |
| Device -> host | `SKALIVE\\0` | 在线心跳 |

V1 的 `SKOK` 是固定认证结果，不能抵抗串口重放。V2 应改为随机挑战-响应协议。
