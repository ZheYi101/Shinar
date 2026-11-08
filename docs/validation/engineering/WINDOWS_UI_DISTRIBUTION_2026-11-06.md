# Windows 图标、分发与对话使用体验验证

日期：2026-11-06。范围：用户要求补齐图标和 Windows 打包，随后要求按 Codex 对话界面的思路改善阅读、输入、侧栏及设置操作。
保留另一聊天正在进行的语音验收及提交工作；没有重启其窗口、修改个人 `.env`、运行模型下载或发起付费模型调用。

## 交付范围

- 原创灰绿／暖纸对话图标，SVG 母版、512px PNG 和 9 档 ICO；Qt 窗口与原生 EXE 使用同一身份。
- 私有 Python 3.12.13、锁定依赖、字体／QML／许可证随包分发；同时提供 ZIP 和 Inno 当前用户安装器。
- 对话使用 16px 无衬线正文、右侧用户消息、原生文字选择和悬停复制；合并输入框工具栏，相关语音状态按阶段显示。
- Enter／Ctrl+Enter 发送、Shift+Enter 换行；保留输入法保护、独立草稿、来源快照、重试与语音控制器。
- 底部侧栏只留设置，复习改从材料库、复盘和对话菜单进入。侧栏开关、导航、选择框、外观选项和开关统一悬停／按压／焦点反馈，支持减少动效。
- 设置内容宽度 720px，明确分类标题；深色基础配色移除旧紫色，继续保留待用户最终确认的状态。

主要实现位于 `desktop/qml/components/ConversationMessage.qml`、`SidebarItem.qml`、`MIconButton.qml`、
`pages/ConversationPage.qml`、`pages/SettingsPage.qml`、`design/AppTheme.qml`，以及
`desktop/shell/identity.py`、`desktop/packaged.py`、`packaging/windows/` 和构建／检查脚本。
契约及使用方式见[布局修订](../../product/UI_LAYOUT_DESIGN.md#2026-11-06-使用体验修订)、
[工作区](../../desktop/WORKSPACE.md)和[Windows 分发](../../desktop/WINDOWS_DISTRIBUTION.md)。

## 检查结果

| 对象 | 结果 | 证据范围 |
| --- | --- | --- |
| Ruff 与离线回归 | 440 passed、10 skipped；`RUN_REAL_AI_TESTS=0` | 包含架构、Qt、语音状态、输入法、来源与恢复回归；不含真实服务验收 |
| 新交互回归 | 消息长文在 360／800／1180px 换行、悬停点击复制、Enter／Shift+Enter、侧栏切换保留草稿、悬停／按压和减少动效 | `tests/desktop/test_desktop_comfort.py`，真实 QML 事件，Mock provider／合成音频 |
| 浅色页面 | 82 张截图，360／600／800／1180／1440px | `build/ui-comfort-final/report.json`，独立临时库，离屏 |
| 深色与缩放 | 34 张截图，360／1180px、150% Qt 缩放 | `build/ui-comfort-dark-150/report.json`，不修改 Windows 系统缩放 |
| wheel | 107 项资源、hash 与隔离加载检查通过 | `scripts/check_wheel_resources.py`，包含新 QML／SVG、应用图标、字体和许可证 |
| ZIP 迁移 | 中文＋空格目录启动通过；私有解释器、原生 EXE、9 档图标、两份 Noto 字体、明暗 QML 和 RTC／ORT 导入通过 | `build/windows/release-relocation-check/report.json`；无预装 Python 依赖 |
| 安装／卸载 | 安装、安装后离屏启动、卸载退出码均为 0；专用卸载登记清理、正常安装登记未改变、外部数据保留、残留程序文件 0 | `build/windows/release-installer-check/report.json`，使用 `/VALIDATE=1`，跳过正常快捷方式 |

源代码离屏截图保留了 Qt multimedia 的 FFmpeg 提示和 PySide6 系统字体目录缺失提示；
中日文内置字体显式加载，截图文字正常，未发现 QML 加载／绑定错误。私有分发运行时的启动输出检查通过。
这些是 Windows 主机上的离屏和自动交互证据，不冒充可见窗口人工视觉确认或真人语音验收。

最后的窄窗 Mock 标识调整后，14 项对话交互与连续语音回归再次通过；新版 wheel 的 107 项资源检查重新通过。

首轮卸载检查发现启动时生成的 Python bytecode 会留在程序目录，启动器改用 `-I -B` 后重新打包，
最终安装／卸载检查确认残留程序文件为 0。个人配置、学习库和语音缓存位于应用安装目录之外。

## 最终开发预览产物

路径：`dist/windows/`。程序包解压约 910 MiB，保留完整 Qt 运行时和依赖许可证，未通过裁剪模块缩小体积。

| 文件 | 字节 | SHA256 |
| --- | ---: | --- |
| `LinguaLoop-0.1.0-windows-x64-setup.exe` | 311574718 | `f93917448f98a8657bce8877a14486861b7bde5f77aa54fd033b722afcf49691` |
| `LinguaLoop-0.1.0-windows-x64.zip` | 358752693 | `4dc19f28c435cf5890e16e8492a528cd34fea844553e5d187ea7604ce107485a` |

`BUILD.json` 记录 Python 来源、wheel 和锁文件 hash；完整清单位于
`build/windows/build-3kyq6mgn/payload.json`。包体检查通过，未包含开发者凭据、学习数据库或调用日志。

## 未完成边界

产物是工作树开发预览快照，未代码签名；没有覆盖干净 Windows 系统矩阵、旧版程序文件被占用时的升级、
默认快捷方式的人工固定／解除固定，以及自动升级。连续语音及真人体验继续由独立任务验收。
当前运行窗口没有热更新，新界面和图标在后续启动时生效。
