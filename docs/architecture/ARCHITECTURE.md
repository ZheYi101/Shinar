# Architecture

## 当前默认：适量基础理解与模型协作（2026-10-28）

[AI 专项方案](./ai/PREPARATION_AND_DIALOGUE.md)的资料、缓存、预算和协作机制已落地，见 [Decision 0019](../decisions/TECH_DECISIONS.md#decision-0019)。真实全书／部分阅读、三条件回放和恢复已形成[阶段报告](../validation/text/SEMANTIC_PREPARATION_2026-10-28.md)，**事实质量与完整回复一秒门禁未过**。旧题库、零模型索引和固定后台次数路径保留兼容，不再代表支持新接口的真实 provider 默认行为。

`core/knowledge.py` 定义 provider 中立的来源单元、笔记、整体认识、聊天记忆和 `TurnContext`。`application/semantic_preparation.py` 负责有限单元理解、按顺序合并、结构修复、独立缓存与预算；材料确认先保存范围，再启动可恢复任务，不锁住聊天。`core/knowledge_context.py` 联合原文、笔记、别名、事件和近期指代选择依据；provider 直接消费这一个上下文，不再二次装配。

原文稳定字符坐标及哈希留在本地；`knowledge_end` 按全部输入依赖计算，已识别前言／作者说明／评论默认与正文分离。部分阅读读取匹配范围的 manifest，拒绝整书概述和依赖不明的旧全局资料。启动、历史切换与更换模型不自动重做已选资料。新缓存身份含格式、服务／模型、影响输出的思考设置与资料语言；难度和反馈偏好不重读材料。

SQLite 新增 `knowledge_artifacts`、`knowledge_cache_hits`、`model_budgets` 和 `model_calls`，保持 WAL 与按操作事务。逐单元成功落盘；截断不原样无限重试或提高输出预算，可保存更小来源单元方案后继续。请求前事务预留，成功按实际用量结算，失败／取消未知量保留预留。旧 `preparation_cache` 不改写为新方案 ready。

前台常规一次对话请求，显式事实核对允许有限慢路径；推理四接口分别负责基础笔记、整体合并、局部核对和聊天记忆。后台缺口单并发、前台优先、45 秒总截止，并合并等待期间最新缺口；来源事实和会话判断分别校验有效期。确认历史只写完整成功消息，草稿、候选、失败半段流不进入真实发言。来源／消息 ID、版本、缓存命中、用量和计时与内容分开记录，不保存推理链或密钥。

当前检索仍是本地词项与语义笔记启发式，没有 embedding／云重排。最终检索 v2 保留预算允许的中等完整段落并补相邻短段，避免固定截短丢结论；该修正在 100 次真实请求上限之后，仅离线验证。完整质量、隐喻召回及舒适度不由结构正确自动保证。

## 历史／兼容：本地索引与固定后台次数

默认桌面导入先保存原文，`read_through=0` 等待确认。`source_index` 用字符位置、哈希、词项和附近标题提示建立本地引用；不调用材料分析模型生成题库。`reading_scope.scope_material` 在进入会话模型前裁掉后文，部分阅读不使用全局概要/人物/话题；只允许完整位于已读前缀的旧段落资料。`PracticeOptions.read_through` 冻结本会话范围。

会话默认 `free-discussion`、`topic=None`，目标语言短开场无需模型。前台以实际发言和最近两条线程消息检索，最多三段源文（各至多 1200 字符），区分标题提示、出处与解读；不把全书所有段落概要和可能回答放进每轮。旧版有出处的准备继续可供内部检索。

至少两次真实发言后，来源发生变化才后台请求微型参考，可选方向最多三个。尝试次数及来源键随 session 保存，自由会话上限三次，失败/取消亦计数；已有陈旧结果不冒充 ready。单次后台输出最多 4000 tokens（含供应商计入的思考部分），自由会话结构无效不自动重试。复盘只看真实输出，不重复全书分析，同样使用有限预算。

缓存键新增已读末尾与格式版本，旧整书 analysis 由 `full_analysis_cache_key` 保留；局部材料切回全书可恢复原付费资料。SQLite/WAL、按操作事务、长期 asyncio worker、独立 provider 保持不变。低词项召回与模型固有知识的剧透风险仍需实测，不宣称零幻觉。见 Decision 0018 与[自由聊天记录](../validation/text/FREE_CHAT_2026-10-28.md)。下文较早的题库及整书汇总实现作为兼容/历史说明，不再是默认桌面流程。


## 本地缓存与可恢复历史（2026-10-28）

真实长篇迭代补充：相同来源/profile 的完整材料在换模型后重复导入也保留原资料，显式重新分析才按新模型的独立缓存处理。讨论 system 指令约束口语节奏、异议/改口和按需引用；仅前台包把持久化章节 UUID 映射成有序编号，数据库来源标识不变。UI 类别归并为有界中文标签，不改领域原始分类；自定义题准备成功才进入新会话页。

文本网络使用按角色独立的 HTTPX AsyncClient，推理最多 4 个、对话最多 2 个连接，空闲保留 120 秒并随 provider 关闭。保留 HTTPX 系统代理处理；避免后台取消关闭对话池的连接。localhost HTTP/1.1 已验证超过默认 5 秒后的复用，线上 Flash SSE 仍出现每轮建连，不能据此宣称实际延迟改善。模型首字/完整计时与 UI 按键至显示/结束计时分别保存。

继续采用标准库 SQLite，无独立缓存服务、ORM 或云数据库。按操作连接和事务适配后台 worker，启用 WAL。新增 `preparation_cache` 表（键、原文哈希、更新时间、分析 payload）及按材料/更新时间的会话索引，启动时幂等创建，旧 JSON 通过默认值兼容读取。

应用层生成缓存键：原文 SHA256、标题、源语言、完整学习 profile、provider 公开身份、准备格式版本。OpenAI-compatible 身份仅包含服务地址与推理模型，不含 API Key；轮换密钥或切换 Flash 不使整书准备失效。`LearningMaterial.analysis_cache_key` 关联已使用缓存，旧数据默认空。完整缓存优先于部分进度，部分缓存按位置/哈希合并。重复导入匹配原材料 ID，复用资料和最近会话；不完整结果等待显式继续整理。

历史按材料查询全部线程，选择旧会话同时恢复材料/profile/runtime，不更新业务时间。完成线程只读。启动恢复最近材料与会话，QML 直接展示会话页；线程草稿仅在 ViewModel 内存保留。确认发送的用户与完整助手回复由同一 runner 保存，预测不作为消息。无 AI 配置时使用明确报错的只读 provider，不能清空已有准备，也不产生模拟回复。

实机探针 `scripts/desktop_session_probe.py` 以可见 Windows 窗口、正常应用数据库和 Qt 输入事件验证，不直接写入对话。开发 mock 测试使用独立临时库。一般模型调用默认 240 秒 wall deadline，整书汇总单独 600 秒，后台预测仍有 45 秒外层截止，前台 Flash 不等待整理。

## 2026-10-28 整本小说验证增量

用户提供真实长篇 EPUB 后，材料准备采用分段索引和整书汇总两层。120000 字符以内仍每段最多 12000 字符，长篇每段最多 24000 字符；默认材料预算提升至 1000000 字符。真实 provider 默认并发 3 段，可用 `LINGUALOOP_PREPARATION_CONCURRENCY` 设置 1–4。每段 Pro 使用 thinking+low、16000 tokens（明确截断时仅再以 24000 重试一次），生成简短概要、事件、人物和 2 个有来源的话题；随后 Pro 以全部有序段落笔记做 low/24000 的整书汇总（明确截断时最多以 32000 重试一次），贯通开头、中段和结局、合并人物并生成跨章节话题。最终最多 60 题，整书题优先，其余按章节轮询。

段落可乱序完成，持久化按原文位置排序；失败会取消仍在运行的段落请求。重试按边界和内容哈希复用已完成段落及其稳定 ID。整书汇总失败保留所有段落并保持 `preparation_complete=False`；成功后新增 `overview_complete=True`。全部段落未变且整书汇总已完成时可复用概要；旧数据该字段默认 False。取消已发送请求不代表供应商停止计费。

Flash 的实时上下文新增本地 `dialogue_knowledge`：只在预先保存的段落话题、要点、人物和引文中按当前发言及近期线程选参考，不在前台调用 Pro 或扫描整本原文。词匹配仍会漏掉转述，因此稳定背景另外包含整书概要、大纲和最多 48 段的简短章节索引；超过时均匀抽样并标明范围。本次 30 段全部包含。稳定背景放在动态资料前，便于兼容服务复用 prompt 前缀缓存。保留最近十条消息及少量早期读者观点；观点明确标为历史，当前改口优先。后台小任务也选择当前交流相关的准备资料，避免一直拿原话题第一个分支。回答倾向两句，具体回应读者的疑问或异议，不强制每轮提问。首字、完整模型回复和应用端到端计时必须区分，1 秒仍是优化目标。

真实整书调用与读者式讨论使用 `scripts/validate_novel.py`，显式要求 `--real` 和 `RUN_REAL_AI_TESTS=1`。本地数据库含原文和确认的会话，必须放在忽略目录；报告只记录覆盖和运行元数据。当前验收结论见 Roadmap 与后续真实小说验收记录。

## 2026-10-24 文本优先增量

当前阶段先独立验收纯文本，再实现 LiveKit 连续语音；既有 Qt 分轮语音保持可用但不作为此阶段的验证前提。主要业务入口为材料和对话。

- `application/material_preparation.py` 按不超过 12000 字符分块处理全材料，按块保存结构化结果与 SHA256，失败后重试复用同语言配置和相同哈希的块。默认 360000 字符预算由 `LINGUALOOP_MAX_MATERIAL_CHARS` 配置，超限显式提示分卷且先保存原文。
- `MaterialAnalysis` 扩展 `outline/characters/chunks/preparation_complete`，`DiscussionTopic` 扩展 `category/answer_branches`，保持旧 JSON 默认值兼容。分支包含可能的用户意图、回答要点、建议短回复、追问和精确原文引用。最终话题预算 60，按章节轮询保留。
- 自定义话题从全部块 payload、摘要和已保存原文按词/日中字符 n-gram 相关性挑选，提取命中附近 600 字符窗口，并附均匀分布的全书概览；明确 selected chunk 标识、起止位置和概览是否抽样。新话题 `source_chunk_ids` 保存引用的章节来源，不借前 60 话题代表全书细节。
- `OpenAICompatibleLLMProvider` 将 Pro 思考角色与 Flash 非思考角色显式拆开。DeepSeek 的全局旧 `DISABLE_THINKING` 只影响对话默认值；原始推理链不进入数据库或 UI。
- 前台 `stream_reply` 仅调用 Flash，收到内容块通过回调进入 UI，不把整本原文传入每轮；使用预制话题、可用预测准备和最近六条消息。Runner 只在流成功结束后提交完整消息，模型 TTFT/总时间单独存入助手消息 metadata。
- Workbench 在单一 asyncio worker 中调度 `prepare_dialogue`。每会话上限 12 次、45 秒超时、异步锁保证一个后台推理任务；新 revision 取消旧任务并验证代际、会话标识和消息数量。预测保存在 `session.preparation`，不加入用户消息。取消后的晚到结果被丢弃；失败不阻塞 Flash。
- 新生成结构由 core 的严格准备校验在 provider 和应用层双重检查：后台必须有非空意图、回答要点和精确来源；新材料/自定义话题必须至少有一个完整有效分支。部分无效分支剔除，全无效或缺失字段最多进行两次格式尝试；失败保留旧有效准备并显示 unavailable。历史 payload 默认空字段继续可读，不因此把无效新结果标为 ready。
- 前台消费历史准备时再次校验；无效旧 snapshot 仍可读取，但不注入 Flash。证据通过集中数组与分支索引去重、近期消息省略持久化 UUID/重复当前发言，输出上限保持 160 tokens。后台 Pro 显式 low effort、4000 tokens，输入收缩到当前题、少量候选/要点、单引文、最近两条发言；输出单意图、至多两短要点和一个精确引用，模型输出后映射原领域结构。分析 high、24000 tokens。每次非流式调用默认 240 秒 wall deadline，单次全材料运行默认 1800 秒总预算；两者可配置，超时保留完成块。
- DeepSeek 构造使用同一 `langchain-openai` 包的 `BaseChatOpenAI`，避免 OpenAI 专用子类将预算字段改名为 `max_completion_tokens`。真实 wire 使用官方 `max_tokens`；离线 httpx transport 验证 high/24000、low/4000 与 Flash/160 的请求体及 thinking 参数，泛 OpenAI 路由继续原适配。
- `provider/workbench.preparation_diagnostics` 只暴露 finish_reason、tokens、耗时、失败阶段和请求预算，不含文本或 CoT。明确 length 时不重复同预算请求；其他结构失败至多两次，依然受单任务 45 秒限制。测试/有界验收可通过 settings 的 `background_max_attempts=1` 限制格式尝试，不能因此宣称线上后台已通过。
- 新会话前台不做 Pro 纠错，结束后根据已确认用户输出汇总；历史 immediate 配置在新讨论中同样延后。旧直接 runner 无 options 的语义保持兼容。
- 导入扩展为 EPUB、Excel XLSX（openpyxl 只读缓存值）和带同名字幕的视频。EPUB 依据 spine，视频仅读字幕，不宣称理解画面。

这些是本轮实现边界，真实文本质量和完整回复低于 1 秒的性能目标仍需真实 HTTP 验证；流式首字指标不能代替完整回复性能。详见 [技术决策 0012](../decisions/TECH_DECISIONS.md)。

## 初始架构目标

第一版架构应支持快速验证产品闭环，同时保留 LLM provider、存储层和前端形态的替换空间。不要为了早期 MVP 引入过重的分布式架构。

当前产品主线见 [Project Brief](../product/PROJECT_BRIEF.md)：沉浸材料理解、话题选择、语音讨论与轻量复盘。已有话题和分轮语音实现；真实语音验收状态见 [初版验证记录](../validation/mvp/INITIAL_VERSION_2026-10-24.md)。下文插件注册和完整 Kernel 合约仍包含目标架构。

核心和 agent kernel 采用 Python-first 方向。前端形态仍可独立选择，但领域模型、Pattern、Plugin capability、Agent Kernel 和第一批 provider adapter 应优先用 Python 编写。

## 建议模块边界

```text
apps
  web app
  desktop / Android QML surfaces

client
  UI components
  conversation view
  material editor
  review dashboard

QML UI
  Python QObject ViewModel
    LearningWorkbench
      Kernel / Provider

application
  material analysis use cases
  topic suggestions and selection
  practice session orchestration
  feedback and review generation

agent-kernel
  PatternRunner
  CapabilityRegistry
  AgentEngine protocol
  SessionCoordinator
  GraphCompiler

engine-adapters
  LangGraph adapter
  direct deterministic runner for tests

domain
  learning material
  practice session
  feedback item
  review item
  user preferences
  pattern contracts
  session event schema

plugin-runtime
  plugin manifest
  capability registry
  lifecycle hooks
  permissions and configuration

infrastructure
  persistence
  LLM provider adapters
  auth adapter
  telemetry / logging

plugins
  voice providers
  avatar renderers
  importers
  LLM / STT / TTS providers

patterns
  topic discussion
  roleplay
  shadowing
  retell
  socratic
  spaced review
```

## 插件化原则

LinguaLoop 应采用 `fixed learning core + optional plugins + capability-aware patterns`，而不是把整个产品设计成 `everything is plugin`。

Core 负责定义学习语义、状态机、事件日志、Pattern contract、capability contract 和结构化输出。Plugins 负责扩展可选能力，例如语音、Live2D、材料导入、LLM/STT/TTS provider。Patterns 负责组织学习流程，并通过 capability requirements 声明自己依赖哪些插件能力。插件不得绕过 core schema 直接改写用户学习数据。

这里的可选表示底层实现可替换、不同 Pattern 可声明不同要求。正式 MVP 的语音讨论必须具备语音能力，不能因插件尚未接入就按文本路径宣告完成。

详细设计见 [PLUGIN_ARCHITECTURE.md](./PLUGIN_ARCHITECTURE.md)。Pattern 分类见 [LEARNING_PATTERNS.md](./LEARNING_PATTERNS.md)。Core 对象和基础概念见 [CORE_CONCEPTS.md](./CORE_CONCEPTS.md)。

Agent kernel 详细设计见 [AGENT_CORE_ARCHITECTURE.md](./AGENT_CORE_ARCHITECTURE.md)。

## Agent Kernel 原则

LinguaLoop 的核心 agent 不是一个自由规划的大 agent，而是一个领域化学习流程执行器。它不负责像 Codex 或 Claude Code 那样自主解决任意任务；它负责执行可声明、可测试、可复盘的语言学习 Pattern。

系统的灵活度主要放在 Pattern 层：Pattern 固定练习模式、语境、纠错强度、输入 modality、结束条件、复习项生成和复习节奏。Kernel 负责执行 Pattern、检查 capability、调用 provider、记录 `SessionEvent`，并把输出沉淀为 `FeedbackItem` 和 `ReviewItem`。

当前桌面与 CLI 采用 direct deterministic runner，复用原有 LangGraph adapter 作为独立实验路径；本次不迁移编排引擎。Core 不依赖 LangGraph，未来引擎可替换。LinguaLoop 自己负责领域模型、Pattern contract、capability registry、权限和事件语义。

## 当前桌面执行边界

- QML Material 页面 → `LearningViewModel` → `LearningWorkbench` → deterministic runner → 可替换文本 provider。
- `core/voice.py` 定义 STT/TTS protocols，`providers/speech.py` 使用独立环境配置调用兼容音频端点，业务不依赖供应商 SDK。
- `desktop/audio.py` 的 Qt capture/player 和所有 UI 对象留在主线程；`desktop/worker.py` 复用一个线程与 asyncio loop，通过 queued signal 交付结果并在退出时取消/释放。
- SQLite 每个操作创建连接及事务，材料先保存再分析。会话、反馈和复习项在本地保存；QSettings 保存外观与新会话偏好。录音只保留在临时文件及内存，不进业务数据库。
- `PracticeSession.topic/options`、`LearningMaterial.profile/subtitle_cues` 和 `MaterialAnalysis.topics` 使用兼容默认值读取旧数据；旧会话 options 为空时保留原有语义。

选择与影响见 [Decision 0011](../decisions/TECH_DECISIONS.md#decision-0011-md3-桌面与独立分轮语音实现)。

## 学习材料生命周期

经验工作区显示，输入材料在进入练习前需要经历清晰生命周期，而不是从用户粘贴文本直接跳到对话：

```text
RawSource
  -> NormalizedMaterial
  -> LearningSegment
  -> PracticePlan
  -> PracticeSession
  -> FeedbackItem / ReviewItem
```

- `RawSource` 保存用户导入或粘贴的原始材料。
- `NormalizedMaterial` 表示去除字幕编号、时间戳、重复 cue、断行和明显噪音后的 lesson-ready text。
- `LearningSegment` 是可教学片段，带有 `track`、`start_ref`、`end_ref`、`scene_or_argument_summary`、前后文摘要等元数据。
- `PracticePlan` 由 Pattern 生成，决定本轮怎么练。
- `PracticeSession` 聚合当前会话状态，但长期事实应由 `SessionEvent` 保存。

这个生命周期支持后续材料导入插件、不同 track 的切分策略，以及 review 时不必重新读取完整原材料也能恢复语境。

## 学习证据与状态

LinguaLoop 不应把“内容展示过”当成“学习者掌握了”。学习状态只能由真实表现证据推进：用户回答、冷启动输出、纠错结果、复习结果、延迟检索结果和用户控制动作。

因此持久化层应区分：

- `SessionEvent`: 发生过的事实，是可回放学习历史。
- `FeedbackItem`: 从用户输出中产生的纠错证据。
- `ReviewItem`: 未来要重新检索或迁移使用的任务。
- `LearnerProfile`: 从历史证据汇总出的当前快照，不是唯一事实来源。

详细方法依据见 [Learning Loop Foundation](../research/LEARNING_LOOP_FOUNDATION.md) 和 [Practice Workspace Findings](../research/PRACTICE_WORKSPACE_FINDINGS.md)。

## LLM 编排原则

- Prompt 不应直接散落在 UI 组件中。
- Provider adapter 返回结构化结果，业务层负责校验和回退。
- 每个 LLM 任务应有明确输入、输出 schema 和失败策略。
- 对话消息、纠错项和复盘项应能关联回原始材料或会话片段。
- PydanticAI 可作为第一批 typed LLM call adapter，但不要让业务层直接依赖 PydanticAI agent 对象。

## QML UI 边界

桌面端和 Android 端使用 PySide6 加载 QML。Qt Quick Controls 6 提供基础控件，Kirigami 提供 ApplicationWindow、Page、导航和响应式布局。QML 不接触领域模型、LangGraph 或具体 provider；Python ViewModel 将领域对象转换为稳定的字符串、列表和状态属性。

材料、练习和复盘是独立页面。桌面端可以使用更宽的上下文区域，移动端使用单列 PageStack/滚动布局。网络操作必须在 Python worker/thread 中执行，ViewModel 通过 busy/error/result signals 更新 QML。

## 语音与实时对话

LiveKit 是 `voice-livekit` 插件的强候选 SDK，而不是项目总基座。Core 只依赖 `VoiceSessionProvider` / capability 抽象，语音插件内部处理 WebRTC、turn detection、interruption、STT-LLM-TTS pipeline、实时转录和延迟指标。依赖语音的 Pattern 只声明 `voice.session`、`stt.transcribe` 或 `tts.speak`，不直接绑定 LiveKit。

基础语音进入正式 MVP 的关键路径：材料理解与话题选择之后，用户能多轮说话并收听 AI 回复。文本保留为原型、辅助输入与故障回退；连续实时双向语音、复杂打断和更完整的遥测作为后续增强。具体 provider 和交互形式待验证，本次不新增 SDK 依赖。

语音输入与回复仍进入同一学习会话和证据链。识别文本应允许用户修正，不能把识别错误直接当成语言错误；仅有 transcript 时不诊断发音，原始录音也不作为复盘的必要存储项。

## 关键用例

- analyzeMaterial(material): 生成语境摘要、可聊话题及来源关联，按需提供关键词、表达点和练习建议。
- startPracticeSession(material, goal, preferences): 根据所选或自提话题创建讨论会话，可显式选择 roleplay；话题与语音元数据的最终 schema 待定义。
- continueConversation(session, userMessage): 生成下一轮 AI 回复和可选反馈。
- summarizeSession(session): 生成复盘和 review items。
- startReview(language, profile, reviewQueue): summary-first 地选择 1-3 个复习方向，而不是直接倾倒所有过期条目。
- recordLearningEvidence(session, event): 把用户输出、反馈、复习结果和用户控制动作保存为可回放事件。

## 数据与隐私

- 用户导入的语言材料可能包含私人内容，默认按敏感数据处理。
- 日志中不得记录完整原文、完整对话或密钥。
- 若后续支持云同步，需要明确数据保留、删除和导出机制。
- 本地开发应使用 `.env.example` 描述环境变量，不提交 `.env`。

## 当前本地持久化

MVP 运行时持久化采用标准库 `sqlite3`，不引入 ORM。SQLite adapter 保存材料、会话、review queue 和 `SessionEvent` 的 JSON payload，Core 仍只依赖 `EventStore` 等协议，不感知数据库实现。

默认数据库路径为平台应用数据目录下的 `LinguaLoop/lingualoop.sqlite3`，可通过 `LINGUALOOP_DATA_DIR` 覆盖。JSON 导出保留为迁移和备份能力，不作为主运行时存储。

当前导入器支持 `.md`、`.markdown` 和 `.docx`。导入流程保留 raw content，同时生成 lesson-ready normalized copy；Google Docs 在线授权、旧式 `.doc`、PDF 和视频导入不进入第一阶段关键路径。

## 待定架构问题

本地语音的可选目录、硬件准入、下载与计算测速位于独立 `lingualoop.local_speech`。桌面模型库使用单个后台管理线程，推理由有界独立 Python 进程运行，Qt/音频播放器留主线程；模型与数值报告用本地文件缓存，不增加数据库或云服务。当前尚未将该运行时连接到 Core 语音 ports / LiveKit；边界与下一阶段见[本地语音指南](../desktop/LOCAL_SPEECH.md)。

- 前端是否采用 Next.js、Vite SPA，还是其他形态。
- 后端是否采用同构应用 API routes、独立 API 服务，还是 BaaS。
- SQLite payload store 何时升级为更细粒度查询 schema 或 repository 层。
- 是否从第一版就支持多 LLM provider。
- 插件 manifest、权限模型和版本兼容策略如何设计。
- Pattern manifest、capability requirements 和 fallback 策略如何设计。
- 基础语音采用哪个 provider，以及 `voice-livekit` 候选如何满足 MVP 的延迟、成本与交互要求。
- LangGraph adapter 在 MVP 中何时替换 direct deterministic runner。
