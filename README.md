# LinguaLoop

LinguaLoop 是一个把沉浸式输入转化为语音输出练习的开源语言学习伙伴。**沉浸提供语境，LinguaLoop 帮你练输出。** 看番、追视频、听播客或读文章后，确认已读范围后直接围绕共同内容自由聊天，AI 再按兴趣补充参考和可选方向；也可以自愿进入语境 roleplay。

## 当前状态

项目处于早期 MVP 阶段。当前开发先验证纯文本：材料本地保存 → 确认已读位置 → 后台完成全范围精简理解与短概述 → 自由聊天时本地选择依据 → 推理角色按信息缺口补充。准备未完成也可提前聊天。已有暖纸与墨迹风格的 PySide6/QML 工作区、SQLite 恢复与分轮语音适配器；基础本地 STT/TTS 和 LiveKit 已独立接通。连续收音、自然插话与真人语音仍须独立验收。桌面页面与原文对照见[工作区指南](./docs/desktop/WORKSPACE.md)。

文本服务通过 OpenAI-compatible provider 接入，推理与对话是独立配置的两个角色。仓库示例使用 `deepseek-v4-pro` 思考模式按需整理参考，使用 `deepseek-flash` 非思考模式回复实际发言；也允许两个角色使用同一模型。运行时以本地 `.env` 或系统环境变量为准，模型名不是业务约束。预测只作参考，不能成为“用户说过的话”。

2026-10-28 新方案在隔离的可见 Windows 窗口完成完整《Lolita》语义准备：39 个授权来源单元、193 条基础笔记、短整体认识，不生成批量题库。全书 8 轮和部分阅读 6 轮实际讨论、两次复盘与重启恢复已保存；另完成 12 场景三条件回放及中日文短材料检查。达到 100 次真实请求上限后停止调用。**事实质量门禁未通过**，完整回复也未稳定低于一秒；检索修正后的真实复验待新预算。详见[语义准备实测](./docs/validation/text/SEMANTIC_PREPARATION_2026-10-28.md)。原文、实际历史和截图只留本机；旧题库、资料和历史继续兼容读取。

**1 秒仍是优化目标，完整回复尚未稳定达到。** 模型首字、完整回复和 UI 端到端耗时分别测量，慢轮次也计入结果。真实连续语音、麦克风与云端 STT/TTS 仍待独立验收。开发过程和历史限制见[路线图](./docs/planning/ROADMAP.md)、[小说阶段记录](./docs/validation/text/NOVEL_ACCEPTANCE_2026-10-28.md)与[初版记录](./docs/validation/mvp/INITIAL_VERSION_2026-10-24.md)；其中较早的余额不足和未完成记录不代表当前服务状态。

## 快速开始（Windows）

需要 Python ≥3.11 与 `uv`。在仓库根目录运行：

```powershell
uv sync --dev --extra desktop
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 编辑 .env，填写自己的端点、API Key 和模型 ID，再启动。
uv run lingualoop-desktop
```

配置不完整时仍可查看本地材料和历史，需要模型的操作会提示配置问题。修改端点、密钥、模型或语音配置后，关闭应用再启动即可读取新配置，已有本地资料会保留。纯文本讨论不需要先配置 STT/TTS。

资料契约、预算与模型协作见[AI 专项方案](./docs/architecture/ai/PREPARATION_AND_DIALOGUE.md)。机制实现与质量验收分开标记；不能从 ready 状态推导所有事实正确。

## 自由聊天与阅读进度

新导入先保存原文。选择“已经读完”，或用原文最后一句精确定位；百分比定位会向前取整并展示实际末尾，核对后再确认。确认立即落盘，随后后台按范围调用推理角色，逐单元保存有出处笔记并合并短概述；会消耗配置服务的额度。阅读范围随会话冻结，活动会话中不能悄悄改变范围。部分阅读不使用全书概述、后续身份或依赖不明的旧资料。

聊天无需选题。开场想法先进入可编辑草稿；前台由对话角色使用统一上下文回应。资料缺口、跨段联系、反驳和历史窗口不足才触发后台准备，最多一个任务；新消息保留有效来源事实，过期立场判断不供给后续轮次。方向可忽略，点击只填草稿。准备进度、失败、继续入口和结果在材料页；失败不阻止有依据的聊天。旧材料不会因启动／历史切换自动付费升级，更换模型也不会删除已选资料。

基础理解预算按授权范围估算 T：输入 `2T+16000`，输出 `max(16000,0.75T)`；会话后台输入／输出 `32000/8192`、八次请求保护、单任务最多 45 秒。请求前事务预留，服务回报后结算；未知失败／取消保留预留，重启不重置。当前预算为代码默认值，不新增个人环境配置。普通对话和复盘分项记录；这些额度不是货币价格承诺。

隔离验证时可使用 `scripts/desktop_session_probe.py --settings-dir build/probe-settings --output build/probe-output`，配合 `LINGUALOOP_DATA_DIR` 指向工作区临时库。`--mock` 使用离线服务；真实调用另需 `--real` 与 `RUN_REAL_AI_TESTS=1`。探针以实际 Qt 输入事件操作可见窗口，不直接注入历史。

Prompt、检索与成本的最新结果见[语义准备实测](docs/validation/text/SEMANTIC_PREPARATION_2026-10-28.md)，零模型初始索引的历史结果见[自由聊天修订记录](docs/validation/text/FREE_CHAT_2026-10-28.md)。本地词项与语义笔记检索仍可能漏召回，不能把精确引用匹配等同于解释正确。

## 技术栈与运行边界

| 部分 | 当前实现 |
| --- | --- |
| Core / 应用层 | Python、Pydantic 2、deterministic runner |
| 桌面 | PySide6 6.11.1、QML、Qt Quick Controls Material、统一 MD3 组件与 tokens |
| 后台与网络 | 长期运行的 asyncio worker、可替换文本 provider、HTTPX |
| 本地数据 | 标准库 SQLite（WAL、按操作连接/事务）、QSettings 外观偏好 |
| 导入 | TXT/Markdown、DOCX、SRT/VTT、EPUB、XLSX；视频读取旁挂字幕 |
| 已有语音接口 | Qt Multimedia WAV 录制/播放、独立 STT/TTS adapter |
| 语音基础 | 无 UI Python 转写/确认/分句合成与真实本机 LiveKit 传输；连续设备/真人交互仍待验收 |

Core 不依赖 Qt 或具体供应商 SDK。默认桌面壳是 ApplicationWindow，使用应用内标题栏；Kirigami 可选。LangGraph 保留独立实验入口，不是当前桌面编排主线。

## 产品方向

LinguaLoop 面向已经在进行沉浸输入、希望把熟悉内容转化为口语表达的学习者。用户继续按兴趣消费内容，项目负责提供有共同语境的输出机会。默认先讨论内容，roleplay 可选；学习方法和反馈节奏逐步支持配置。

核心学习闭环：

1. 带入已经看过、听过或读过的字幕、转写或文本
2. 确认已读范围，直接聊感受、疑问与不同看法
3. 系统根据交流补充少量参考和可选方向；也可以自愿进入语境 roleplay
4. 根据偏好获得提示、纠错和替代表达
5. 结束后轻量复盘，下次再练值得巩固的表达

当前主旨以 [Project Brief](./docs/product/PROJECT_BRIEF.md) 为准；用户无需先完成词汇课或理解测验才能开聊。

## 文档导航

- [AGENTS.md](./AGENTS.md): 给 Codex / coding agents 的仓库工作规则
- [docs/README.md](./docs/README.md): 文档目录入口和分类导航
- [docs/product/PROJECT_BRIEF.md](./docs/product/PROJECT_BRIEF.md): 项目愿景、用户和产品原则
- [docs/product/MVP_SPEC.md](./docs/product/MVP_SPEC.md): 第一版 MVP 范围和验收标准
- [docs/architecture/ARCHITECTURE.md](./docs/architecture/ARCHITECTURE.md): 初始系统架构和模块边界
- [docs/architecture/CORE_CONCEPTS.md](./docs/architecture/CORE_CONCEPTS.md): Core 领域对象、Provider、EventStore 和 Python/Pydantic 基础概念
- [docs/architecture/PLUGIN_ARCHITECTURE.md](./docs/architecture/PLUGIN_ARCHITECTURE.md): Core / Plugins / Patterns 三层扩展架构
- [docs/architecture/AGENT_CORE_ARCHITECTURE.md](./docs/architecture/AGENT_CORE_ARCHITECTURE.md): Python-first Agent Kernel、LangGraph adapter 和 typed LLM 调用规划
- [docs/decisions/TECH_DECISIONS.md](./docs/decisions/TECH_DECISIONS.md): 技术决策记录和待定项
- [AI 预处理与模型协作方案](./docs/architecture/ai/PREPARATION_AND_DIALOGUE.md): 当前资料契约、流程、预算和待通过的质量验收
- [分类验收记录](./docs/validation/README.md): 实际运行证据与限制
- [docs/planning/ROADMAP.md](./docs/planning/ROADMAP.md): 当前计划；历史执行地图另行归档
- [CONTRIBUTING.md](./CONTRIBUTING.md): 开源贡献规范

## 本地验证

普通 pytest 默认跳过标记为 `real_ai` 的测试，即使本地 `.env` 留有真实调用开关。离线回归仍显式设置 `RUN_REAL_AI_TESTS=0`：

```powershell
uv sync --dev --extra desktop
$env:RUN_REAL_AI_TESTS='0'
uv run --locked ruff check src tests scripts
.venv\Scripts\python.exe -m pytest -q
```

代码规范、检查范围和按模块整理的方法见[贡献指南](./CONTRIBUTING.md)。CI 在 Windows 的 Python 3.11/3.13 上运行静态检查和离线测试；工作流已配置，远端运行结果以实际 CI 为准。

生成带显式字体加载的演示截图：

```powershell
.venv\Scripts\python.exe scripts\render_ui_preview.py
```

截图保存在 `build/ui-preview/`，使用临时演示数据，不读取个人学习数据库或 `.env`。

新工作区的页面交互与截图使用独立临时库和 Mock，通过实际 QML 控件导入、保存范围和发送：

```powershell
.venv\Scripts\python.exe scripts\validate_ui_workspace.py
.venv\Scripts\python.exe scripts\validate_ui_workspace.py --visible --output build/ui-workspace-visible
```

默认离屏渲染；`--visible` 在可见窗口中执行。可用进程级 `QT_SCALE_FACTOR=1.25` 或 `1.5` 核对缩放，不更改 Windows 全局设置。

与修订 3 页面稿做视觉复核时，可用 `--review-fixture --height 960` 通过真实 QML 建立三份合成材料与多线程，然后运行 `scripts/compare_ui_screens.py` 生成设计稿／修正前／修正后的图组。脚本默认读取 `build/ui-plan-audit/visible-100-final/` 和 `build/ui-visual-review/final/`；也可用 `--before`、`--after` 指定已有截图。明确设定 `QT_SCALE_FACTOR=1` 后采集 100% 基线，避免不同显示器的系统 DPR 混入对比。

这一版界面默认中文，设置中的“显示语言”与学习偏好的“母语”分别保存。国际化采用 Qt 翻译目录，新增界面文案使用 `qsTr()`，桌面 Python 文案使用 `QCoreApplication.translate()`；动态内容使用占位符。更新中文目录：

```powershell
.venv\Scripts\python.exe scripts\update_translations.py
```

系统语言解析、翻译资源加载与首次母语建议入口已预留；未来增加语言包后再启用首次启动的系统语言默认策略，不能覆盖用户已保存的母语。完整约定见[国际化说明](./docs/desktop/I18N.md)。

## 下一步

围绕当前主旨，优先补齐以下能力（详细范围见 MVP 和路线图）：

1. 继续改进完整小说讨论的具体性、自然程度和响应速度，保留真实慢轮次及错误前提、分歧、改口的验证；1 秒不作为已经交付的承诺。
2. 文本验收后实现 LiveKit 连续对话，再选择适合未来用户接入的 STT/TTS 服务。
3. 补齐平台发行包、Pattern / capability contract，并确定项目开源许可证。

## 真实 AI 冒烟测试

普通回归应关闭真实调用。下列模型配置是仓库示例，不代表必须使用这些 ID；请使用自己端点实际支持的模型。要测试独立的 LangGraph → OpenAI-compatible provider → 真实模型链路，可在本地 `.env` 配置：

```dotenv
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_REASONING_MODEL=deepseek-v4-pro
OPENAI_DIALOGUE_MODEL=deepseek-flash
OPENAI_DISABLE_THINKING=1
OPENAI_REASONING_THINKING=1
OPENAI_DIALOGUE_THINKING=0
RUN_REAL_AI_TESTS=0
```

DeepSeek 两个角色分别控制思考：推理默认 `thinking.type=enabled`，对话默认 `thinking.type=disabled`；材料分段、汇总与后台小任务会设置自己的预算和 effort。即使两个角色指向同一模型，这些配置也保持分离。旧 `OPENAI_DISABLE_THINKING=1` 仅影响对话默认值，不再全局关闭推理。通用兼容服务可用两个新变量分别覆盖；不支持 thinking 参数的服务请留空这些变量并将旧项设为 0。模型名称和参数以[供应商模型文档](https://api-docs.deepseek.com/quick_start/pricing/)及[思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)为准；不保存或展示原始思维链。

如果不确定服务可用模型名，先运行：

```powershell
.venv\Scripts\python.exe scripts\list_openai_models.py
```

再把返回列表里的模型 id 填到 `OPENAI_REASONING_MODEL` 和 `OPENAI_DIALOGUE_MODEL`。然后运行真实 AI 冒烟测试：

```powershell
$env:RUN_REAL_AI_TESTS='1'
.venv\Scripts\python.exe -m pytest tests\test_llm.py --run-real-ai -q
$env:RUN_REAL_AI_TESTS='0'
```

真实调用必须同时传入 `--run-real-ai` 并设置 `RUN_REAL_AI_TESTS=1`，会消耗账户额度。此冒烟测试不代替正常桌面的完整材料、多轮对话、历史恢复和语音验收。

不要提交 `.env` 文件；仓库已在 `.gitignore` 中忽略本地环境文件。

## CLI POC

命令行原型读取与桌面相同的模型配置，用于验证闭环：

```powershell
uv run lingualoop
```

如果还没同步依赖，先执行 `uv sync --dev`。需要离线 Mock 时，使用下方桌面调试的独立数据目录示例，将启动命令改成 `uv run lingualoop --mock`。

常用命令：

- `load`：加载并分析材料
- `import`：导入 `.txt`、`.md`、`.markdown`、`.docx`、`.srt`、`.vtt`、`.epub` 或 `.xlsx` 材料，并确认标题、track 与 normalized preview
- `start`：开始一次练习会话
- `say`：发送用户回答
- `finish`：结束本轮并生成结构化复盘和 review items
- `review`：查看今日到期复习项
- `review --all`：查看全部 active 复习项
- `rate`：记录 `again`、`hard`、`good` 或 `easy` 复习结果；`good/easy` 会先做最小答案校验
- `summary`：查看当前会话摘要
- `export`：导出会话 JSON
- `reset`：清空当前选择状态，不删除本地持久化数据
- `quit`：退出

默认模式会读取 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_REASONING_MODEL` 和 `OPENAI_DIALOGUE_MODEL`。离线调试可用 `--mock`。

## MD3 桌面初版

桌面端采用 Python ≥3.11、PySide6 6.11.1、QML 和 Qt Quick Controls Material。Windows 默认使用 ApplicationWindow，安装 PySide6 即可运行。Kirigami 仅作为显式启用的可选壳：

```powershell
uv sync --extra desktop
```

启动桌面工作台。桌面端默认使用真实 OpenAI-compatible provider，并读取当前工作目录 `.env` 或系统环境变量中的 `OPENAI_*` 配置：

```powershell
uv run lingualoop-desktop
```

离线调试时可以显式使用 Mock provider。用独立数据目录保存演示内容，退出后恢复原配置：

```powershell
$linguaPreviousDataDir = $env:LINGUALOOP_DATA_DIR
try {
    $env:LINGUALOOP_DATA_DIR = Join-Path $PWD 'build/mock-library'
    uv run lingualoop-desktop --mock
} finally {
    $env:LINGUALOOP_DATA_DIR = $linguaPreviousDataDir
}
```

普通启动缺少或无法解析 AI 配置时，会进入本地资料模式，仍可查看已保存的材料和历史；需要模型的操作明确报错，不会自动生成模拟回答。服务余额不足时，本地资料也可打开，在线操作显示服务错误。

界面默认跟随系统主题，可切换浅色、深色及减少动效。主要围绕材料和对话；复盘、设置作为辅助入口。宽度小于 600 使用底部导航；600–1199 使用 80px 导航 rail；1200 起对话页可显示 320px 语境面板。

## 材料与本地持久化

当前桌面自由聊天使用前文所述的本地索引和已读范围。下面的整书分段／题库预算及 `validate_novel.py` 选题命令属于**旧版显式准备工具和兼容路径**，不描述默认桌面，也不是新 AI 设计的预算。

EPUB 按书内 spine 阅读顺序抽取文字并去除 ruby 注音、脚本与样式；Excel 按工作表和行抽取单元格缓存值，不执行公式。视频 `.mp4/.mkv/.webm/.mov/.avi` 只导入同目录同名 `.srt` 或 `.vtt`，当前模型未读取视频画面。没有字幕时先生成/导出字幕再导入。

### 旧版显式材料准备工具

该路径先保存原文，再分段整理：小材料每段最多 12000 字符，超过 120000 字符的长篇每段最多 24000 字符。默认单份预算 1000000 字符，可用 `LINGUALOOP_MAX_MATERIAL_CHARS` 调整到 12000–5000000，超限保留原文并提示。DeepSeek 推理角色的分段任务采用思考模式 low、16000 tokens，明确截断时最多再以 24000 重试一次；默认同时处理 3 段（`LINGUALOOP_PREPARATION_CONCURRENCY=1–4`）。完成即保存摘要、人物、事件、话题、精确引用和哈希。最后用全部有序笔记做整书汇总（low、24000 tokens；明确截断时最多以 32000 重试一次），贯通结局、合并人物并准备跨章节话题，预制题最多保留 60 个，用户后续自定义题另行保存。网络或汇总失败后重新分析会复用已完成段落。多次模型调用会产生相应费用，取消请求不保证服务停止计费。

单次分析运行总预算默认 1800 秒，可用 `LINGUALOOP_PREPARATION_DEADLINE_SECONDS` 调整；一般非流式调用另有默认 240 秒 wall deadline（`OPENAI_REASONING_DEADLINE_SECONDS`），整书汇总单独默认 600 秒（`OPENAI_SYNTHESIS_DEADLINE_SECONDS`），超时保留完成段落。这些预算不让前台 Flash 等待后台推理。整书汇总成功才允许开聊。话题含开场问题、候选用户意图、回答要点、短回复、追问和原文引用。

前台只调用对话角色。除当前题的预制分支、可用后台资料外，本地按当前发言在已保存的全书准备资料中选择相关情节和人物；不在前台做整书推理或搜索原文。上下文保留整书概要、最多 48 段简短索引、最近十条消息与少量早期读者观点，当前改口优先。单条发言上限 4000 字符，对话输出上限 160 tokens。证据集中去重，当前发言只传一次；传给模型的章节编号替代无对话意义的长 ID，数据库仍保留稳定来源 ID。回复以简短、具体的日常交流为目标，不要求每轮提问或变成理解测验。

两个角色使用独立的长期 HTTP 连接池，空闲连接保留 120 秒，推理/对话连接上限分别为 4/2；取消后台请求不会占用或关闭对话池的连接。连接复用不等于供应商推理延迟达标，仍需测量冷启动和后续轮次。

后台在单次运行中新建会话时重置准备计数，上限 12 次、同时最多一个请求、单次任务 45 秒；这个计数尚未持久化，不能作为跨重启的计费上限。DeepSeek 推理角色使用 low、4000 tokens，以当前交流相关的已准备要点、一个引用及最近两条发言生成微型参考。新发言、结束、重置或切换材料会取消旧请求，过期结果丢弃，失败不阻断聊天。新准备必须有非空候选意图、要点及精确引用，无效结构最多尝试两次，明确达到输出预算时不重复相同请求。诊断只含完成原因、tokens、耗时和失败阶段，不保存原始返回或思维链。历史准备在消费前再次校验。自定义话题开聊前，从全部段落及原文按词匹配挑选相关章节、命中附近窗口和均匀全书概览，再交推理角色整理保存；准备成功才进入新对话，失败时保留当前材料。以后轮次仍只走对话角色。

本阶段提供结束后反馈或关闭反馈；历史 `immediate` 偏好在新讨论中也延后到结束，避免推理纠错阻塞回复。旧 `options=None` 的直接 runner 接口保留兼容语义。`SessionStepResult.timing` 中 `ttft_ms` 是首个可见文本块耗时，`total_ms` 是完整模型回复耗时，不含后续 SQLite 保存；实际端到端耗时应另测。只在回复完整成功后保存用户与助手消息，失败的半段流不进入历史。

### 本地数据与历史

默认本地数据保存在平台应用数据目录下的 `LinguaLoop/lingualoop.sqlite3`，可通过 `LINGUALOOP_DATA_DIR` 覆盖。外观与新会话偏好使用 QSettings；凭据保留在本地环境。可选 Kirigami 的兼容性见 [QML runtime](./docs/desktop/QML_RUNTIME.md)。

Windows 默认路径为 `%LOCALAPPDATA%\LinguaLoop\lingualoop.sqlite3`。SQLite 使用 WAL 和按操作连接，保存原文、整理资料、已确认消息、复盘及事件。缓存按原文 SHA256、标题、源语言、学习语言/水平、推理服务/模型和准备版本隔离，不含密钥或文件路径。相同标题、内容、源语言与学习配置的材料重复导入复用原记录；已经完成的资料在切换模型后也会保留，不自动重复付费分析，显式重新分析才按当前模型查找或生成对应缓存。不完整缓存先展示，再由“继续整理”恢复。完整缓存不被较旧的部分进度覆盖，自定义题与历史不会被旧缓存覆盖。EPUB 标题优先读取书内元数据。

对话页“历史对话”按当前材料显示全部已保存会话，可恢复旧线程；完成的会话只读。正常重启恢复最近会话并显示对话页。当前草稿在页面/线程切换间保留于内存，未发送草稿不写数据库。数据库及相邻 `-wal`、`-shm` 文件均含本地敏感数据，备份或迁移前先关闭软件。

### 旧版显式准备与实机验证工具

真实小说验收工具支持持久化接续，必须显式启用真实调用；`build/` 中的数据库含原文和会话，请勿提交：

```powershell
$env:RUN_REAL_AI_TESTS='1'
.venv\Scripts\python.exe scripts/validate_novel.py --real --phase prepare --material 'D:/books/novel.epub' --data-dir build/novel-validation
.venv\Scripts\python.exe scripts/validate_novel.py --real --phase topics --data-dir build/novel-validation
.venv\Scripts\python.exe scripts/validate_novel.py --real --phase start --topic-id topic_ID --data-dir build/novel-validation
.venv\Scripts\python.exe scripts/validate_novel.py --real --phase turn --message 'I read the ending differently.' --data-dir build/novel-validation
.venv\Scripts\python.exe scripts/validate_novel.py --real --phase review --data-dir build/novel-validation
```

`start` 也接受 `--custom-topic`，`turn` 接受 UTF-8 `--message-file`；`export` 输出可读的 `prepared_notes.md`。`chat` 保持一个进程和连接，逐行接收 JSON 命令（`start/turn/wait/state/review/quit`），用于真实连续交谈计时。输出分别包含首字、完整回复和端到端耗时；低于 1 秒是优化目标，结构通过不能代替对话质量与性能结论。

准备完成后，可运行 `scripts/validate_novel_desktop.py --real --data-dir build/novel-validation`。它复制已有数据库到新的 `desktop/` 子目录，以真实模型验证点击选题、键盘输入、发送、切页与草稿保留、不同宽度和复盘，保留本地截图及元数据报告。需要 desktop/dev 依赖和真实调用开关，已有验收副本不会被覆盖。

验证正常软件可用开发探针 `.venv\Scripts\python.exe scripts/desktop_session_probe.py --qt-dialogs --output build/native-session`：打开可见 Windows 窗口，使用正常应用数据库，以 Qt 鼠标/键盘事件操作控件，不注入对话记录。stdin 接收 `state/click/type/key/snapshot/quit` JSON 命令，需要保持交互终端。Ctrl+Enter 发送时记录从按键到首段 UI 文本、后续 Qt 帧和完整操作结束的时间，同时保留模型首字/完整回复计时。报告、截图及实际文本仅存 ignored `build/`。默认阻止模型调用；实聊需追加 `--real` 并设置 `RUN_REAL_AI_TESTS=1`。探针仍可改变选择和本地状态，纯查看资料优先用正常软件。已退出的实机运行会生成 `run-*.json`；历史报告和阶段文档须结合当前代码与后续运行记录判断。

语义方案的隔离实机验证与回放工具：

```powershell
$env:LINGUALOOP_DATA_DIR=Join-Path $PWD 'build/semantic-validation/app-library'
$env:RUN_REAL_AI_TESTS='1'
.venv\Scripts\python.exe scripts/desktop_session_probe.py --real --qt-dialogs --settings-dir build/semantic-validation/settings --output build/semantic-validation/native --request-ledger build/semantic-validation/requests.sqlite3 --request-limit 100
```

每次接续均使用同一 `--request-ledger`，达到授权上限不删除账本或提高额度。`scripts/validate_semantic_dialogue.py` 的 `--phase export|draft-gold` 只读实际库并导出本地文件，不调用模型；`compare|languages` 还要求 `--real`、真实开关及同一请求账本。完整命令均需 `--data-dir`、`--output`；`compare` 另需 `--gold` 指向已核对出处的参考 JSON。回放不写入实际历史。`comparison.json`、原始失败和独立人工评分空缺均保留，禁止把参考草稿自动冒充已核读资料。

## 打包检查

当前分发产物是 Python wheel，独立 Windows 安装器尚未交付。修改 QML、SVG 或许可证后，核对它们已进入安装包：

```powershell
uv build --wheel --out-dir build/package-check
$linguaWheel = Get-ChildItem build/package-check/*.whl | Sort-Object LastWriteTime -Descending | Select-Object -First 1
.venv\Scripts\python.exe scripts/check_wheel_resources.py $linguaWheel.FullName
```

该检查从隔离目录加载安装包资源，不替代真实服务、交互质量和真人语音验收。

## 语音配置与使用

### 可选 LiveKit 本机探针

文本链路验证后，可单独安装官方 RTC/API SDK 做本机传输探针：

```powershell
uv sync --dev --extra desktop --extra realtime
.venv\Scripts\python.exe -m pytest tests\realtime -q
.venv\Scripts\python.exe scripts\probe_livekit.py --download-server
```

探针只使用自写文本和合成 PCM，不读取 AI 凭据或用户学习库。server 固定版本校验后缓存于 ignored `build/livekit-probe/`；信令仅 loopback，媒体/STUN 可用 `--rtc-bind-ip <本机所属私网IP>` 明确绑定单个地址，关闭 RTC TCP fallback，不修改防火墙或使用公共 STUN。2026-10-29 修复真实 STUN、对端数据就绪和退出重入后，本机私网地址路径已经通过真实音轨/文本验证；纯 loopback 历史失败仍保留。临时 token、自有子进程及资源结束时清理。具体证据见 [LiveKit 指南](./docs/desktop/LIVEKIT.md)，不等于持续麦克风或真人语音通过。

### 无 UI 的 Python 基础语音

`VoiceSessionCoordinator` 复用 Workbench 的推理/对话角色，提供转写草稿、确认落库、回复分句合成和独立重试；新增确认事务使回复失败不丢用户发言。普通 pytest 不加载模型；真实本地模型与 RTC 分别通过 `--run-local-speech`、`--run-realtime` 开启，始终可使用 Mock LLM 避免付费请求。接口、准备 profile 和复现命令见 [Python 语音指南](./docs/desktop/VOICE_PYTHON.md)。QML 尚未接新服务。

### 现有分轮语音

在本地 `.env` 中分别配置 `LINGUALOOP_STT_BASE_URL/API_KEY/MODEL`、`LINGUALOOP_TTS_BASE_URL/API_KEY/MODEL/VOICE`；首次配置可复制 `.env.example`，保留已有配置。STT 使用 `/audio/transcriptions`，TTS 使用 `/audio/speech` 并请求 PCM WAV；服务需要兼容这些接口。模型和 voice 使用服务实际提供的 ID，文本中转服务不一定提供音频能力。修改配置后重启应用。`--mock` 明确禁用真实语音服务。

选择材料和话题后点击“开始说话”，最多录制 60 秒，点击“结束录音”取得转写。编辑后点击“发送”，AI 回复保存后合成播放。可以重录、停止和重播；识别失败保留当前录音供重试，合成失败只重试合成。详细配置、隐私边界及真人验收步骤见 [分轮语音指南](./docs/desktop/VOICE.md)。

材料会发送给所配置的文本服务，录音会发送给 STT，AI 回复会发送给 TTS。原始录音只作临时处理，数据库保存用户确认发送的文本。正常结束、切换材料或退出时清理临时音频；异常终止的残留见语音指南。

### 可选本地语音模型库

补充：独立 Melo 英文与 VOICEVOX 已有可显式注册的 Python 后端；下文 GUI 下载/选择范围仍沿用已有实现，新增后端的界面与发行安装尚未接入。

“设置 → 语音模型”按语言分别下载、测速、试听和选用 STT/TTS；“计算与加速”分别设置识别/合成的自动、CPU 或 NVIDIA CUDA GPU，准备独立运行环境，并查看显存/整卡使用率、设置预算与空闲释放。自动模式对已验证明显提速的 SenseVoice 2024 FP32 优先用 GPU，轻量 CPU 模型继续用 CPU。首次准备 GPU 环境会下载固定版本 CUDA/cuDNN 运行库，通常无需完整 Toolkit，显卡驱动需由用户安装。已选对话模型接入桌面分轮录音/朗读；目前支持 SenseVoice、ReazonSpeech、Zipformer 和现有 sherpa TTS 适配，独立 Melo 英文、Kotoba、VOICEVOX 的产品适配仍待完成。LiveKit 连续语音另行验收。

基础桌面安装可查看目录、下载及准备运行环境；CLI 旧测速入口也可用 `uv sync --dev --extra desktop --extra local-speech`。`LINGUALOOP_SPEECH_DIR` 覆盖缓存目录，`LINGUALOOP_SPEECH_PYTHON` 仅覆盖 CLI/旧 CPU 测速解释器，实际对话使用应用管理的独立环境。高级本地验证可通过 `LINGUALOOP_CUDA_DLL_DIR` 指定匹配的 CUDA DLL 目录，不修改系统 PATH。命令、资源预算、许可边界和本机结果见[本地语音指南](./docs/desktop/LOCAL_SPEECH.md)。

逐模型的中英日严格评测见[语音评测记录](./docs/validation/speech/LOCAL_SPEECH_STRICT_EVALUATION_2026-10-28.md)：公开真人语料的 CER/WER、冷/热首结果、首 PCM、合成/播报字速、独立候选环境及匿名听评包分开记录。评测脚本与模型资产放在独立目录，不切换正常应用的语音 provider；未取得人工评分的听感项目保持未验收。
