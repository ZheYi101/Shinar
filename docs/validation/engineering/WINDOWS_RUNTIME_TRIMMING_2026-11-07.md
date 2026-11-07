# Windows 私有运行时裁剪

日期：2026-11-07。范围：0.1.3 Windows x64 发行物；缩小下载与安装文件占用，保留既有 API 设置、阅读器、语音、字体和非冻结模型环境机制。个人 `.env`、实际学习库、已安装应用与模型缓存未修改，付费模型调用为 0。

## 策略与边界

实现见 `scripts/windows_runtime.py`、`scripts/build_windows.py` 和 `packaging/windows/cleanup_runtime.py`。产品 Python import／实际绑定加载、QML import scanner 和普通／延迟 PE 导入决定保留的依赖闭包；Qt 的发布资源、Unicode 字体、软件图形回退与输入法／音频插件保留。删除开发工具、未使用绑定、`.debug` 资源、额外 Qt 语言数据、类型与编译头文件及缓存。`venv`、`ensurepip`、SQLite 和独立模型进程仍可用，未采用冻结 EXE 或更换 UI 技术。

实际清单记录于 `build/windows/build-xn0v_odl/pruning.json`。共移除 **4606 项文件、305129854 字节**，构建运行时从 954819190 字节降到 649689336 字节。主要节省：Qt 根目录工具／未用二进制约 87.2 MiB、调试资源约 77.2 MiB、额外翻译约 55.3 MiB、Python 支撑／缓存约 25.8 MiB、QML 开发和未用模块约 16.8 MiB、metatypes 约 14.5 MiB、插件约 11.9 MiB。保留组件的许可证、字体 OFL 与 Python 许可证随包存在；被完全移除的 Tcl/Tk 许可证不再分发。

Qt locale 保留 en-US／zh-CN／zh-TW／ja；界面翻译入口和显示语言／学习母语／目标语言分离不变。未来新增语言或 Qt 依赖须重新核对策略。实际发布依赖依据 [Qt WebEngine 分发说明](https://doc.qt.io/qt-6/qtwebengine-deploying.html) 和 [Qt for Python 部署说明](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)核对；这些文档不能代替本包验证。

安装器改用 LZMA2 normal。升级清理在成功复制新包后执行，只删除包内 `RUNTIME_LAYOUT.json` 的明确退役文件，按 Windows 路径与大小写规则保护当前保留项，拒绝绝对／越界路径；不递归清空运行时、用户目录或模型缓存。ZIP 使用者应解压到新目录，覆盖旧目录无法自动缩减旧文件。

## 工程证据

普通回归显式设置 `RUN_REAL_AI_TESTS=0`。

| 检查 | 已执行结果与本地 ignored 证据 |
| --- | --- |
| 全量回归 | **573 passed、10 skipped**，236.79 s；`build/windows-slim-full-tests.log` |
| 裁剪／升级边界 | 最终定向检查 **22 passed**，含真实 Windows PE 依赖闭包、损坏原生映像、Qt import 发现、构建目录限制、仅清理退役项及保留项的大小写保护；不将开发环境当作裁剪目标 |
| Ruff／diff | 构建时全库与新增清理脚本通过；最后对固定构建快照的源码及本次工具再检查通过，`build/windows-slim-snapshot-ruff.log`。本次负责文件的 `git diff --check` 通过。交付前当前工作区的另一任务修改出现 `semantic_preparation.py` E402 和 `openai_compatible.py` EOF 空行；未覆盖其修改，也未将其混入已验证包 |
| wheel | **137 项应用资源**与隔离 QML smoke 通过；`build/windows-slim-final-wheel-check.log`。wheel 不裁剪应用资源，裁剪只作用于私有运行时 |
| 跨组件 native 审计 | 除 Qt 外的包体 PE 导入未引用已退役 DLL；`build/windows-slim-native-audit.log` |
| 实际 ZIP／可见 QML | 含中文和空格的解压路径，API 目录下拉、加密保存、重新绑定、明暗主题及 360／600／800／1180／1440px 通过；Qt 合成 WAV 解码及真实 LiveKit APM 的 10 ms 帧处理通过；`build/windows/s13-visible/report.json` |
| 模型环境 bootstrap | 从裁剪版实际私有 Python 离线创建 venv，并在子解释器执行 `pip --version` 通过；同上报告，不下载模型或安装推理依赖 |
| 原型阅读器 | 裁剪原型在可见 Windows 窗口通过中英日、明暗、选区／发送／历史与私有 profile；`build/windows/slim0/reader/report.json`。最终 archive 的独立复验另记，原型不冒充最终包 |
| 最终包阅读器 | 实际 ZIP 中的私有 Python／Qt 在可见 Windows 窗口完成 **9 项检查**，中英日、明暗、Unicode、分栏／缩放／查找、选区／历史与私有 profile 通过；`build/windows/s13-reader/report.json` |
| 实际包缩放 | 首次未配置的独立目录分别以 **125%／150%** 缩放运行，进入服务页、读取模型下拉、保存与重载通过；`build/windows/s13-first-run/report.json`。人工查看最终明亮界面、窄窗下拉及阅读器截图 |
| 真实安装与升级 | 先将完整 0.1.2 安装到独立目录，再原地升级到 0.1.3。安装、已安装 EXE smoke、卸载均返回 **0**，退役文件剩余 **0**，所有保留文件存在；正常安装登记不变、外部测试数据保留、程序文件卸载后残留 **0**。清理在复制成功后完成且返回 0；`build/windows/s13u/report.json` |

构建快照目录：`build/windows/build-xn0v_odl`。原始完整 0.1.2 基线仍保留，安装／升级验证使用独立 Validation 登记和测试目录，不替换用户的正常安装。

## 最终产物与实际体积

| 指标 | 0.1.2 完整包 | 0.1.3 裁剪包 |
| --- | ---: | ---: |
| 安装器文件 | 312071641 字节（297.61 MiB） | 193421142 字节（184.46 MiB），减少约 38.0% |
| ZIP 解包的程序文件 | 955055785 字节（910.81 MiB） | 650962887 字节（620.81 MiB），减少约 31.8% |
| 独立实际安装／原地升级后文件 | 963656488 字节（919.01 MiB） | 662331766 字节（631.65 MiB），减少约 31.3% |

安装行包含 Inno 的卸载程序／追加卸载记录，因此大于 ZIP 内的程序文件总量。这里统计实际文件字节数，非 RAM、模型下载缓存或 NTFS 簇分配估计。

产物位于 `dist/windows/`：

- `LinguaLoop-0.1.3-windows-x64-setup.exe`：SHA256 `442890d2bfcacac72b37c7bd8e6194546d6dc2aaa34901bb967c72a4e021995f`。
- `LinguaLoop-0.1.3-windows-x64.zip`：267138526 字节；SHA256 `fc4a3d3723b86a2dfdf1e47a8e34df66ae141f30ee268cf09f8cfd14199dbca7`。

原型及中间包体的 workspace 清理被自动审批拒绝，故保留其目录和证据；未改用其他方式删除。该限制不涉及已通过的安装器升级清理，也未触及其他任务的构建目录、旧发行物或用户缓存。

## 验收限制

未执行干净 Windows 虚拟机矩阵、实际 GPU 推理或新的真人语音质量验收；合成音解码／APM 不等于麦克风、扬声器、STT/TTS、回声和插话均通过。新资产依旧在设置中显式准备，未使用缩小主包来宣称模型本身更小。发行物仍为未签名开发预览；WebEngine 主 DLL 本身约 195 MiB，是保留 EPUB 引擎时的主要固定成本。

对应 Decision 0042；使用及升级命令见 [Windows 分发指南](../../desktop/WINDOWS_DISTRIBUTION.md)。
