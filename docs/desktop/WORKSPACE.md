# 桌面材料与对话工作区

2026-10-29。当前桌面继续使用 PySide6/QML 和 Qt Quick Controls Material，以“暖纸与墨迹”tokens、内置中日文字体与原创插画图标替换原紫色 MD3 外观。它是现有桌面的重构，不是新增前端技术栈。目标稿见[总体布局](../product/UI_LAYOUT_DESIGN.md)，本轮离线和打包结果见[集成检查](../validation/engineering/WORKSPACE_INTEGRATION_2026-10-29.md)。

随后逐页对照修订 3 进行了[浅色视觉复核](../validation/engineering/UI_VISUAL_REVIEW_2026-10-29.md)：统一实际可见控件尺寸、设置行与主题预览、左对齐侧栏、顶部单行聊天操作、顶部新对话表单和原文分区。根窗口仍使用 Material；纸墨叶控件以 Qt 自带 Basic 控件定制背景／内容／指示器，避免继承 Material 的内缩、浮动提示和开关形态。不升级 Qt、不引入新的样式框架。

## 页面与状态

- 紧凑侧栏按材料组织多段对话，可收起；材料库、导入、范围核对、新对话和设置在主区切换。
- `DesktopWorkspaceController` 管理浏览材料、路由、原文视图和每线程临时编辑状态；学习记录仍由 Workbench/SQLite 管理。浏览其他材料或设置不替换正在对话的线程。
- 导入先保存材料与规范化原文；文本/Markdown、字幕及 EPUB 的可用结构映射为稳定字符范围。来源定位不额外调用模型。
- 每条线程保存独立草稿、编辑位置和原文指向；新对话可选择材料和已有练习偏好。结束会话和浏览页面是不同操作。
- 设置按类别分组，保留外观、学习、模型服务、本地语音及计算配置；语音模型库仍使用已有下载、测速和候选管理逻辑。

本轮补齐结果见 [UI 实施记录](../validation/engineering/UI_IMPLEMENTATION_2026-10-29.md)。材料树通过 `list_session_summaries()` 查询真实标题、归属、轮数、时间和状态，不反序列化完整对话；相同投影不重新创建列表。开场想法保持草稿，开始线程不以它调用自定义题准备。范围确认前返回导入会保留名称、语言、文件和粘贴内容，重复继续仍复用材料；保存范围后才清理已完成的导入表单。

显示语言在外观分类中，学习母语在学习偏好中，使用独立 QSettings 字段。当前显示中文，Qt 翻译入口、系统语言解析与首次学习母语建议见[国际化说明](./I18N.md)。

## 原文对照

原文按需展开，章节选择建立讨论范围；单击段落或拖选文字直接聚焦，清除细选回到章节。支持查找、键盘选择、原生复制和长文分块加载。Python 字符位置与 Qt UTF-16 位置显式转换，避免 emoji 拆开或中日文偏移。

发送时冻结来源版本、已读边界和精确选区，消息可回看当时来源；回看历史来源不会改变当前指向。“发送 A 后改选 B，再失败重试”沿用 A，新草稿和当前 B 保留。确认和回复重试仍走 Workbench 的统一事务入口。

预览历史时直接完成一次新的选择，会退出预览并采用新指向；原消息快照不变。原文版本失效时仅显示原确认引文，不接受错误定位。原文、查找、导入采用独立请求身份，离开页面、切线程或进入失效历史预览后，旧加载不能回写当前视图。输入法仍在组合时 Ctrl+Enter 不提交。新线程从整体原文视图开始，不继承上一线程的章节或滚动位置。

## 资源和运行

两份 Noto Serif SC/JP 字体与 OFL 许可位于 `qml/assets/fonts/`，启动时显式加载。原创图标及来源记录位于 `qml/assets/illustrated/`，细线 SVG 用于窗口与导航操作。资源通过 `pyproject.toml` 随 wheel 分发，基础安装不访问在线字体。

按 [README](../../README.md) 启动。检查安装包时：

```powershell
uv build --wheel --out-dir build/package-check
$linguaWheel = Get-ChildItem build/package-check/*.whl | Sort-Object LastWriteTime -Descending | Select-Object -First 1
.venv\Scripts\python.exe scripts/check_wheel_resources.py $linguaWheel.FullName
```

2026-10-30 已通过独立桌面控制器接入 `VoiceSessionCoordinator`：结束录音自动提交、逐句朗读、停止朗读、逐轮重试和恢复。文字草稿独立保留；关闭原文、缩窗或换主题不清理音频。当前仍是分轮交互，连续麦克风、VAD/AEC、自然插话与真人设备另做。说明与证据见[语音指南](./VOICE.md)及[接线记录](../validation/engineering/VOICE_QML_2026-10-30.md)。
