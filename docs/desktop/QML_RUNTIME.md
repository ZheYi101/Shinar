# QML Runtime 运行要求

## Python 依赖

桌面依赖固定 `PySide6==6.11.1`，默认 Qt Quick Controls Material 不需要额外 QML 安装：

```powershell
uv sync --extra desktop
```

Kirigami 不是项目通过 `pip install kirigami` 获取的普通 Python 包。它是 Qt 能发现的 `org.kde.kirigami` QML module，必须和 PySide6 使用兼容的 Qt 主版本。

## Windows 开发

当前默认壳使用自绘 MD3 标题栏，通过 `Qt.FramelessWindowHint` 移除原生 Windows 顶栏。窗口拖动与边缘缩放分别调用 Qt `startSystemMove` / `startSystemResize`；位置、正常尺寸、最大化状态保存在独立 `Shinar/Window` QSettings 中，恢复时校验可用屏幕范围。支持 Alt+F10 最大化/恢复、Alt+F4 关闭。宽窗口仅“材料 / 对话”为主入口，复盘和设置在侧栏底部及“更多”菜单；紧凑窗口也可从“更多”访问。

本阶段默认纯文本，不要求 STT/TTS 配置。可编辑草稿通过 Ctrl+Enter 发送；前台流式回复与后台参考准备分别显示状态。只在语音服务配置齐全时显示原有录音入口。

可在不展示任何窗口、不读取 `.env` 或用户学习数据的条件下，核对真实 Windows HWND 样式：

```powershell
uv run python scripts/check_desktop_window.py
```

2026-10-24 本机结果为 `platform=windows, visible=false, win32_style=0x860b0000, native_caption=false, device_pixel_ratio=1.0`。该检查仅证明原生标题栏已移除；物理鼠标拖动、Windows Snap、跨 DPI / 多屏移动仍需桌面验收。offscreen Qt Test 的窗口控制、恢复和缩放转交检查不能替代实际操作系统交互。

UI 方案、参考源码和本轮失败修复记录见 [UI_SURFACE_PLAN](../product/UI_SURFACE_PLAN.md)；唯一项目状态表见 [ROADMAP](../planning/ROADMAP.md)。

当前默认加载 `MainFallback.qml` 的 Qt ApplicationWindow 和统一 MD3 页面。只有明确配置 `SHINAR_KIRIGAMI_MODE=on` 并具备兼容 runtime 才使用 Kirigami 壳；两个壳共享材料、对话、复盘、设置页面和 ViewModel。普通 Windows 运行无需安装 Craft。以下步骤只供可选 Kirigami 环境使用。

Windows 上，Craft 安装的 Kirigami 原生插件不能直接混用到 PyPI PySide6 wheel 的 Qt 进程中。即使两侧 Qt 都显示为 6.11.1，二进制构建来源不同仍可能在加载 `Kirigamiplugin.dll` 时触发 Windows `0xc0000139`。因此默认 `auto` 模式会拒绝把 `C:\CraftRoot\qml` 的插件加载进 PyPI PySide6，保证桌面端可以稳定使用 fallback 启动。不要通过修改全局 `PATH` 强行将 `C:\CraftRoot\bin` 放在 PySide6 前面。

参考：[Kirigami Windows Setup](https://develop.kde.org/docs/getting-started/kirigami/platforms-windows/)。

### 推荐安装步骤

KDE 官方 Windows 开发文档推荐使用 Craft。建议准备：

- Python 3.12 或 3.13，单独供 Craft 使用；当前项目的 Python 3.14 不建议作为 Craft bootstrap 解释器。
- Visual Studio 2022 的 `Desktop development with C++` 工作负载。
- Windows PowerShell，不要使用 PowerShell ISE。
- Windows Developer Mode，以便 Craft 更快地处理符号链接和解压。

先以普通或管理员 PowerShell 执行 KDE 官方 bootstrap：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
iex ((New-Object Net.WebClient).DownloadString('https://invent.kde.org/packaging/craft/-/raw/master/setup/install_craft.ps1'))
```

安装完成后，使用项目脚本安装 KDE blueprints、Kirigami runtime 并发现 runtime：

```powershell
.\scripts\setup_kirigami_windows.ps1 -InstallRuntime
uv sync --extra desktop
uv run python -c "from shinar.desktop.app import kirigami_runtime_available; print(kirigami_runtime_available())"
uv run shinar-desktop --mock
```

只检查“进程能创建 Qt 应用、ViewModel 和 QML 页面”而不保持窗口运行时，可以使用：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run shinar-desktop --mock --smoke
```

脚本默认使用 `C:\CraftRoot`，会搜索实际的 `org\kde\kirigami\qmldir` 文件，并把其 import root 写入当前用户的 `QML2_IMPORT_PATH` 和 `QML_IMPORT_PATH`。这一步完成的是 KDE runtime 的安装与发现；要在 Windows 上使用正式 Kirigami 页面，Python binding 和 Qt runtime 也必须来自同一套 Qt 分发。

当前已验证的稳定本地命令是：

```powershell
uv run shinar-desktop --mock
```

它会使用 Qt Quick Controls fallback，不会加载不兼容的 Craft DLL。需要检查当前选择的页面时，可以运行：

```powershell
uv run python -c "from shinar.desktop.app import kirigami_runtime_available, kirigami_runtime_usable; print(kirigami_runtime_available(), kirigami_runtime_usable())"
```

`True False` 表示 Craft Kirigami 已安装，但当前 PyPI PySide6 不能安全加载它，这是预期保护行为。`SHINAR_KIRIGAMI_MODE=on` 只用于已经确认 Qt/PySide6/Kirigami 来自同一分发的运行环境；不要把它用于目前的 Craft + PyPI PySide6 组合。

如果 Craft 已经创建了 `C:\CraftRoot\craft-tmp`，但脚本提示未安装，说明是 Craft bootstrap 的新目录布局，脚本会自动识别。你的 PySide6 来自 MSVC Qt，因此 Craft 配置必须使用 `windows-cl-msvc2022-x86_64`，不能使用 `windows-gcc-x86_64`。修复已有配置后再安装：

```powershell
.\scripts\setup_kirigami_windows.ps1 -RepairSettings
.\scripts\setup_kirigami_windows.ps1 -InstallRuntime
```

首次安装会先准备 MSYS2、Craft 和 KDE blueprint，可能需要较长时间。若输出
`failed retrieving file ... from mirror.msys2.org`、`Operation too slow` 或
`Craft failed while installing dev-utils/msys-base`，这是下载镜像超时，不代表配置错误。
直接重新执行同一条 `-InstallRuntime` 命令即可，Craft 会复用已经下载和安装成功的缓存；不要
重新改 ABI，也不要删除 `C:\CraftRoot`。如果连续多次失败，再在 MSYS2/Craft 的 mirrorlist
中选择可访问的镜像后重试。

`-RepairSettings` 只修改 `C:\CraftRoot\etc\CraftSettings.ini` 中的 ABI 和 Python 路径，不删除 Craft 文件。它会从 `py -3.12` 自动获取 Python 3.12 的实际安装路径。

如果只想设置已有 Craft runtime 的环境：

```powershell
.\scripts\setup_kirigami_windows.ps1
```

脚本不会提交密钥，也不会修改项目 Python 虚拟环境以外的 Shinar 配置。

## Linux

默认使用随 PySide6 分发的 Qt Material。选择 Kirigami 时使用发行版提供的与 PySide6/Qt6 匹配的 runtime。

## Android

Android 暂不进入 Windows 首版交付。后续移动验证先确认 module、QML 资源和 Python 入口能被打包。普通 pytest 不负责 Android 安装和启动，窄窗口通过不代表移动包可用。

移动模式可用 Qt 官方教程中的环境变量进行本地检查：

```powershell
$env:QT_QUICK_CONTROLS_MOBILE = "1"
uv run shinar-desktop --mock
```

本地自动 smoke test 会分别以桌面 `1180x780` 和手机 `360x740`、`412x915` 尺寸加载 QML。它验证页面可创建、可调整尺寸且不会依赖真实 API；不等价于 Android 包已经构建或真机已运行。

## 资源打包

QML 根文件、`pages/`、`components/`、`design/AppTheme.qml` 和 `qmldir`、Material Symbols SVG 和许可证通过 `setuptools.package-data` 随 wheel 分发。可以运行 `uv build --wheel --out-dir build/package-check` 检查资源。独立 Windows 安装器仍待增加平台打包配置，需包含 Qt Multimedia、Qt Material style 和相关插件；不能把 wheel 构建通过当作 exe 安装器已经可用。

构建后运行 `uv run python scripts/check_wheel_resources.py build/package-check/shinar-0.1.0-py3-none-any.whl`，检查全部资源并从 wheel 的隔离临时目录加载 QML，避免误用源码目录造成打包假通过。

2026-10-24 新候选验证通过：39 个 QML / SVG / 许可证资源齐全，隔离导入 wheel 内 `WindowController` 并加载隐藏窗口，确认三个窗口按钮、拖动区、边缘缩放句柄和 frameless flags。探针使用临时 SQLite 与两个临时 QSettings 文件，不读取 `.env`，不安装到全局环境。候选 SHA256 与首次选择器失败的修复记录见 [UI_SURFACE_PLAN](../product/UI_SURFACE_PLAN.md)。这仍是 wheel 资源与离屏加载验收，不等价于 Windows exe 安装器、物理拖动或跨 DPI 验收。
