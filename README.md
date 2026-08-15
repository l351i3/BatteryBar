# Battery Bar (罗技多设备动态电量监控版)

Battery Bar 是一个罗技外设电量监控与获取工具。

## 最新特性

- **动态设备发现 (完全摆脱硬编码)**：彻底移除旧版写死 PID、特定 Receiver、指定 Receiver 槽位和硬编码 Feature Index 的实现。
- **支持 Bolt & Unifying 罗技接收器多槽位多设备**：自动扫描槽位 `1 ~ 6` 的所有连接设备。
- **动态 Root Feature 寻址**：通过罗技 HID++ 2.0 协议的 Root Feature (`0x0000`)，动态获取 `0x1004` (电池状态)、`0x0005` (设备名称)、`0x0003` (设备信息) 的 Feature Index，兼容任意罗技无线设备。
- **精确读取**：使用 `0x1004` Feature 的 **Function 1** 读取准确电量百分比，避免读取 Function 0 状态字节导致的电量误差。
- **按物理接收器去重**：自动过滤因不同 Usage Page 产生的重复 HID 路径。

## 项目结构

```text
BatteryBar/
├── hidpp_provider.py         # 动态罗技 HID++ 协议及设备电量读取提供者
├── classifier.py             # 罗技外设类型分类器
├── models.py                 # 电量设备、分类及状态数据结构
└── tests/
    └── test_hidpp_provider.py # 动态模拟测试套件
```

## 测试与验证

项目包含完善的单元测试。您可以通过以下命令运行测试：

```bash
PYTHONPATH=. python3 -m unittest tests/test_hidpp_provider.py
```
