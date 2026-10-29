# 桌面材料与对话工作区

2026-10-29。当前桌面继续使用 PySide6/QML 和 Qt Quick Controls Material，以“暖纸与墨迹”tokens、内置中日文字体与原创插画图标替换原紫色 MD3 外观。它是现有桌面的重构，不是新增前端技术栈。目标稿见[总体布局](../product/UI_LAYOUT_DESIGN.md)，本轮离线和打包结果见[集成检查](../validation/engineering/WORKSPACE_INTEGRATION_2026-10-29.md)。

## 页面与状态

- 紧凑侧栏按材料组织多段对话，可收起；材料库、导入、范围核对、新对话和设置在主区切换。
- `DesktopWorkspaceController` 管理浏览材料、路由、原文视图和每线程临时编辑状态；学习记录仍由 Workbench/SQLite 管理。浏览其他材料或设置不替换正在对话的线程。
- 导入先保存材料与规范化原文；文本/Markdown、字幕及 EPUB 的可用结构映射为稳定字符范围。来源定位不额外调用模型。
- 每条线程保存独立草稿、编辑位置和原文指向；新对话可选择材料和已有练习偏好。结束会话和浏览页面是不同操作。
- 设置按类别分组，保留外观、学习、模型服务、本地语音及计算配置；语音模型库仍使用已有下载、测速和候选管理逻辑。

## 原文对照

原文按需展开，章节选择建立讨论范围；单击段落或拖选文字直接聚焦，清除细选回到章节。支持查找、键盘选择、原生复制和长文分块加载。Python 字符位置与 Qt UTF-16 位置显式转换，避免 emoji 拆开或中日文偏移。

发送时冻结来源版本、已读边界和精确选区，消息可回看当时来源；回看历史来源不会改变当前指向。“发送 A 后改选 B，再失败重试”沿用 A，新草稿和当前 B 保留。确认和回复重试仍走 Workbench 的统一事务入口。

## 资源和运行

两份 Noto Serif SC/JP 字体与 OFL 许可位于 `qml/assets/fonts/`，启动时显式加载。原创图标及来源记录位于 `qml/assets/illustrated/`，细线 SVG 用于窗口与导航操作。资源通过 `pyproject.toml` 随 wheel 分发，基础安装不访问在线字体。

按 [README](../../README.md) 启动。检查安装包时：

```powershell
uv build --wheel --out-dir build/package-check
$linguaWheel = Get-ChildItem build/package-check/*.whl | Sort-Object LastWriteTime -Descending | Select-Object -First 1
.venv\Scripts\python.exe scripts/check_wheel_resources.py $linguaWheel.FullName
```

本次 QML 重构保留原 Qt 分轮录音/朗读入口，没有连接新的 `VoiceSessionCoordinator`。持续麦克风、VAD/AEC、自然插话、真人设备与最终视觉验收均不能由离屏测试替代。
