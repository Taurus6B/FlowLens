"""FlowLens（流量镜）—— 本机网络流量按应用统计的桌面工具。

模块划分：
    app.core      配置、数据模型、工具函数
    app.storage   数据存储（SQLite 持久化）
    app.collector 流量采集（ETW / 估算 / 演示）
    app.stats     统计与报表（聚合、导出）
    app.ui        界面（PySide6）
"""

__version__ = "1.0.0"
__app_name__ = "FlowLens"
__app_name_cn__ = "流量镜"
