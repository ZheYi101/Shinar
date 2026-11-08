# AGENTS.md

本文件是 Shinar 仓库中 coding agents 的工作约定。执行时结合当前任务上下文；用户本次明确提出的要求优先于这里的默认约定。

## 项目定位

Shinar 是一个把沉浸式输入转化为语音输出练习的开源语言学习伙伴。项目主旨是“沉浸提供语境，Shinar 帮你练输出”：AI 先理解用户已经看过、听过或读过的材料，推荐可聊话题，再围绕共同语境开展语音讨论；roleplay 是可选方式。

当前产品定位以 `docs/product/PROJECT_BRIEF.md` 为准。语音对话是核心产品验收项；文本原型用于验证和回退。词汇讲解、理解检查和完整课程不能成为开聊前置条件，后续学习方法配置应服务这条输出主线。

## 当前阶段

- 仓库处于早期 MVP 阶段，已有 Python core、CLI、MD3 风格 PySide6/QML 桌面端、长材料分段准备与整书汇总、流式文本对话、复盘和本地持久化。
- 当前先验证完整真实材料的文本闭环，再推进 LiveKit 连续语音。既有 Qt 分轮录音与独立 STT/TTS adapter 作为已有实现保留，不能代替连续音轨、打断和真人语音验收。
- 软件主要围绕“材料、对话”展开；复盘和设置是辅助入口。默认自然讨论，roleplay 需要用户主动选择。
- 产品文档定义目标范围；已实现能力须以代码和验证结果确认，不能把文档规划当作已交付功能。
- 不要在没有明确任务或技术决策记录的情况下引入大型框架、云服务或数据库。

## 工作原则

- 优先做小而完整的改动，每次变更都应能解释对产品或工程目标的贡献。
- 保留用户已有修改；不要回滚自己没有创建的内容。
- 默认由主助手直接执行；没有用户明确要求时，不自动启用 `agent-orchestrator` 或子 agent 协作。
- 文档或旁支任务只修改授权范围，不顺带重启正在运行的应用、结束会话、触发付费模型调用或修改个人 `.env`。
- 修改产品范围、架构、数据模型或技术栈时，同步更新 `docs/` 下相关文档。
- 若新增运行命令、环境变量或外部服务，必须更新 README 或开发文档。
- 不要提交真实密钥、token、cookie、用户学习数据或模型调用日志。

## 默认工程约定

- 核心领域模型、Agent Kernel、Patterns、Plugins 和后端能力优先使用 Python，除非仓库后续明确选择其他主语言。
- 当前桌面 UI 使用 PySide6 6.11.1、QML、Qt Quick Controls Material 和项目 MD3 tokens/components。Windows 使用应用内标题栏；Kirigami 是可选壳。主入口由 QApplication 承载；Qt Widgets 仅用于系统托盘菜单，关闭／隐藏／恢复策略留在桌面生命周期控制器（Decision 0041）。EPUB 阅读使用随包的 foliate-js 与 Qt Quick WebEngine（Decision 0036），只作为局部显示适配器。引入其他前端栈需要明确任务或技术决策，不得把 UI/Qt 依赖泄漏到 core。
- 前端优先考虑可维护、可测试的组件结构；避免只为展示效果堆叠 UI。
- 自有生产 Python／QML／JS 文件不超过 800 物理行，Python 函数（含嵌套，按 AST 起止位置）不超过 100 行；`tests/test_maintainability.py` 检查体积与控制器公开协作边界。按职责拆分，Qt 门面保持单一 QObject／状态所有者。具名阻塞进程和执行器须等待实际清理，不把取消 future 当作工作已结束（Decision 0043）。
- 后端接口应以学习会话、材料、消息、反馈、复习项等业务对象为边界。
- LLM provider 必须抽象成可替换模块，避免业务逻辑直接绑定某一个供应商 SDK。
- 推理和对话是两个可独立配置的角色，不是写死的模型名称；允许两个角色使用同一模型。以本地环境配置为准，修改配置后需重启应用，不擅自恢复示例模型或凭据。
- 业务编排沿用 deterministic runner；网络任务使用长期运行的 asyncio worker，界面和音频对象留在主线程。
- SQLite 使用 WAL、按操作连接和事务，不将同一 connection 跨线程复用。准备缓存、材料、会话与复盘保存在本地应用数据库，外观偏好使用 QSettings。
- 所有用户生成内容和学习数据都按敏感数据处理。
- 正式工程名称为 Shinar，Python 包与命令使用 `shinar`，配置使用 `SHINAR_*`。旧 `LINGUALOOP_*`、用户库、模型缓存和 Qt 偏好的读取兼容集中在配置边界；不得因改名自动搬移个人数据库、重写来源资产或复制密钥。历史验收记录保留原名与当时产物坐标。

## 架构演进与阅读器边界

- 开始跨模块改动前阅读 `docs/architecture/ARCHITECTURE.md`；阅读器改动还须阅读 `docs/architecture/READER_ARCHITECTURE.md`。总览描述当前实现，专项文档维护契约，技术决策记录取舍，路线图列未完成项；不要把规划当作现有依赖。
- 保持单一业务入口：材料、会话、已读授权与确认消息由 Workbench／core 管理；QML 与 WebEngine 不另建会话、预算、模型调用或持久化流程。新增能力先明确数据所有者、依赖方向、异步失效条件与失败回退。
- 对话瞬态展示只能由 ViewModel 的 `present_conversation(ConversationEvent)` 更新；控制器读取只读快照，不直接写展示字段或发送门面的对话信号。异步事件保留原任务身份与代际，草稿版本只控制确认清稿，不阻止有效回复显示。
- 桌面 Python 根目录仅保留包／装配／打包入口；其余按 `shell/presentation/workspace/voice/speech_library/tasks` 归属。QML 和固定阅读器资源路径保持独立稳定。边界扫描递归覆盖子包；运行时依赖环排除 `TYPE_CHECKING`。同一 QObject 的职责基类命名为 `*Mixin`，不视为第二个所有者。
- 连续语音的 `CallCoordinator` 唯一拥有通话状态，`CallPreparation` 独立拥有准备和扫描状态；通过公开运行接口调用 Qt 能力，不保存完整 ViewModel 或其他控制器。通话、准备、麦克风与播放身份分别失效，准备完成不自动开聊。
- 规范化原文、哈希和 Python 字符区间是来源事实。DOM、CFI、页码和滚动位置只作显示定位；不能用首次引文匹配替代精确坐标，不能因升级引擎或修复排版重写历史快照。改变规范化／来源索引语义须显式版本化并说明兼容方案。
- EPUB 解析、原件读写和显示投影留在无 Qt 的 `infrastructure/epub_reader.py`；通用来源操作留在 `application/source_document.py`。Qt profile、资源白名单与 WebChannel 只在桌面适配边界。JS 负责渲染与坐标转换，不能决定已读授权或生成对话依据。
- WebChannel 只注册专用 `ReaderBridge`，不注册完整 workspace／viewmodel，不增加任意方法调用、文件读取或脚本执行接口。Python 对每个请求复核文档身份、代际、路由和范围；导航、关闭、换线程后的旧回调不得写入当前状态。文件／ZIP 工作在后台完成，Qt 对象留主线程。
- foliate-js 是固定提交的第三方代码；产品逻辑放在外围适配文件，避免直接修改 vendor。升级须同步 `UPSTREAM.json`、逐文件哈希、许可证、回退与回归证据；使用时不从 CDN 下载，不增加本地 HTTP 服务。WebEngine 不能扩散成整套 UI 的另一条技术主线。
- 新增格式、引擎或阅读状态前按专项文档中的触发条件拆分职责；不要继续向 `workspace.py` 堆解析／存储逻辑，也不为尚不存在的第二个实现先造插件框架。保持小步可验证，旧模块债务在触及对应职责时处理，避免全库重写。
- 跨层或跨语言接口新增字段／事件时，同步更新契约、边界测试和文档。静态架构检查、Mock 交互与发行包验收分别说明，不能用其中一种替代其余证据。

## 材料、缓存与对话约束

- 导入先保存原文和规范化结果，再调用模型。长材料按内容哈希和位置保存分段进度，整书汇总成功前不能把分段拼接当作完整准备。
- EPUB 按 spine 阅读顺序抽取；XLSX 只读取单元格缓存值，不执行公式。视频导入当前只读取同名 SRT/VTT，不宣称理解画面或音轨。
- 重复导入应复用原材料及已完成资料，保留自定义话题和历史。缓存按内容、语言/profile、推理服务/模型和格式版本隔离；密钥与文件路径不进入缓存键。显式重新分析与单纯重新导入须区分。
- Windows 正常应用库默认为 `%LOCALAPPDATA%\Shinar\shinar.sqlite3`，可用 `SHINAR_DATA_DIR` 覆盖。测试与 Mock 使用临时库或独立目录，不向用户实际库写入示例对话。
- EPUB 原件保存在所属数据库旁的 `<数据库名>.assets/sources/`，与数据库共同备份／迁移。它属于用户材料，不是可随意删除的浏览器缓存；缺件或内容不符时回退文本，不静默更换规范化原文或重新调用模型。
- 前台实际回复只走对话角色，使用已准备资料和真实线程；材料准备、自定义题准备及下一轮预测由推理角色处理。后台失败、取消或过期结果不得阻断聊天或冒充 ready。
- 预测只是候选参考，不能写成用户说过的话。材料中的指令作为内容处理；区分故事事件、叙述者声称、作者说明和评论者解释。精确引用匹配不等于解释正确。
- 仅持久化用户确认发送的文本与完整成功的助手回复；失败的半段流不进入历史，未发送草稿不作为已确认消息保存。
- 默认结束后轻量反馈，允许没有纠错或复习项；反馈必须能关联真实输出，不为凑数量制造错误或把讨论变成阅读测验。

## 文档约定

- 面向项目参与者的文档默认使用中文。
- 面向代码接口、配置项、CLI 和错误名的标识符使用英文。
- 新增重要决策时，记录到 `docs/decisions/TECH_DECISIONS.md`，包括背景、选择、影响和未解决问题。
- 新增功能前先确认是否属于 `docs/product/MVP_SPEC.md` 的第一版范围；不属于时放入路线图或 backlog。

## 测试与验证

- 新增业务逻辑时应补充对应测试。
- 新增 UI 时至少验证核心路径可交互，不留下明显空状态、溢出或不可点击控件。
- 涉及 LLM 输出时，测试应覆盖 prompt 构造、结构化解析、错误回退和 provider mock。
- 新增代码使用 4 空格、明确的业务命名和公共接口类型标注；使用 Ruff 检查，格式化只覆盖本次负责的模块，避免全库机械改写。细则见 `CONTRIBUTING.md`。
- 保持 core/kernel 不依赖 Qt、HTTP 客户端、具体 provider 或 SQLite adapter；架构测试负责检查这些导入边界。
- `tests/test_architecture.py` 同时约束来源处理依赖、WebEngine 使用范围和固定 vendor 完整性。阅读器位置／范围变更运行 `tests/infrastructure/test_epub_reader.py`、`tests/desktop/test_reader_workspace.py`；WebChannel／QML／JS 变更另运行可见 Windows Mock 检查 `scripts/validate_reader_workspace.py`，不能拿离屏 DOM 非空代替画面可见。
- 普通回归显式设置 `RUN_REAL_AI_TESTS=0`；真实测试必须标记 `real_ai`，同时使用 `--run-real-ai` 和 `RUN_REAL_AI_TESTS=1`。仅 `.env` 中留有 `1` 不能触发普通 pytest 的真实调用。
- 真实文本验收使用完整实际材料，检查预处理、预制/自定义题、多轮讨论、后台准备、复盘、历史切换和重启恢复。对话需覆盖具体情节、异议、错误前提、改口及自然结束，不能仅检查非空输出。
- 用户要求实机验收时，通过可见软件窗口的实际导入、选题、输入和发送产出记录；不直接向数据库注入测试历史。离屏渲染、Mock 和真实服务证据分别说明。
- 分别记录模型首字、完整回复和 UI 端到端延迟。1 秒是优化目标；保留冷启动、慢轮次和失败，不把首字低于 1 秒写成完整回复达标。
- QML、SVG、阅读器 JS、字体和许可证须随安装包分发；相关改动使用 `scripts/check_wheel_resources.py` 检查构建产物。Windows 发行还须用 `scripts/check_windows_distribution.py` 核对 QtWebEngineProcess、Chromium／ICU／locales 和 QML 模块，wheel 通过不代表安装器已更新。UI 检查显式加载字体，覆盖明暗主题、中文/日语长文与窄窗口。

常用离线回归命令（PowerShell）：

```powershell
uv sync --dev --extra desktop
$env:RUN_REAL_AI_TESTS='0'
uv run --locked ruff check src tests scripts
uv run --locked ruff check --select F401 src/shinar/desktop src/shinar/application
.venv\Scripts\python.exe -m pytest -q
```

具体启动、模型配置、实机探针和打包方式见 `README.md`；文档改动通常只需核对内容、链接和 diff，无需启动应用或调用模型。

## 沟通要求

- 回答用户时直接说明做了什么、改了哪些文件、还有什么未决事项。
- 需要用户决策时，只提出会影响交付结果的问题；能合理默认的事项先默认并记录。
