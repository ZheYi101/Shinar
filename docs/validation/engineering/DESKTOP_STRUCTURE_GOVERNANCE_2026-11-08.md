# Shinar 桌面结构治理与审查修复

日期：2026-11-08。范围：桌面 Python 所有权、职责目录、离线测试与验证工具。分支 `codex/desktop-structure-governance`，只创建本地提交。

结论：计划内 6 项审查问题已关闭；完整离线回归、可见 Windows Mock、新 wheel 及隔离安装探针均通过。其余三个 QObject 门面的共享状态拆分按已确认边界保留为后续债务。

## 审查项与实现

| 项目 | 处理与证据 |
| --- | --- |
| 子目录、别名和动态私有访问漏检 | `tests/support/boundaries.py` 递归扫描；覆盖导入／赋值／注解别名、嵌套属性、私有导入和字符串 getattr/setattr；TYPE_CHECKING 不构成运行时环。`test_boundary_checker.py` 使用合成源码验证漏检情形 |
| Workspace 默认偏好兼容缺失 | 默认 ProductSettings("Workspace")，显式注入优先；旧 true、新 false／true 逐键优先级与写入隔离均用临时 INI 回归 |
| AI 设置读取私有存储 | 使用 Workbench.storage_path；provider 配置通过独立的公开只读副本读取 |
| 桌面读取 Workbench 私有会话材料 | 公开 session_material() 保留冻结范围；领域回归验证查询不改当前材料／会话 |
| 连续语音状态与准备混合、跨控制器私有依赖 | 单一 QObject，CallCoordinator／CallPreparation 两个普通状态所有者；CallSnapshot 不可变；CallRuntimePort 限定运行能力；公开 SpeechRoute／tts_available；对话展示沿用唯一入口 |
| 平铺目录、测试与验证脚本耦合 | 32 个生产模块迁入 6 个职责包，根目录只保留 3 个入口；22 个桌面测试文件迁入 tests/desktop；LangGraph 两个测试模块迁入 tests/engine；共享场景使用 tests/support 普通上下文管理器 |

原有侧栏对齐改动已先独立保存。QML、翻译、图标与阅读器资源目录保持原位，第三方文件及其 pin／哈希不变。删除已确认无引用的根目录零字节 `dict`，不清理忽略的缓存与旧构建记录。

## 所有权与失败规则

- CallCoordinator 唯一更新通话状态；CallPreparation 独立拥有任务取消事件、准备身份和扫描代际。准备成功不启动通话；准备运行中拒绝开通话。
- Qt 门面拥有资源适配器、设备、桥、后台进程引用和信号。普通协作者只持有明确的运行接口，不持有完整 ViewModel 或其他控制器。
- CallEvent 回主线程后先校验原身份；通话回复、麦克风、播放和暂停分别验证代际／身份。历史切换、关闭、重试或资源根目录变化使相应旧事件失效。
- 展示事件传递原 PresentationToken；草稿版本只决定确认时是否清稿。失败半流不进入历史，历史仍由 Workbench 提交。
- 退出沿用实际任务／进程／执行器清理链路，取消 future 不等于工作结束；安装仍为受管进程中的临时目录、校验与原子发布。

## 目录与测试契约

生产：shell（壳／设置）、presentation（QML 投影）、workspace（导航／来源／阅读）、voice（分轮／预检／连续语音）、speech_library（模型库／操作／任务列表）、tasks（共享 worker／进度／错误）。旧平铺模块没有转发文件。完整模块映射保存在本次构建证据 `build/desktop-governance/module-migration.json`。

LearningPropertiesMixin／ConversationViewMixin 属于 LearningViewModel；ReaderWorkspaceMixin 属于 DesktopWorkspaceController；SpeechLibraryOperationsMixin 属于 SpeechLibraryViewModel。这三组仍共享其 QObject 状态。后续新增状态写入者或异步职责前须先提炼快照与失效规则；本轮没有声称它们已经完全解耦。

Qt fixture 只在 tests/desktop/conftest.py；FakeAudio／FakeSpeech、合成 PCM／RTC／预检、交互助手和场景工厂供测试与脚本共同使用。工厂不依赖 pytest，不在导入时设置平台；使用上下文管理器关闭场景和还原补丁。共享 EPUB 与加密替身也不再从具体测试用例导入。

门禁新增生产代码禁止依赖 tests、脚本禁止导入 test_*／fixture 内部／注入 tests 目录、连续通话唯一状态写入者、桌面根目录入口清单和 wheel Python 模块清单。桌面／application 的 F401 已加入 CI。翻译提取递归发现 Python，保留文本和上下文，WebEngine 白名单同步新路径。

## 验收证据

基线收集 642 个用例，最终收集 679 项，原用例全部保留，新增 37 项。按文件迁移和参数化模块标识变化逐项映射，未减少用例，跳过原因不变。映射与差集保存在 `build/desktop-governance/test-inventory.json`，原始收集记录保存在同目录。

阶段证据：门禁／偏好／公开查询回归通过；连续语音拆分阶段相关 24 项通过；目录迁移的架构／连续语音 41 项通过；共享场景与准备／预检相关 28 项通过；独立脚本启动与场景异常清理 8 项通过。

最终结果：

| 验收 | 结果与证据（相对仓库根目录） |
| --- | --- |
| 完整离线回归 | **669 passed, 10 skipped，259.44 秒**；`build/desktop-governance/offline-final.txt`、`offline-final.xml`。跳过：真实 AI 1 项、真实本地语音 8 项、真实 RTC 1 项，均需原有显式开关 |
| Ruff／F401／空白 | `ruff check src tests scripts`、桌面／application F401 与 diff 空白检查通过 |
| 体积与所有权门禁 | 193 个自有生产 Python／QML／JS 文件、1569 个 Python 函数；最大文件 787 行（CallCoordinator），最大函数 100 行；递归所有权、运行时导入环、Qt 与测试依赖边界均通过。`size-audit.json` |
| 文本／分轮语音／历史 | 可见 Windows，明亮 100% 与暗色 150%，宽度 360／1180；各 46 张截图，无 QML 错误。`visible-light/report.json`、`visible-dark-150/report.json` |
| 连续语音 | 合成 RTC／PCM／权限预检；暂停、保留草稿、识别、播放、打断、失败恢复与停止；14 张截图，4 次 Mock 对话，回调与 QML 错误均为 0。`visible-continuous-report.json`。结尾故障文案是主动注入的设备失败状态 |
| 阅读器 | 9 项检查、7 张可见截图；英中日、明暗、1600／680 宽度，字体已加载、无溢出，拖选／复制／发送／历史及离线 profile 通过。`visible-reader/report.json` |
| 模型库 | 360／600／800／1180／1440 宽度、STT／TTS 页签，10 张截图、10 项真实滚轮检查，独立取消通过；任务与传输均合成。`visible-model-library/report.json` |
| 托盘与退出 | tray／dialog／window 三个入口分别执行；每项覆盖明暗与 360／1180、隐藏继续工作、托盘恢复、策略回读、退出及 worker 清理，共 18 项检查与 12 张截图。`visible-lifecycle/*-report.json` |
| 进程结束 | 记录的 14 个宿主／所属子进程（含 QtWebEngineProcess）全部结束，未发现存活记录或遗留直属子进程；未结束任何用户进程。`process-cleanup.json` |
| 翻译与资源 | 递归提取 684 个已有文本，无新增文本或上下文变化；翻译编译通过；vendor pin／逐文件哈希通过；资源位置未移动 |
| 新 wheel | 从 `bb950a0` 的干净文件清单复制精确工作区字节到全新目录构建，避免 Git 归档的 Windows 文本换行差异；138 项资源逐字节匹配，Python 模块清单一致，无旧平铺模块。`dist-final/shinar-0.1.3-py3-none-any.whl`、`wheel-final-check.txt` |
| 隔离安装 | `uv pip install --offline --no-deps --target .../installed-final`，用 Python `-I` 运行探针，确认包来自隔离目录；材料／已读范围／讨论／重启恢复及 QML 启动通过；实际 CLI load／确认范围／start／say／finish／quit 通过。依赖复用当前宿主环境，不代表独立 Windows 分发验收。`installed-final-probe.txt`、`installed-cli-report.json` |

上述证据统一位于 `build/desktop-governance/`，属于忽略的本地构建／验收产物；摘要为 `acceptance-summary.json`。可见场景依次执行，没有同时打开两项可见验收。离屏 WebEngine 输出过软件渲染回退日志，可见阅读器另行检查了实际字体、墨迹与截图。

最终 wheel SHA-256：`d86beca4e871e17c3a2ac553aa92fc83f56022037b018ebf19056cebeb65cb01`。

验证期间发现并修正两项测试迁移问题：恢复 Windows 二进制测试原有的 PySide6 跳过检查；连续语音重试原先可能在 worker 计数增加时误把开场消息当成新回复，改为等待新回复完整持久化及投影，不放宽断言或超时。修正后重新完成整套离线回归。

构建与可见验收仅使用隔离 Mock、临时学习库／INI 和合成音频，不修改个人配置、学习数据、模型缓存；付费模型调用为 0。真实 AI、真人语音和新 Windows 安装器本轮未验收，旧证据不升级为本轮通过。

## 本地提交

- `151588a`：保存侧栏图标与字标对齐。
- `057bfba`：递归所有权门禁、设置兼容与公开材料查询。
- `fd56818`：连续通话状态与准备所有者拆分。
- `1d3a1bd`：生产职责分包、桌面测试迁移、共享场景与导入位置治理。
- `6b00165`：独立脚本、场景异常清理和 wheel 核心路径检查。
- `bb950a0`：等待已确认的重试投影并更新递归翻译位置；本轮 wheel 的代码基准。
- 本记录及验收索引由最后的文档提交交付；未推送远端。
