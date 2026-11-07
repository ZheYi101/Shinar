# Technical Decisions

<a id="decision-0036"></a>

## Decision 0036: 原文对照区采用 foliate-js 与离线 WebEngine

- Status: Accepted（用户授权更换；已接入正式阅读区，安装器整包复验另列）
- Date: 2026-11-06

背景：用户反馈内置阅读器排版差、分段观感不均，要求研究复用外部成熟组件，服务现有聊天旁原文对照的 sidebar idea。当前 EPUB 导入把 XHTML 转成纯文本，再由 QML `TextEdit.PlainText` 展示，丢失真实目录链接、书籍样式和大部分语义结构。

选择：保留 Python／QML 主壳，用 Qt Quick WebEngine 嵌入固定提交的 foliate-js；复用其 EPUB／重排／定位能力，现有工作区继续管理同一会话、选段、已读范围和历史快照。原 EPUB 原子保存到所属数据库旁的 `.assets/sources/`；显示副本保留静态段落／标题／行内语义和本地图片，以当前规范化文本逐字符投影生成位置 span，完全相符才启用。统一书页样式覆盖出版者 CSS；不把原文重新切成等长块。旧材料和历史不静默迁移，不能精确对齐、原件缺失或固定版式时回退文本。

影响：锁定 commit 并随包分发 JS、MIT／BSD 许可证；WebEngine 按需创建视图，使用临时 profile、文件白名单和 CSP，不新增本地服务器、CDN 或模型请求。中日文字体通过 CSS 加载；DOM UTF-16、元素端点与 Python 字符范围显式转换。线程／路由／请求身份共同拒绝旧页面回调，原模型授权边界不变。源码资源随 wheel 检查，Windows 分发探针增加 Chromium 二进制／资源检查。

维护契约：WebEngine 只作为局部显示适配，不承接会话、授权或模型业务；来源处理保持无 Qt，专用桥接不开放通用调用。固定上游模块与许可的完整性及导入范围纳入普通架构测试。现存 workspace 加载组合、Workbench 资产目录耦合和后续抽取的触发条件维护在[阅读器架构](../architecture/READER_ARCHITECTURE.md)，总依赖见[系统架构](../architecture/ARCHITECTURE.md)；这些计划不冒充已完成的 service／repository 拆分。

验证：已在可见 Windows Mock 工作区完成鼠标拖选／原生复制／键盘扩选、选段发送和历史预览，以及分栏拖动、查找定位、中英日文、明暗／窄窗、边界标记和移走原件后的打开。483 项普通回归与 132 项 wheel 资源检查通过；离屏 WebEngine 截图在本机可能空白，不作为视觉证据。实现、复现、适用范围与完整安装器未复验的限制见[阅读器指南](../desktop/READER.md)和[集成记录](../validation/engineering/READER_INTEGRATION_2026-11-06.md)；[初始选型](../research/READER_ENGINE_SELECTION_2026-11-06.md)保留研究过程。

<a id="decision-0028"></a>

## Decision 0028: 纸墨叶控件采用 Qt Basic 定制，根窗口保留 Material

- Status: Accepted（浅色视觉复核实现）
- Date: 2026-10-29

与修订 3 页面稿逐页比对后，发现 Material 默认按钮内缩令 36px 热区只呈现约 24px 背景，输入提示浮在边框上，默认开关／下拉框与纸墨方向不一致。按 Qt 官方控件定制方式，保留现有 Material 根窗口、PySide6 6.11.1 和 QML，在 `MButton/MTextField/MTextArea/MComboBox/MSwitch/MSpinBox` 内采用 Qt 自带 Basic 控件并显式控制表面、内容和指示器。没有新增前端栈、StyleKit、服务或运行时依赖。

设置行、主题预览和材料页头抽为可复用组件；聊天操作并入标题栏，原文使用独立浅纸分区，表单顶部排布。翻译标记、原生文本编辑／输入法与选区、键盘交互、旧业务／语音边界继续保留。深色保持基础兼容，视觉定稿仍另做。方案依据与实际检查见[视觉复核记录](../validation/engineering/UI_VISUAL_REVIEW_2026-10-29.md)。

<a id="decision-0027"></a>

## Decision 0027: 中文先行的 Qt 国际化入口与独立学习母语

- Status: Accepted（中文资源与国际化入口已实现，其他语言包后续）
- Date: 2026-10-29

依据用户追加要求，界面文案通过 `qsTr`／`QCoreApplication.translate` 标记，动态提示使用占位符，使用 TS/QM 标准资源机制，不引入前端框架。`displayLanguage` 与学习领域的 `nativeLanguage` 分开保存。本版本默认中文，系统语言无已交付资源时回退中文；`QLocale.system().uiLanguages()`、语言包加载和首次母语建议已经预留。未来增加语言包后再将首次默认改为跟随系统，并只给尚无显式偏好的学习母语提供建议，不覆盖历史 profile。

影响：翻译资源随 wheel 分发，翻译提取可离线复现；切换界面语言不重开线程、不改原文／草稿／消息、不清理语音。应用层与 core 不导入 Qt，既有业务异常与语音目录说明的完整多语言迁移须通过边界代码和参数完成。具体接口、当前覆盖与扩展步骤见[国际化说明](../desktop/I18N.md)。

本轮同时完成工作区的摘要投影、开场草稿零自定义题调用、范围返回保留输入、请求过期隔离、IME 保护与浅色 QML 验证，见[UI 实施记录](../validation/engineering/UI_IMPLEMENTATION_2026-10-29.md)。深色视觉定稿、其他语言翻译与连续真人语音仍为后续范围。

<a id="decision-0026"></a>

## Decision 0026: 暖纸 QML 工作区与独立桌面状态

- Status: Accepted（首批实现；最终视觉与真人连续语音未验收）
- Date: 2026-10-29

在 Decision 0020–0022 的交互与暂定视觉方向上，保留 PySide6/QML/Material 技术栈，引入 `DesktopWorkspaceController` 管理页面、浏览材料、每线程草稿和原文视图；业务记录继续通过 Workbench 和 SQLite。按材料组织多段对话，导入与范围核对在主区完成，设置按类别排列。

来源定位使用稳定字符范围及 Qt UTF-16 映射；发送时冻结快照，历史回看不覆盖当前选区。已有 Qt 分轮语音和模型/计算设置保留，不因重构就宣称已接入基础语音协调器或连续麦克风。

内置中日文字体、OFL 许可、原创图标及来源记录随 wheel 分发。完整离线回归与隔离安装资源检查通过，说明见[工作区指南](../desktop/WORKSPACE.md)及[合并检查](../validation/engineering/WORKSPACE_INTEGRATION_2026-10-29.md)。设计稿中未覆盖细节、真人连续语音和最终视觉确认仍单独验收。

## Decision 0024: 基础 Python 语音、确认事务与可验证本机 RTC

- Status: Accepted（Python 基础实现；未接 QML/持续设备音频）
- Date: 2026-10-29

用户确认先实现无 UI 的录音转写、确认发送、分句合成、失败重试和真实本机 RTC，暂缓 VAD/AEC/插话等高级功能。作为 Decision 0023 总体蓝图的基础增量，沿用 deterministic Workbench/runner 与可替换语音端口，不引入 Agent 框架。

确认与生成分开：SQLite schema 2 以会话/request ID 唯一 turn 先原子保存确认用户，再原子保存完整助手/事件；attempt 比较和有界租约拒绝旧提交。runner 保留直接调用兼容，Workbench 的旧 send_message 包装新流程。上下文按确认前历史冻结，当前用户只包含一次；双角色预算、后台版本判断与显式核验仍在原入口，语音不复制一套推理编排。

语音协调器输出真实格式的分句 WAV；可见文本读取不等待 TTS。目录选择在本轮绑定一次，固定运行时/静态加载 key 复用模型，注册的额外后端需验证本地资产、运行时和必要条款。VOICEVOX 与独立 Melo 英文先交付 Python adapter，不据此宣传 GUI 下载或发行安装已完成。

在用户明确允许后，扩展 Decision 0013 的探针网络边界：信令仍 loopback，媒体与真实 STUN responder 可绑定一个 OS 所属私网 IP；不 wildcard、不修改防火墙、不使用公共 STUN/TURN。修复对端 active 等待和退出重入的新 Room。已结束 WAV 走可靠字节流，回复走真实 PCM 轨；原始持续麦克风分轮留后续。

影响：普通 pytest 不启动重模型/RTC，真实集成分别显式开启；完整链路使用 Mock LLM＋真实本地语音，不产生付费请求。纯 loopback 历史失败、冷启动和 UI 未验收独立保留。实现、复现与剩余项见 [Python 指南](../desktop/VOICE_PYTHON.md)和[基础验收](../validation/speech/VOICE_PYTHON_INTEGRATION_2026-10-29.md)。

## Decision 0023: 统一语音会话、按语言模型与可取消播放的接入提案

- Status: Proposed（完整实现方案待评审；不改变已交付能力）
- Date: 2026-10-29

背景：本地模型/CPU-GPU 实测与首批分轮适配已经形成，但 Qt 仍以 WAV 录放音为主；单一 busy/完成回调不适合持续收音和插话，LiveKit 最后一次真实连接仍未通过。用户要求将实际 TTS/STT 接入展开到功能与模块逻辑。

提案：采用 VoiceSessionCoordinator、Qt PCM 音频桥、独立 AudioSessionWorker 和模型进程，复用现有对话角色、后台准备及 LiveKit adapter，不新增 Agent 框架。按语言分别选择模型；对实测显著加速的配置推荐 GPU，CPU 备份须独立通过速度/质量门。STT 热态平均计算沿用 ≤500ms 的筛选，端点到转写/出声另测。LLM 增量按可说短句合成，连续音轨播放；打断先关代际门与清播放，再取消计算，保留新输入。模型资源由一个监督器预约、预热和释放。

拟调整的产品/存储语义：非原生 partial 的离线 STT 可在连续音频上端点分轮；自动发送由用户显式开启；已确认用户先事务保存、完整成功助手再保存，取消/失败半流不进成功历史。上述均为本提案内容，未修改现有 MVP 或实现为已接受状态。具体事务、最小 turn 表、接口、文件落点、故障矩阵、分期出口见[完整接入方案](../architecture/voice/SPEECH_INTEGRATION.md)。

影响与待验证：中文 Melo GPU、VOICEVOX/独立 Melo 英文产品 adapter、全新 GPU 环境与冻结发行分发须分别验证。GPU 预算是软预算，不承诺使用率百分比。真实 RTC 是正式连续语音的独立门，Mock/开发直连不替代；扬声器 AEC、真人三语、真实打断和一秒目标仍待验收。现有 Qt 分轮、云语音端口和文本回退保留。

<a id="decision-0022"></a>

## Decision 0022: 材料内组织对话与紧凑页面布局提案

- Status: Proposed（用户方向已明确；逐页布局为首轮稿，待评审，未实现）
- Date: 2026-10-29
- 统一文档：[总体布局与逐页 UI 稿](../product/UI_LAYOUT_DESIGN.md)。

背景：用户要求以材料为源组织多段对话，缩减宽侧栏，参考所附截图的设置分类与行式内容，并将读后对照功能纳入总 UI。评审中进一步要求删除抒情短句、压缩标题区与重复说明，避免浪费页面空间。

提案：材料树中展开会话，主区提供材料库／材料空间／对话；表达复习与设置为辅助入口，未来功能仅在“更多”预留。侧栏建议 208px 并可收起为 56px；设置按外观、学习、服务、设备、本地语音和数据分组。修订 2 按用户评审删除重复页标题、面包屑和材料树图标，顶部只留操作与收起时必要上下文；原文目录／定位／搜索使用按需浮层，不压缩正文；导入与范围弹窗删除常驻解释，按选择展示控件。输出 25 个视图、交互参考与 6 个原创图标母版，不将原型当成 QML 或真人语音验收。

修订 3：用户认为表单弹窗仍拥挤，要求先参考网上设计。查阅 Carbon、GOV.UK 与 Readwise 官方资料及公开示例后，将普通导入与“更多”改为主区页面，已读范围改为材料内的原文核对页，保留字段间距、返回路径与未提交输入。直接点选末段是新增待评审入口；聊天原文指向与阅读边界继续分开。扩展为 30 张状态稿，依据与未核验范围见[外部设计参考](../product/UI_DESIGN_REFERENCES.md)。系统文件选择器与轻量导航菜单不在普通表单弹窗禁用范围内；应用仍未迁移。

影响：后续不再照搬两个独立主入口加混合来源“最近对话”的旧外壳。保留 Decision 0020 的同一会话、直接原文选择与语音连续性语义，保留 Decision 0021 的纸墨风格和 PySide6/QML 技术栈；像素、字段与具体分组仍可评审调整，不改业务配置或数据。

未解决：逐页布局确认、真实数据量下的材料树与长标题、各语音阶段、深色主题、Qt 命中区域／键盘／输入法／触控与安装包验证。未来练习、自制语音场景和声音工具不因布局预留而进入已交付功能范围。

<a id="decision-0021"></a>

## Decision 0021: 暂定暖纸与墨迹的视觉方向

- Status: Accepted（用户暂定的视觉基线；具体 UI 待讨论，尚未实现）
- Date: 2026-10-28
- 统一文档：[视觉风格设计：暖纸与墨迹](../product/VISUAL_STYLE_GUIDE.md)。

### 背景

用户希望 LinguaLoop 更有书香味与读后聊天的感觉。三版探索中，用户认为浅色旧书页更舒适，要求去掉紫色并吸收复古手账元素；随后指定最新融合图暂定风格，先记录详细文字、参考图、配色与可复用图标生成语言，具体 UI 后续单独讨论。

### 选择

以浅暖纸、深褐墨迹、少量灰绿和克制手账装饰作为视觉基线；保留舒展的文字与留白，纸条、纸胶带、淡印章和布面书只作为局部辅助元素。归档完整参考图，提供建议色值、候选字体及功能小图标／辅助插画的独立生成模板。HEX 与字体为设计默认值，不声称生成图使用了精确色值或实际字体文件。

### 影响与替代关系

本选择替代 Decision 0011 中紫色 MD3 外观作为后续视觉默认要求的部分；现有 MD3 实现保持原状，PySide6/QML、线程、数据和资源分发约束继续有效，不引入新 UI 框架。概念图不固定三栏、语境卡、导航宽度或功能入口，也不替代 Decision 0020 的读后对照交互。本次只修改设计文档与参考资产，不启动应用、不调用业务模型、不改变其他任务范围。

### 未解决问题

具体页面与组件布局、连续语音状态、全部交互状态、深色主题、最终字体和图标生产仍待专项设计与验证；本轮色值的纯色对比检查不等于 QML、实机或安装包验收。独立图标尚未生成，正式资产仍需整理、许可记录与实际尺寸检查。

<a id="decision-0020"></a>

## Decision 0020: 读后对照聊天与直接选择交互

- Status: Accepted（功能交互基线；总 UI 待整合，应用实现与实机验收未完成）
- Date: 2026-10-28
- 统一规格：[读后对照聊天功能设计](../product/CONVERSATION_WORKSPACE_DESIGN.md)。

背景：用户希望读完小说后再使用 LinguaLoop，保持轻量；同时希望像与朋友指着某一章、段或句子讨论，而不是管理阅读笔记。用户认可重做后的交互，要求形成颗粒级功能规格，供正在开展的总 UI 设计参考。

选择：默认直接聊天，按需展开作品，沿用同一会话和输入。选择章节即讨论该章；单击段落或完成文字选区直接聚焦，无需再点指定。清除细选回到本章，清除章节范围回到全部已读内容；原文选择不自动发送或调用模型。已发轮次冻结原文范围，历史预览与当前范围分开，布局变化不丢草稿或中断语音。

影响：替代早期交互草案中的选章后二次确认和每段常驻“指这段”按钮。总 UI 使用规格中的组件、状态和验收编号；外壳、比例、断点与视觉样式可统筹调整。规格和两张虚构材料原型参考图不代表当前 QML 已实现，不改变 Decision 0019 的独立 AI 机制任务范围，也不新增阅读引擎、云服务或数据库。

未解决：真实章节/选区锚点、窗口与输入法的实际行为、单击/滚动误触、版本恢复及真人连续语音中的范围时序，须由后续应用增量分别实现与验收。具体业务模型与存储方案不在本次文档任务中落定。

<a id="decision-0019"></a>

## Decision 0019: 全覆盖基础理解与按信息缺口协作

- Status: Accepted（机制已实现；质量／成本与完整延迟门禁尚未通过）
- Date: 2026-10-28
- 详细方案：[适量材料预处理与双模型协作](../architecture/ai/PREPARATION_AND_DIALOGUE.md)。

### 背景

旧版批量题库与拟答成本高，不能保证自然交流或完整回复一秒；随后默认零模型初始索引又缺少基础语义理解，真实评估发现归属与召回问题。用户先要求形成方案，随后明确批准落地并限定 100 次真实验证请求。

### 采用选择

对已确认阅读的全部授权内容做有限输出的分段理解，保留事件／主张、人物／概念、归属、歧义和来源依赖，合并短整体认识；不默认生成大量话题与回答。原文、材料事实、真实聊天记忆和临时解释分别管理。

常规前台仅由对话角色回应，本地装配整体认识、近期历史和当前依据；推理角色按信息缺口补足局部资料与必要记忆，不默认逐轮预测。材料事实按来源和范围复用，会话判断按新发言校验。范围不足允许取证慢路径，不为一秒目标编造或生成无内容填充。

### 影响与替代关系

保持 Python/Pydantic、SQLite/WAL、deterministic runner 和可替换 provider，不新增大型框架、云数据库或 embedding 服务。新增 `knowledge_artifacts / knowledge_cache_hits / model_budgets / model_calls`；旧准备缓存与历史不迁移为新的合格标记。单元／合并 4096、局部／记忆 2048 输出上限包含思考部分；请求前事务预留，未知用量保留预留，状态和额度跨重启。后台单并发、45 秒总限时和最新缺口合并。

本实现替代 Decision 0018 中“默认不做基础语义理解”和固定三次后台尝试作为主要策略的部分；保留自由聊天、阅读边界和不批量拟答。旧材料不因启动、历史切换或模型变化自动产生付费升级；显式继续／重新准备才运行。实现取代旧默认策略不等于对话质量已通过，不改变正式 MVP 的独立语音验收要求。

### 未解决与验证

完整小说与部分阅读、14 轮实际讨论、12 场景三条件结果和中日文检查已形成[本轮实测](../validation/text/SEMANTIC_PREPARATION_2026-10-28.md)。100 次请求后停止；发生事实失败，独立真人盲评和一秒目标未过。固定截短丢失关键结论已在最终检索代码修正并离线验证，但未追加真实复验。实际思考输出高于可见笔记，不能声称已证明费用下降。继续以事实／归属、异议与改口、自然结束、防剧透、费用和完整延迟分别判断。

编号整理说明：原文件两个 Decision 0015 中，准备缓存保留 0015，自由聊天修订更正为 0018；原选择内容保留，相关引用同步更新。

## Decision 0016: 真实读者讨论驱动前台节奏和连接池迭代

- Status: Accepted
- Date: 2026-10-28

完整小说实测发现自由类别产生几十种近义词、开场偏书面、部分轮次延迟明显。保留原始领域类别，由 ViewModel 映射为有界中文浏览类别；自定义题整理成功后才切换页面。口语节奏、回应异议/改口、可选追问与按需引用提升为 system 指令；全书简短背景不删减，只把前台用的章节 UUID 换为有序编号，来源 ID 继续持久化。

HTTPX 默认 5 秒空闲超时不适合读完再回复的节奏。采用角色独立 AsyncClient，推理池 4、对话池 2，空闲 120 秒，保持系统代理语义并关闭资源。共用一个池的实验会让后台请求占用对话连接，因此以角色隔离作为最终选择。真实 localhost HTTP/1.1 测试验证跨 5 秒复用和清理；线上最后三次 Flash SSE 仍各建连，没有证明线上提速。依据 [HTTPX 连接限制](https://www.python-httpx.org/advanced/resource-limits/)与[客户端复用](https://www.python-httpx.org/advanced/clients/)。

实际材料和 17 轮历史保留在正常应用数据库，完成 3 次复盘及中途重启恢复。用户改变本地模型配置后按请求重启，当前两角色均为 deepseek-flash，原 Pro 准备保留。1 秒为优化目标，完整回复实测未达成；所有慢轮次、后台失败与质量限制保留在[验收记录](../validation/text/NOVEL_ACCEPTANCE_2026-10-28.md)，不能以 mock 或缓存命中替代。

## Decision 0015: 同库准备缓存、可选历史与实机验收

- Status: Accepted
- Date: 2026-10-28

用户要求打开正常软件就能看到小说预处理和实际对话历史。继续使用标准库 SQLite，将准备缓存和业务资料放在默认应用数据库；启用 WAL、按操作连接/事务和材料会话索引，不增加缓存服务。缓存键按内容哈希、标题、语言/profile、推理服务/模型和准备版本隔离，排除 API Key，支持密钥轮换；`analysis_cache_key=None` 兼容旧记录。相同导入复用材料 ID，部分缓存等待显式继续，完整缓存不能被部分进度覆盖。

对话页提供按材料的历史选择，恢复旧线程不改变排序，完成线程只读，启动恢复最近会话。缺少有效配置时打开本地库，但在线操作明确失败，禁止自动生成 mock 回答。未发送草稿只在内存保留；材料、准备资料及确认消息本地持久化。

当前采用正常 Windows 应用目录。已有真实 Pro 准备可迁入同版本缓存，但小说必须通过实际窗口导入；实际对话必须通过控件输入/发送，不能用 fixture 填充用户历史。探针以 Qt 鼠标/键盘事件驱动可见 Windows 窗口，分别测量模型首字/完整耗时、UI 首文本/后续帧和发送至操作结束。缓存命中不能替代真实讨论质量。

整书汇总在实际调用中曾耗时超过 5 分钟，新增独立 `OPENAI_SYNTHESIS_DEADLINE_SECONDS=600`；一般非流式调用仍默认 240 秒，后台受 45 秒外层预算约束。这只允许长任务完成，不是对话延迟优化。数据库和相邻 WAL 文件含敏感材料/历史，均从 Git 忽略，备份先关闭应用。整书汇总成功、真实 Flash 历史及舒适性仍待服务可用后验证。

## Decision 0014: 以完整真实小说验证两层材料准备和读者式对话

日期：2026-10-28。用户提供完整《Lolita》EPUB，要求实际预处理后连续对话，并评价响应速度及读者体验；停止 orchestrator 与子 agent 工作方式，由主助手直接实现和验收。

原逐段拼接概要和首 300 字符实时摘要无法贯通长篇；8000 token 的 Pro 小任务在真实调用中多次 `finish_reason=length`，相同预算的重试仍截断。因此保留全书分段和逐段落盘，增加整书 Pro 汇总；段落采用更精简的两题结构、low/16000 输出预算，若明确截断只再以 24000 重试一次；普通结构错误仍至多两次。思考预算与最终 JSON 共享上限，不关闭推理模型的思考来冒充通过。默认最多并发 3 段，可配置 1–4；默认材料上限 1000000 字符，长篇段落最多 24000 字符。整书汇总原 high/24000 在真实调用中两次截断，改为精简重复笔记字段、Pro low/24000，明确截断时仅以 32000 再试一次；成功前禁止开聊。

新增 `MaterialAnalysis.overview_complete=False` 兼容旧数据；同边界和哈希的段落复用稳定 ID，全文未变且汇总完成才复用整书结果。失败、超时或取消保留已保存段落，取消其他请求；供应商已经接受的请求计费情况不能由本地取消推断。

快速模型只拿保存的准备资料：当前题、完整的简短整书概要、按本轮发言挑选的情节/人物、最近十条消息与少量早期读者观点。当前发言及改口优先于预测；后台参考也随实际话题变动。没有引入向量服务、额外模型或全文实时推理依赖。代价是词匹配仍可能漏掉隐含关联，需通过实际对话识别并迭代，而不是用引用存在性自动判定语义正确。

验收使用真实配置、完整 EPUB、持久化数据库及连续应用进程中的多轮交谈，分别计首字、完整模型回复和应用端到端时间；1 秒保留为优化目标。评价涵盖具体事实、人物动机、叙述可靠性、追问、分歧、改口、自然收束及重启恢复。质量不能由非空输出或结构通过代替。原文与会话只存本地忽略目录，提交文档只记录必要事实、问题和元数据。

本文档记录会影响长期维护的产品与技术选择。已接受的后续决策覆盖早期记录中的对应范围；当前产品主旨见 [Project Brief](../product/PROJECT_BRIEF.md)。Decision 0010 调整语音优先级与 MVP 边界，早期“文本 MVP 先行、语音后续增强”的表述仅保留为历史背景。

## Decision 0001: 先文档化范围，再脚手架化应用

- Status: Accepted
- Date: 2026-08-14

### 背景

项目仍处于产品和工程边界定义阶段。如果过早创建完整脚手架，容易把技术栈选择固化在尚未验证的产品假设上。

### 决策

先建立 README、AGENTS、MVP、架构和路线图等基础文档。后续在明确第一版交互形态、存储方式和 LLM 接入方式后，再创建应用代码。

### 影响

- 短期没有可运行应用。
- 后续脚手架应以 `docs/product/MVP_SPEC.md` 和 `docs/architecture/ARCHITECTURE.md` 为事实来源。
- 技术栈选择需要在本文档中补充新的 decision entry。

## Decision 0002: 采用 Core / Plugins / Patterns 三层扩展架构

- Status: Accepted
- Date: 2026-08-25

### 背景

项目希望支持语音、Live2D、不同学习 pattern、复习调度、材料导入、LLM/STT/TTS provider 等能力扩展。通用 agent harness 展示了 capability registry、plugin registry、event log 和 runtime adapter 等可借鉴的工程结构。

LinguaLoop 可以借鉴这种插件组合思想，但产品目标不同。LinguaLoop 的核心价值来自稳定学习闭环，而不是任意 agent 能力组合。学习 Pattern 也不应被混同为普通能力插件：Pattern 负责「怎么学」，Plugin 负责「能做什么」。

### 决策

LinguaLoop 采用 `fixed learning core + optional plugins + capability-aware patterns`。

- Core 定义学习材料、练习会话、消息、反馈、复习项、session events、Pattern contract、capability contract 和结构化输出。
- Plugins 是可用可不用的能力提供者，例如语音、Live2D、材料导入、LLM/STT/TTS provider。
- Patterns 是可组合的学习流程，例如 roleplay、shadowing、retell、spaced-review。Pattern 可以依赖特定 capability，但不直接依赖具体插件实现。

插件通过明确 contract 扩展能力，不能直接改写 core schema 或绕过学习状态机。Pattern 通过 capability requirements 声明运行条件。

Codex、Claude Code、DeepSeek Harness 等通用 agent 系统可以作为结构参考，但不作为 LinguaLoop 的总基座，也不定义 LinguaLoop 的学习流程。

### 影响

- 需要新增 `plugin-runtime`、`plugins` 和 `patterns` 的架构边界。
- 语音、Live2D、provider、importer 作为插件能力设计。
- 学习 Pattern 作为独立流程层设计，可声明对插件 capability 的依赖。
- MVP 仍先验证文本学习闭环，只实现最小 plugin registry、capability requirement check 和一个内置文本 Pattern。
- 插件权限、Pattern fallback、版本兼容、事件命名空间和 schema 校验会成为早期基础设施工作。

### 参考

- DeepSeek Harness architecture: https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md
- Cordis tutorial in DeepSeek Harness: https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cordis-tutorial/index.md

## Decision 0003: LiveKit 作为语音插件 SDK，而不是项目总基座

- Status: Accepted
- Date: 2026-08-25

### 背景

LinguaLoop 后续可能发展出口语 AI 对话、实时转录、用户打断、turn detection、流式 TTS、语音延迟指标等能力。LiveKit Agents 和 LiveKit SDK 适合处理实时音频、WebRTC、room/session、provider integrations 和语音 agent pipeline。

但 LiveKit 不定义 LinguaLoop 的学习材料、练习策略、复盘结构或复习机制。

### 决策

LiveKit 作为 `voice-livekit` 插件的底层 SDK / runtime dependency。Core 只定义 `VoiceSessionProvider` / voice capability 抽象，应用层和 Pattern 通过插件注册的能力使用语音会话。

```text
LinguaLoop core
  -> VoiceSessionProvider contract
    -> voice-livekit plugin
      -> LiveKit Agents / LiveKit SDK / selected STT-LLM-TTS providers
```

### 影响

- 文本 MVP 不被 LiveKit 复杂度阻塞。
- 未来可以替换或并存 OpenAI Realtime API、Gemini Live API、Pipecat 或其他语音方案。
- 学习领域模型不会被 room / participant / track 等实时通信模型污染。
- 语音插件需要单独追踪用户停说到 AI 出声、打断响应、STT partial 稳定性、TTS 首音频和单轮成本。
- 依赖语音的 Pattern 只声明 voice / STT / TTS capability，不感知 LiveKit 细节。

### 参考

- LiveKit Agents introduction: https://docs.livekit.io/agents/
- LiveKit model plugins: https://docs.livekit.io/agents/models/
- LiveKit turn detection and interruptions: https://docs.livekit.io/agents/logic/turns/
- LiveKit pipeline nodes and hooks: https://docs.livekit.io/agents/logic/nodes/

## Decision 0004: Python-first Agent Kernel with LangGraph Adapter

- Status: Accepted
- Date: 2026-08-27

### 背景

项目主语言倾向 Python。核心 agent 层需要支持 Pattern 执行、插件能力调用、结构化输出、可恢复会话、事件记录和后续语音扩展。

LinguaLoop 的 agent 定位不是通用任务 agent。它不需要像 Codex 或 Claude Code 那样理解和解决任意开放目标；它需要围绕用户输入材料执行稳定的 language learning loop：输入理解、任务化对话、即时纠错、复述输出和间隔复习。

因此项目可以手写自己的领域化 agent kernel。复杂度应集中在学习语义、Pattern contract、事件记录和 provider 边界，而不是构建一个自由规划的完整 agent harness。

### 决策

采用 Python-first 核心架构：

- Core 使用 Pydantic models 定义领域对象、事件、Pattern contract 和 capability contract。
- Agent Kernel 手写 `PatternRunner`、`CapabilityRegistry`、`SessionCoordinator`、`AgentEngine` protocol 和 `EventStore` interface，定位为领域学习流程执行器。
- 系统灵活度主要放在 Pattern 层；Pattern 决定练习模式、语境、纠错强度、输入 modality、结束条件、复习项生成和复习节奏。
- 默认 `AgentEngine` adapter 使用 LangGraph，负责 stateful workflow、routing、streaming、checkpoint / resume。
- typed LLM calls 使用 PydanticAI 或轻量 Pydantic provider adapter，统一包在 LinguaLoop 的 `TypedLLMClient` 后面。
- LiveKit 继续作为 `voice-livekit` 插件的 SDK，不进入 Core 或 Agent Kernel。

### 影响

- 不采用 DeepSeek Harness 作为主 runtime，但保留实验性 adapter 的可能。
- 不引入通用自由规划 agent loop；LLM 生成具体语言内容，但不拥有学习流程控制权。
- 第一阶段先实现 direct deterministic runner，确保手写核心可理解、可测试；LangGraph adapter 在同一 flow 稳定后接入。
- Core 和 Kernel 不直接暴露 LangGraph checkpoint、PydanticAI agent 或 LiveKit room 概念。
- 项目默认语言约定从 TypeScript-first 调整为 Python-first core；前端可独立选择 TypeScript / Web 技术栈。
- 初始 Python package scaffold 已创建，LangGraph 先作为 `engine.langgraph` adapter 引入，core 只保留领域模型和 provider contract。

### 参考

- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph graph API: https://docs.langchain.com/oss/python/langgraph/graph-api
- PydanticAI agents: https://pydantic.dev/docs/ai/core-concepts/agent/
- PydanticAI output validation: https://pydantic.dev/docs/ai/core-concepts/output/

## Decision 0005: 以真实输入和输出证据定义学习闭环

- Status: Accepted
- Date: 2026-08-28

### 背景

LinguaLoop 的思考起源来自一个已实际使用的 `input-driven-language-coach` skill 和 EnglishLearningWorkflow 经验工作区。该工作区包含 raw/cleaned/segments/lessons/sessions 的材料流、输入驱动 lesson、summary-first review，以及独立的 CORA spoken-retrieval practice。

这些实践显示，产品价值不在“一次性生成解释”，而在把真实输入材料转化为可输出、可纠错、可复习、可延迟检索的学习证据链。外部学习科学也支持类似方向：noticing、output、retrieval practice、distributed practice 和 formulaic language 都提示系统应促成注意、输出、回忆、间隔和语块完整性，而不是只提供被动讲解。

### 决策

LinguaLoop 的 MVP 和后续架构采用以下学习闭环作为产品约束：

```text
真实输入 -> 语境理解 -> 高价值目标选择 -> 检索/输出 -> 纠错 -> 复习项 -> 延迟再输出
```

具体约束：

- 用户材料必须保留 raw、normalized/lesson-ready、segment 的概念边界。
- `track` 是显式业务属性；`live_chat`、`article_reading`、后续 `spoken_retrieval` 等 track 可共享对象，但不能被文件后缀替代。
- 用户真实输出、冷启动尝试、复习结果和延迟检索结果才是学习状态更新证据。
- `FeedbackItem` 应优先表达 pattern-level 问题，并能关联到用户消息或材料片段。
- `ReviewItem` 应是可重新检索或迁移使用的任务，不只是词条收藏。
- Profile Delta 是当前证据快照，长期 profile 应从事件、反馈和复习结果重建。
- CORA spoken-retrieval 与 input-driven lesson 是不同 Pattern 家族，不能强行合并成一个六段 lesson 模板。

### 影响

- Product spec 需要把主动输出、反馈证据、review candidates 和 summary-first review 作为 MVP 验收约束。
- Architecture 需要明确 material lifecycle、session events、learner profile snapshot 和 review queue 的边界。
- Pattern contract 需要允许不同学习方法拥有不同状态机，同时共享 `PracticePlan`、`SessionEvent`、`FeedbackItem` 和 `ReviewItem` 等 core 对象。
- Provider adapter 不能只提供 free-form chat completion；它需要支持结构化材料分析、纠错、复习项生成和 profile delta 生成。
- 不应把生成 lesson、展示 model answer 或展示复习项计为掌握；只有后续输出证据能更新学习状态。

### 未解决问题

- MVP 是否纳入 `spoken_retrieval` / CORA 作为正式 Pattern，还是先作为 roadmap 中的后续 Pattern。
- `LearningSegment`、`ProfileDelta`、`ReviewOutcome` 和用户控制事件的最终 schema。
- Review 调度第一版使用简单 due date，还是引入更完整的 SRS 参数。
- 如何在公开 demo 中展示经验样本价值，同时不暴露个人学习材料和历史。

### 参考

- Learning Loop Foundation: ../research/LEARNING_LOOP_FOUNDATION.md
- Practice Workspace Findings: ../research/PRACTICE_WORKSPACE_FINDINGS.md
- Schmidt 1990, noticing hypothesis: https://doi.org/10.1093/applin/11.2.129
- Swain 1998, output hypothesis: https://doi.org/10.1016/S0346-251X(98)00002-5
- Karpicke & Blunt 2011, retrieval practice: https://doi.org/10.1126/science.1199327
- Cepeda et al. 2006, distributed practice: https://doi.org/10.1037/0033-2909.132.3.354
- Wood 2006, formulaic language in L2 speech: https://eric.ed.gov/?id=EJ750535

## Decision 0006: 先做 CLI POC，再做 Python-native 桌面壳

- Status: Accepted
- Date: 2026-09-07

### 背景

当前核心闭环已经能在测试中跑通，但还没有稳定的用户壳。为了尽快验证真实材料导入、分析、对话、纠错、复盘和导出这条链路，先需要一个最小可运行的命令行原型。

### 决策

- 先实现无 UI CLI POC，作为第一条可操作入口。
- CLI 通过共享的 application service 调用 kernel / provider，不直接绑定 LangGraph 或具体 LLM SDK。
- 下一阶段桌面端优先采用 Python-native 壳，复用同一套 application service；WebUI 不作为主线。

### 影响

- CLI 可以直接用于本地 smoke test 和功能验收。
- 桌面端与 CLI 共用同一业务服务层，后续更容易替换交互外壳。
- WebUI 仍可保留为未来可选项，但不会先成为主交互。

## Decision 0007: 桌面端采用 PyQt6 + PyQt-SiliconUI POC（Superseded）

- Status: Accepted
- Date: 2026-09-08

### 背景

项目已经有可运行的 CLI POC 和共享 application service。下一步需要验证本地桌面端交互壳，并且用户偏好 PyQt-SiliconUI 的视觉风格。已检查 `feature/pyqt6-migration` 分支：该分支描述中提到 PySide6，但实际依赖和源码 import 均以 PyQt6 为主，因此当前不能按 PySide6/QML 直接使用。

### 决策

- 桌面端 POC 改为 `PyQt6 + PyQt-SiliconUI`。
- `PyQt-SiliconUI` 通过 Git 依赖接入 `feature/pyqt6-migration` 分支，不 vendor 第三方源码，也不使用 submodule。
- 桌面端先作为薄 UI 壳复用 `LearningWorkbench`，不直接依赖 LangGraph、ChatOpenAI 或 provider 内部。
- 默认使用真实 OpenAI-compatible provider，通过 `OPENAI_*` 环境变量配置；mock provider 仅通过显式参数用于离线调试。

### 影响

- 项目会受到 PyQt-SiliconUI GPLv3 许可证影响；如果未来希望改用 MIT、Apache-2.0 或闭源分发，需要重新评估 UI 依赖或移除该组件库。
- Git 分支依赖的稳定性弱于正式发布包；后续需要关注上游迁移进度，并在需要时固定 commit 或替换组件库。
- 第一版桌面端使用中文浅色界面，只验证窗口启动和最小学习闭环，不承诺完整 UI 体验、持久化或真实 API 异步调用体验。

## Decision 0008: 统一采用 PySide6/QML + Qt Quick Controls 6 + Kirigami

- Status: Accepted
- Date: 2026-09-08
- Supersedes: Decision 0007

### 背景

LinguaLoop 后续需要同时覆盖桌面端和移动端。语言学习在手机上不是桌面三栏布局的简单缩小，而是材料、练习、输出、反馈、复盘的连续任务流。QML 更适合快速调整响应式布局和触控交互，Kirigami 针对桌面与移动设备的 convergent application 场景设计。

### 决策

- UI 主线采用 `PySide6 + QML + Qt Quick Controls 6 + KDE Kirigami`。
- Kirigami 作为桌面端和 Android 端的应用壳，核心页面共享 QML 实现。
- QML 只调用 Python `QObject` ViewModel 的 properties、signals 和 slots；不直接调用 LangGraph、ChatOpenAI、provider 或 Pydantic 内部对象。
- `LearningWorkbench` 继续作为应用层边界，Core、Kernel 和 Provider 保持 Python-first 且与 UI 框架无关。
- LLM 操作放入 Python worker/thread，界面只处理 loading、结果和错误；请求失败时保留用户当前输入。
- Android 优先进行移动端运行验证，iOS 暂不作为第一阶段目标。
- Decision 0007 的 PyQt6 与 PyQt-SiliconUI 路线不再作为主线，相关依赖移除。

### 影响

- PySide6 通过 Python 依赖安装；Kirigami 是 Qt QML runtime，不把 PyPI 上同名的 `kirigami` 包视为 KDE Kirigami 依赖。
- Windows、Linux 和 Android 需要分别验证 QML module 发现、运行时分发和打包方式。
- Windows 开发期不得把 Craft 编译的 Kirigami native plugin 直接注入 PyPI PySide6 的 Qt 进程。检测到这种组合时，应用自动使用 Qt Quick Controls fallback；正式 Kirigami Windows 分发必须使用同源的 Qt、PySide6 和 Kirigami runtime，并在独立打包 spike 中验证。
- Kirigami/Qt 依赖的 LGPL/GPL 组合、图标资源和平台打包方式需要在发布前单独审查。
- 首版页面采用材料、练习、复盘导航；移动端优先保持单列、可返回、可滚动和适合触控的交互。

### 参考

- Qt Quick Controls: https://doc.qt.io/qt-6/qtquickcontrols-index.html
- Kirigami Getting Started: https://develop.kde.org/docs/getting-started/kirigami/
- Kirigami Python Setup: https://develop.kde.org/docs/getting-started/kirigami/setup-python/
- Kirigami Windows Setup: https://develop.kde.org/docs/getting-started/kirigami/platforms-windows/

## 技术栈候选

### Python-first Agent Core

- Core: Python package with Pydantic v2 models and stable schemas。
- Kernel: handwritten PatternRunner, CapabilityRegistry, SessionCoordinator, AgentEngine protocol。
- Runtime: LangGraph adapter after direct deterministic runner。
- LLM: PydanticAI or lightweight Pydantic-based provider adapter behind LinguaLoop boundary。
- Testing: pytest, provider mocks, deterministic Pattern fixtures。

适合手写核心、保持领域语义清晰，并避免重写完整 agent harness。

### Web-first TypeScript

- Frontend: Next.js 或 Vite + React
- Backend: Node.js API、Next.js route handlers，或轻量独立服务
- Storage: SQLite/Postgres 起步
- LLM: provider adapter 封装 OpenAI-compatible API

只适合作为前端候选；不再作为核心 agent 层的默认方向。

### Local-first Desktop / PWA

- Frontend: React + local persistence
- Storage: IndexedDB 或 SQLite wrapper
- Sync: 后续再做可选云同步

适合强调用户数据可控，但早期工程复杂度更高。

### Three-layer Extension Core

- Core: TypeScript domain package with stable schemas。
- Runtime: lightweight plugin manifest, capability registry, lifecycle hooks。
- Plugins: first-party packages for providers, voice, avatar, importers。
- Patterns: first-party or third-party learning flows with explicit capability requirements。
- Voice: `voice-livekit` as a first-party plugin candidate, not a core dependency。

适合在不牺牲学习闭环一致性的前提下扩展多模态能力。

## 待决策项

- 开源许可证：MIT、Apache-2.0、AGPL-3.0 或其他。
- 第一版部署目标：本地开发优先、云端 demo，还是可自托管。
- LLM provider 策略：单 provider 起步，还是从第一版就做 provider registry。
- 鉴权策略：无登录本地版、邮箱登录，还是第三方 OAuth。
- 插件 manifest 格式、权限模型、版本兼容策略。
- Pattern manifest 格式、capability requirements、fallback 策略。
- 第一批官方学习 Pattern 清单。

## Decision 0009: 本地 SQLite 持久化和主动结束复盘进入 MVP

- Status: Accepted
- Date: 2026-09-09

### 背景

桌面端 POC 已经能通过内存态完成材料分析、练习对话和导出，但用户关闭或重启软件后无法继续看到材料、会话和复习项。当前产品目标强调真实材料、用户输出证据、反馈来源和 review queue 的连续性，因此内存态无法支撑 MVP 验收。

同时，外部产品调研显示，材料导入、AI 解释和卡片生成已经是常见基线。LinguaLoop 的差异应落在可追溯学习证据链，而不是只做更多格式的导入或泛用聊天。

### 决策

- MVP 运行时持久化采用本地 SQLite，使用标准库 `sqlite3`，暂不引入 ORM。
- 默认数据库路径为平台应用数据目录下的 `LinguaLoop/lingualoop.sqlite3`，允许用 `LINGUALOOP_DATA_DIR` 覆盖。
- 存储材料、会话、消息、反馈、复盘、review items、review outcomes 和 `SessionEvent`。
- Markdown 和 DOCX 是第一批文件导入格式；旧式 `.doc`、PDF、视频和 Google Docs 在线授权暂不进入第一阶段。
- 多轮练习过程中只生成即时反馈；最终 review candidates 在用户点击“结束并复盘”后集中生成。
- 桌面端采用左导航、中工作区、右上下文的工作台布局，并在窄屏下折叠。

### 影响

- `LearningWorkbench` 成为本地恢复、材料列表、会话完成和 review queue 的应用层边界。
- Provider contract 增加 `summarize_session`，用于输出结构化 `SessionReview`。
- `ReviewItem` 需要保存来源材料、来源会话、状态和 `due_at`，`ReviewOutcome` 记录 `again/hard/good/easy`，控制事件覆盖 pause、ignore、archive、delete 和 mastered。
- JSON 导出继续作为备份和迁移出口，但不承担运行时状态。
- Mock provider 继续用于 CLI、测试和显式离线调试；普通桌面模式不自动降级到 mock。

### 未解决问题

- SQLite 当前使用 JSON payload table，后续需要评估何时拆成更细粒度 repository schema。
- `LearningSegment` 已进入 Core，但 segment 自动切分和来源位置标注还需要继续补强。
- 基础 due date 调度已经可用，但完整 spaced repetition 算法仍留到后续阶段。

## Decision 0010: 沉浸语境驱动语音输出成为产品主线

- Status: Accepted
- Date: 2026-10-24
- Supersedes: Decision 0002、0003 中语音仅为后续增强、不进入 MVP 关键路径的范围安排；保留其 Core / Plugin / Pattern 与可替换语音实现边界。

### 背景

用户明确提出将既有语境练习与沉浸式学习结合：继续按兴趣看番、看视频等，把已经接触过的内容作为语境，让 AI 先理解材料、总结可聊内容、推荐话题，主要通过语音对话练输出；愿意时也可以玩语境 roleplay。

现有文本对话、材料分析和复习队列可以复用，但“把字幕变成课程”和“把语音放到远期插件阶段”不能完整表达本次主旨。用户也保留了按自己认可的学习理论调整练习的长期方向。

### 决策

- 产品主旨确定为“沉浸提供语境，LinguaLoop 帮你练输出”，语音对话是核心体验。
- 默认入口是材料理解后的话题推荐与自然讨论；roleplay 自愿，词汇讲解和理解测验不作为开聊前提。
- 正式 MVP 必须包含基础多轮语音输入和 AI 语音回复。现有文本闭环定义为原型基础，并保留为辅助和故障回退。
- 语音通过可替换 provider / plugin capability 接入，不因此把具体 SDK 放进 Core；本次不重新选择 SDK、引入外部服务或修改实现。
- 方法可配置保留为产品方向，MVP 先支持基础练习偏好；完整自定义理论编辑器、连续实时双向语音和 avatar 留在后续范围。
- 继续保留真实输出证据、可追溯反馈、主动结束复盘和本地 review queue；不把话题生成或内容展示计为掌握。

### 影响

- `PROJECT_BRIEF.md` 成为当前主旨的权威入口；README、AGENTS、MVP、路线图和相关架构文档同步对齐。
- 路线图新增核心语音 MVP 阶段，先补齐话题选择、自然讨论和基础语音，再扩展实时交互与更多学习方法。
- Plugin 在实现上可替换，不意味着语音在产品验收上可省略；文字回退不能代替语音验收。
- 当前代码中的文本流程保持可用；本次是文档与范围更新，不宣称话题、语音或方法配置已交付。

### 未解决问题

- 基础语音 provider、轮流说话的具体交互方式、延迟和成本是否满足实际使用。
- 话题质量、材料范围和来源关联的最小结构，以及字幕导入增强的具体设计。
- 学习理论配置如何落到可测试、可复盘的 Pattern 参数或扩展，而非任意 prompt。
- 新主线是否能帮助用户更愿意开口和持续输出，需要真实使用验证。

## Decision 0011: MD3 桌面与独立分轮语音实现

- Status: Accepted
- Date: 2026-10-24
- Supersedes: 早期 Windows 默认 Kirigami 壳、固定三栏布局与逐轮强制纠错；保留 Python-first、provider 可替换和 SQLite 的既有选择。

### 背景

用户批准以 MD3 统一首版 UI，并交付“材料 → 话题 → 分轮语音 → 轻量复盘”。现有 UI 组件层级不统一、侧栏压缩对话，SQLite 共享连接跨线程报错，每次请求创建独立 asyncio loop 也不适合复用网络 client。

### 选择

- Python ≥3.11、Pydantic 2、PySide6 6.11.1/QML，Windows 默认 ApplicationWindow；Kirigami 仅显式启用。加载 QML 前统一 Qt Material 样式。
- `AppTheme` 和项目组件管理 MD3 语义色彩、字体、形状与状态，紫色种子 #6750A4，系统/浅/深主题和减少动效保存在 QSettings。
- <600 使用底部导航，600–1199 使用 80px rail，≥1200 对话页增加 320px 语境面板。
- 增加 pysubs2 1.8.x 解析 SRT/VTT；保留原文和 cue 起止时间，topic 引用必须在规范化材料中出现。单次分析限制 30000 字符，长材料保存后提示选片段，不静默截断。
- 明确 `DiscussionTopic` 与 `PracticeOptions`；默认自然讨论、低强度和结束反馈。纠错失败不阻断对话，反馈和复习证据不足可为空，单次复盘最多三个重点和三个复习项。
- 语音采用 Qt Multimedia WAV + 独立 STT/TTS protocol 和 httpx adapter，配置使用 `LINGUALOOP_STT_*` / `LINGUALOOP_TTS_*`。文本服务不自动继承为语音服务。
- 最多录音 60 秒，识别后由用户编辑确认，再发送生成和合成；合成重试不重新调用文本模型。
- SQLite 按操作连接与事务，后台采用一个长期运行 asyncio worker；音频和 GUI 留在主线程，正常退出关闭任务与临时文件。
- 编排继续 deterministic runner，不增加新数据库、云编排或大型 UI 框架。

### 影响

Core 与供应商/Qt 保持隔离，QML 拆成设计系统、组件和业务页面；新增资源通过 package-data 随 wheel 分发并验证。旧 payload 通过默认值读取；旧会话保留兼容语义。材料里的指令作为内容处理，云端音频与确认后的本地文本分开保存。

### 未解决问题

- 真实服务、麦克风、播放、延迟和成本仍需至少三轮真人验收，mock 结果不能替代。
- 当前只构建 Python wheel；独立 Windows 安装器、代码签名和 Qt runtime 打包尚未交付。
- 强制终止可能留下系统临时目录，后续可增加启动时清理策略；不存原始音频供重启恢复。
- 完整理论编辑器、连续通话/自动打断、材料原地管理、跨整季索引和移动端继续留待后续。

## Decision 0012: DeepSeek 双角色、可接续材料准备与文本优先验收

- Status: Accepted
- Date: 2026-10-24
- Supersedes: Decision 0011 的单次 30000 字符限制、固定少量话题以及本阶段依赖 STT/TTS 验收的先后顺序；产品仍以沉浸语境下的自然输出为目标。

### 背景

用户要求围绕材料和对话，先用现有 DeepSeek 配置完成纯文本测试；材料包含整本小说、Excel、EPUB 或带字幕的视频。推理模型应提前准备丰富话题和常见回答，在对话后台按需继续准备，前台短回复由 Flash 执行，以完整回复低于 1 秒为性能目标。文本验证后再转向 LiveKit 连续语音。

### 选择

- 复用 Python core、deterministic runner、SQLite 和 provider 抽象，不新增数据库或云索引。Excel 增加必要的 openpyxl；EPUB 用标准库读取 spine 和 HTML 文字。视频当前只读取同名字幕，未调用视觉模型。
- 首选 `deepseek-v4-pro` 思考模式负责整理与后台准备，`deepseek-flash` 非思考模式负责所有前台轮次。显式分别发送 thinking 参数，推理角色加 high effort；旧 `OPENAI_DISABLE_THINKING` 不再覆盖推理。依据 [DeepSeek 模型表](https://api-docs.deepseek.com/quick_start/pricing/) 与 [思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)。
- 原文先保存；按最多 12000 字符处理，逐块持久化哈希、摘要、规范化结果和证据。失败可恢复已完成块。默认 360000 字符安全预算显式可配置到 5000000，超限提示分卷，不静默截掉章节。
- 材料保存大纲、人物、块摘要与最多 60 个跨章话题；每题可保存多个候选用户意图、短回复要点及精确引用。自定义话题在开聊前推理准备并保存。
- 前台仅用话题准备包、已完成后台准备和近期六条消息流式回复；背景候选不是用户事实。用户每条消息限制 4000 字符。回复失败不将半消息持久化。
- 背景最多 12 次/会话、45 秒/次、一个并发，采用 revision/代际/会话标识验证；新发言、换材料、结束和重置取消旧请求。异常或过期结果不阻塞当前轮。
- 新生成结果严格校验：后台意图、要点、精确引用均非空；材料与自定义话题必须有完整的有来源回答分支。部分无效分支剔除；缺失/全空/全无效时最多两个格式尝试，后台 45 秒覆盖整个准备任务。失败保留旧有效 snapshot 但不标 ready。旧数据的默认空字段仍允许读取。
- 审查补充：消费旧 snapshot 前也执行严格校验，允许读取历史不表示可将无引用内容交给 Flash。话题预算跨所有章节轮询；自定义题按全部块与原文的轻量相关性挑选、附命中窗口和全书分布概览，保留明确来源范围。
- 真实首轮计时显示完整回复 1 秒尚未普遍达成；可逆优化只去重重复证据、当前发言及无用 UUID，保留分支与回答质量、160-token 输出预算。Pro 后台小任务最终采用 low effort、4000-token 上限；历史 low/2500 两次未 ready 的测量保留，分析继续 high。实测单次分析输出 19231 tokens，因此分析上限设为 24000；每次非流式模型默认 240 秒 wall deadline、全材料单次运行默认 1800 秒总预算，超时后可从保存块接续。对应配置见 `.env.example`，增加预算将增加成本。
- `ChatOpenAI` 会将 `max_tokens` 改写为 OpenAI 字段 `max_completion_tokens`。DeepSeek 使用同库 `BaseChatOpenAI` 保留官方字段，透过 MockTransport 断言实际 wire JSON 参数，而不只断言 Python settings；泛 OpenAI 仍保留原客户端。
- 最后一次有界后台修复：low/2500 的两次真实输出都恰好 2500，但当时缺少 finish_reason，不能据此直接断言截断。新增仅含安全元数据的诊断，后台输入仅当前题与两轮、少量备选和单引文；输出缩成一意图、一两个短要点和一引文。独立后台预算调整为 low/4000，仍为思考角色、单并发、45 秒总任务、12 任务/会话。明确 length 时不做同预算重试，其他结构无效仍最多两次；不 fake ready，也不将预测计入用户历史。最终微型包 low/4000 已真实验证一次 10.69 秒 ready，随后 included 到唯一 Flash 请求；没有意图准确率标注或提速因果证据，不能从单例推导稳定性，见[文本独立验收](../validation/text/TEXT_ACCEPTANCE_2026-10-24.md)。
- 首个内容块 TTFT 与完整模型耗时分别测量，端到端耗时另测。不能从 TTFT 低于 1 秒推导完整回复达标。
- 新讨论即时纠错延后到结束（包括历史 immediate 偏好），确保 Pro 不进入前台路径；直接 runner 的旧 options=None 保持兼容。

### 影响和未解决问题

旧业务 JSON 通过默认空列表、空 preparation 和完成标记兼容读取。真实材料仍会上传配置的模型服务，按敏感数据处理；不记录原始推理链、密钥或完整模型日志。长材料整理会产生多次 Pro 调用，增加预算前应考虑成本。精确引用只能证明来源存在，不能自动证明所有 AI 解释正确，仍需真实素材质量验收。完整回复低于 1 秒是待测目标，网络和模型服务时间可能无法满足；不得因流式 UI 可用就宣布达成。LiveKit 及 STT/TTS 选择由后续文本验收门决定。

## Decision 0013: 以可选 Python RTC adapter 做严格 loopback 探针

- Status: Accepted（技术探针边界；真实 RTC 连通未通过）
- Date: 2026-10-24

### 背景

文本功能和真实前台调用已验证，完整回复 1 秒尚未稳定达到；用户明确选择保留该优化目标，先做 LiveKit 探针。此时需要验证 transport、连续 PCM、文本流和取消生命周期，而不提前实现整套云语音 UI 或引入模型框架。

### 决策

- 新增独立 `lingualoop.realtime`；协议、PCM 与接收代际 gate 不依赖 SDK。仅 `realtime` extra 安装固定版 `livekit` / `livekit-api`，不引入 `livekit-agents`。业务和 LLM provider 不依赖 RTC；transport 不修改 `DialoguePreparation`。
- 可靠文本事件带 session/turn/generation/seq，draft 仅在显式 done 后完成。generation 绑定一条连续 PCM 轨和 SID；取消立即关闭接收呈现门、清发送队列、释放旧轨，旧代际不能冒充新轮。
- 使用可校验的官方 Windows server 资产，缓存于 ignored build；不创建云账号、服务、公网入口、firewall 规则或全局安装。HTTP/UDP 实际 socket 必须严格 loopback。当前官方 server 的 RTC TCP listener 无独立 bind IP 配置，故禁用 TCP fallback，不能以 `--bind` 或 node_ip 广告代替 socket 检查。
- SDK 的空 ICE 列表会继承 server ICE 表；初版误用非空、空 URL 的 ICE entry，违反 libwebrtc 校验，是探针配置缺陷。修正为由探针显式传入合法 `stun:127.0.0.1:<已审计UDP端口>`，非空 URL 阻断回退；不新增 STUN 服务或监听。探针严格校验 literal loopback、canonical URL 和精确端口，adapter 通过显式配置接收，不把本机限制加入 core。RTC exercise 在隐藏短命子进程内运行，父进程硬截止和 PID/socket 检查覆盖 native 握手超时；临时密钥不进命令行/结果/仓库。

### 影响和未解决问题

当前离线协议/清理测试通过，Windows server 的 loopback 监听及退出可复核。历史空 ICE 列表出现真实握手 timeout，但有继承默认 ICE 的限制；随后空 URL entry 的独立 ConnectError 来自无效配置候选，不能证明本机 loopback 不可用。合法本机 URL 修复经离线自验和唯一一次独立差异 RTC 复验：首 client 连接约 44.9 秒后被总 deadline 取消，`operation_deadline`、native 创建 `not_observed`，不能推断已进入 ICE 握手；所有自有进程/socket 清理通过。双参与者 PCM/文本/取消/重入尚未到达，不记通过。不因此放宽网络范围或增加云服务。现有 QML 和分轮语音继续使用原实现，未接新 adapter。完整 VAD/AEC、STT/TTS、播放队列打断、真人语音、自动断网恢复与设备切换均待后续验证。具体版本、限制、命令和失败证据见 [LIVEKIT.md](../desktop/LIVEKIT.md)。


## Decision 0017: 可选本地语音目录、实测准入与独立推理进程

- Status: Accepted（阶段 1 / 2；尚未接入连续语音）
- Date: 2026-10-28

用户批准先研究与实测本地 STT/TTS，再交付按语言、用途、硬件选择的模型库；要求同时考虑整条链路的延迟。复用 Python、Pydantic、httpx 与 PySide6/QML，不引入新数据库、云模型框架或后台服务。

- 固定模型包版本、字节数、SHA256、前端/语言限制与来源；已适配包和候选家族分开。默认不批量下载所有模型，不把 GPU 检出当作 CUDA 可用。资源准入检查当前可用 RAM 与缓存盘空间，配对累加预算并留系统余量；预算不是模型最低配置声明。
- 下载使用可续传内容缓存、完整性校验、安全展开与原子安装；按模型跨进程加锁，取消不安装半包，卸载不触及学习资料。版本目录保留，跨版本选择 UI 后续再做。
- GUI 不导入推理库。单个管理线程处理 I/O，受控独立进程加载 CPU 模型，硬截止/取消释放资源；Qt 对象与试听播放器留主线程。模型包中的 Python 脚本不执行。依赖作为 local-speech extra，重模型及 GPU 运行时不进基础安装。
- 固定 sherpa-onnx 1.13.8，而非直接采用 2.0.1：实际探针发现 2.x 忽略旧 VITS data_dir，Piper 缺外部 phonemizer 时生成空音频。1.13.8 有 Windows/Python 3.13 wheel，已用固定包复测；未来升级须先迁移前端，不能只升级版本号。依据官方 [Piper 外部前端示例](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/test-offline-tts-piper-phonemize.py)。
- 冷加载、首次推理、热态 p50/p95、首 PCM、ASR 最后计算和双模型并发分别记录；模型指纹、运行时、CPU/平台、语言与线程策略匹配后才用于 UI 推荐。初步实时预算为 STT 最后计算 350ms、TTS 首 PCM 300ms，超标者不作实时推荐。这是本项目筛选策略，完整停顿到出声仍以真人链路测量为准。
- 2026-10-28 严格语料复核：Zipformer 默认使用 FP32 decoder，encoder/joiner 保持 INT8；全 INT8 decoder 的中文大量删除已由同语料 FP32 对照确认。引入独立 adapter revision，使旧配置测量、相关配对报告与已存候选失效，无需更改模型包指纹或重复下载。详见[严格评测](../validation/speech/LOCAL_SPEECH_STRICT_EVALUATION_2026-10-28.md)。
- 目录、下载、数值报告、内置试听与候选选择使用独立本地缓存；不复制输入录音，不保存识别文本，不读写学习历史。保存候选不切换已有 provider。阶段 3 再连接实际音频/LiveKit，测 VAD、LLM、播放队列、AEC 与打断。
- 2026-10-29 用户确认允许各语言分别安装/选择 STT/TTS，不强求一个多语包；沿用现有 `language:scenario:task` 候选键。实际对话切换、模型常驻和预热生命周期仍待接入，不因保存候选就宣称已交付。
- 2026-10-29 此前批次按热态首字算术平均 ≤500ms 筛 STT，保留两版 SenseVoice 的中/英四项，当时日语暂缺；这是已有报告口径下的实验筛选，不替代统一“说完/端点确认到可见文本”的链路准入，也没有覆盖代码内现存 p95 计算预算。当时 CPU 环境未提供 CUDA provider，后续 GPU 必须验证实际 kernel、精度、CER/WER 与资源，禁止静默 CPU 回退。
- 同日按用户进一步要求完成[实际 GPU 与日语候选补测](../validation/speech/SPEECH_GPU_JAPANESE_MELO_FOLLOWUP_2026-10-29.md)：2024 SenseVoice FP32 GPU 三语均值 52–58ms；INT8 GPU 为混合执行，未优于同运行时 CPU 对照。ReazonSpeech CPU 与 Kotoba GPU 日语也通过 500ms 平均线；精度、前端与运行时作为独立配置保留，不覆盖旧 CPU 结果。新增 Melo 独立英语评测不等于切换现有 TTS provider。
- 2026-10-29 用户定性试听后：中文 Melo、英语 Lessac 优先，日语 VOICEVOX 暂留；Amy L054 的否定词错误已由用户确认，修复复测前仅备选。已测 Kokoro 与 Qwen 退出本轮候选，原始资产和失败/慢轮次保留，不继续 Qwen 流式/并发补测。完整选型与 VOICEVOX 首 PCM/整句完成口径见[用户筛选记录](../validation/speech/LOCAL_SPEECH_SELECTION_2026-10-29.md)。

未解决：日语声音的产品再分发许可；各模型的学习者口音准确率、人工音质及再分发审核；跨 GPU 后端与长时间并发；真正的一秒停顿到出声。VOICEVOX 本地评测条款已由用户接受，固定包和首音实测见严格报告；不代表已完成产品再分发审核。本机短样例结果、失败记录和使用方法见[本地语音指南](../desktop/LOCAL_SPEECH.md)。


<a id="decision-0018"></a>

## Decision 0018: 自由聊天、已读范围与有预算的参考整理

日期：2026-10-28。状态：采用；替代 Decision 0012 中默认丰富题库与整书汇总前置的部分，其余 provider/线程/存储约束继续有效。

背景：用户认为选题 UI 机械、前置 token 成本高。完整小说实测的整书汇总为 24829 输入 / 18775 输出 token，自定义题为 9202 / 11060；预制大量分支并未让完整回复稳定低于一秒。不能由此断言所有准备无用，应比较参考命中率、对话具体性、延迟与总成本。

选择：沿用 Python、Pydantic、SQLite 和 QML，不增加向量服务。默认在本机按原文位置和哈希建立小段索引，缓存词项；前台按当前发言和历史选择最多三段相关原文，删除每轮全书概述、题库分支和猜测回答的必需依赖。自由开场使用目标语言短句，不产生模型请求；推理参考在两次真实发言后、来源变化且预算允许时运行，每会话最多三次尝试，次数持久化。可选方向最多三个，点击后仍由用户确认发送。

阅读范围使用规范化原文的字符末尾，保存到材料，并在会话 options 中快照。新桌面导入的 0 表示未确认；历史 None 兼容原整本范围。精确原文末句优先，百分比只是定位辅助，会向前取整并展示末尾。所有会话模型路径只拿已读前缀；部分阅读不复用全局概要/人物/话题，只允许完整落在范围内的分段依据。原整书 analysis 仍在独立缓存，恢复读完状态可取回，历史消息不重写。

影响：默认导入费用为零，无需等数分钟题库准备。原文检索不等于理解，省略、跨章推断与别名仍可能漏召回；小上下文也不保证模型不调用固有的整书知识，Prompt 必须明确禁止后文及暗示，并做真实防剧透验证。对话质量下降时应改进局部索引、归属和引用选择，不恢复无上限预写回答。

未解决：EPUB 章节标签与跨版本阅读位置映射；有质量增益证据的可选分段事实压缩；跨会话参考复用和按金额展示成本；语义召回及真人连续语音。已读范围是产品防剧透边界，不宣称可形式化阻止模型凭预训练知识猜到后文。


<a id="decision-0025"></a>

## Decision 0025: 按模型选择 CPU/GPU，并让显存和驻留可见

日期：2026-10-29。状态：采用，首批适配已实现；在 Decision 0017 上增加分轮语音接入，不替代 LiveKit 连续语音验收。

背景：用户重视首字等待，并确认新英文听样可用；严格评测中 SenseVoice 2024 FP32 的 GPU 提速明显，而 INT8 并非因开启 GPU 就更快。用户也关心显卡被软件长期占用。

选择：设置拆为“语音模型”和“计算与加速”。模型按语言/场景/任务保存；STT/TTS 分别自动或手动 CPU/CUDA。自动优先采用有实测收益的 GPU 适配，硬件、预留或预算不足才考虑 CPU；手动 GPU 失败不静默回退。STT 本机平均计算超过 500ms 不推荐对话；CPU/GPU、运行时、GPU 编号及 adapter 变化须重新匹配测速。准确率/听感仍需要独立证据。

推理在独立常驻 Python 子进程内运行，GUI 不加载权重、Torch 或 CUDA。固定运行库通过可取消的独立 venv 准备，驱动由用户安装，通常不需要完整 Toolkit；CUDA 准备必须通过真实 kernel 探针。音频和识别结果经内存管道返回，输入不另存文件。首批接入 SenseVoice、ReazonSpeech、既有 sherpa TTS 路径，其他已评测后端后续适配。

影响：新增语音缓存下 compute.json，不改学习数据库或个人 .env。预算累加 GPU 模型的保守估算，配置 CUDA arena，并预留显存给其他应用；这不是整体进程硬上限，不承诺固定 GPU 使用率百分比。区分整卡/进程统计，Windows WDDM 不支持时显示未知。默认空闲 120 秒释放，提供立即和手动释放；释放自己的整个进程树，防止虚拟环境启动器留下占用。常驻模型持有文件锁。

未解决：独立 Melo 英文、Kotoba、VOICEVOX 的产品适配，冻结应用的运行时分发、会话前自动预热、跨平台显卡后端，以及真人端点到出声、并发与打断验收。GPU 新环境完整下载受本机网络停滞影响，不能把现有运行环境的 kernel/模型通过写成新下载已通过。验证见[接入记录](../validation/speech/LOCAL_SPEECH_COMPUTE_SETTINGS_2026-10-29.md)。


<a id="decision-0029"></a>

## Decision 0029: QML 自动发送分轮语音与独立播放状态

日期：2026-10-30。状态：采用；是 Decision 0023/0024 的桌面过渡增量。

用户明确实际交流不应强制确认转写，本轮先选择结束录音即自动发送，每轮默认自动朗读。沿用 Qt、既有 worker、Workbench、确认事务和语音协调器，不增加技术栈或 LiveKit 产品依赖。新增 DesktopVoiceController 管理独立识别、回复与播放状态；停止朗读只取消语音，不取消文字生成。

输入在事务提交后成为历史，按录音/文字请求 ID 防重；回复与朗读分别重试。原文在结束录音时捕获，下一份文字草稿独立保留。主线程有界音频队列以 EndOfMedia 推进，合成完成和设备播放完成分别释放状态；模型调用留在共享 asyncio loop。桌面文案继续使用 Qt 翻译入口。

未解决：连续麦克风、端点/VAD、AEC、自然插话、网络自动恢复与真人多语言质量；本次 Mock 和合成音频验证不能替代这些验收。新本地声音的产品安装/下载也不纳入此增量。见[QML 语音记录](../validation/engineering/VOICE_QML_2026-10-30.md)。

<a id="decision-0030"></a>

## Decision 0030: 独立 RTC/DSP 进程与停顿自动提交

后续设置闭环采用 Decision 0031；本节既有独立 RTC/DSP 选择保持。

日期：2026-10-30。状态：采用，机制已接线，真人设备验收待完成。

背景：分轮自动发送已接通，但仍需每次停止录音。用户确认本轮完成停顿自动提交、自然插话与扬声器 AEC，先用耳机验证；不要求 partial，付费模型预算为 0。

选择：Qt 主线程用 QAudioSource/Sink 做有界设备 IO，独立 AudioSessionWorker 拥有两个 LiveKit peer、APM、Silero v6.2.3 CPU ONNX 和有状态重采样器；业务仍由既有 worker、VoiceSessionCoordinator 和 Workbench 执行。麦克风／回复都经过真实本机 SFU。模型资产固定 hash 和许可，显式准备，开麦不下载。

默认 650 ms 停顿，可选 1000 ms。Engine VAD 唯一产生端点，本地近端检测快速停旧输出；认领前校验句段版本与近端状态。输入会话／麦克风代际独立于输出代际。续说先等旧识别清理，新回复先等旧生成释放。取消事务先失效旧轮，再清队列、reset 设备和取消推理，拒绝迟到保存；完整文字与音频交付分别记录。

用户选择先静音再发文字；停止朗读仅停声音，停止语音也取消未完成回复，但不结束学习线程。一次断线最多重建一次，恢复需用户重新开启监听。设备变化不自动转外放。字体、中文优先翻译入口与原文／草稿契约继续沿用。

影响：新增可选 continuous-voice extra，不给基础 CLI 引入 ORT/RTC 必需依赖；SQLite 使用已有 JSON 扩展默认字段，不保存录音和助手半流。真人、合成声卡和真实本地服务的证据分开。Decision 0029 修正了此前与工作区 Decision 0026 重复的编号，语义不变。

未解决：真人耳机／扬声器、声学余音、学习者口音和真实模型对话质量；partial、完整监督器与云部署仍后续。新声音 GUI 与独立环境准备现按 Decision 0031 实施并记录验证，不再作为本节未接线项。见[验收记录](../validation/engineering/CONTINUOUS_VOICE_2026-10-30.md)。


<a id="decision-0031"></a>

## Decision 0031: 按运行时类型准备语音与冻结声音配置

日期：2026-10-30。状态：采用，真实验证中。

背景：评测 adapter 不能依赖开发目录和手写 profile 成为普通用户入口，ONNX、VOICEVOX、Melo 和 RTC 的依赖不同。

选择：复用固定下载、SHA256、锁与缓存，按 ONNX CPU/CUDA、VOICEVOX CPU、Melo CPU/CUDA、RTC/APM 分环境准备。固定 Python/uv、wheel 与前端，候选环境通过实际计算后原子切换，失败保留上一环境。Melo 固定 Python 3.12.13、Torch 2.9.1、Transformers 4.57.3；不改系统 Python、PATH 或安装驱动。

VOICEVOX 首批只开放ずんだもん，普通风格核对固定 VVM、按版本确认条款并署名。Melo EN/EN_NEWEST 共享资源。候选声音与已选声音分开，报告绑定环境/前端/声音；测速与业务共用 profile，不同解释器配对使用独立常驻进程。

影响：扩展既有 JSON 默认字段与资源分发，不迁移学习数据库；旧 prepared-profile、旧模型兼容记录和分轮回退保留。独立安装包、更多角色及其他 GPU 平台另做。原定最终提交等待设置和真人设备门禁；2026-11-06 用户明确要求先整理提交当前实现，未完成门禁仍单独记录，见[设置指南](../desktop/LOCAL_SPEECH_SETUP.md)与[交付自测](../validation/engineering/VOICE_HANDOFF_2026-11-06.md)。

<a id="decision-0032"></a>

## Decision 0032: Windows 私有 Python 分发与应用图标

日期：2026-11-06。状态：采用；开发预览分发，不替代进行中的 UI／真人语音验收。

背景：用户要求补齐应用图标与 Windows 打包，同时保留正在运行的桌面 UI／语音任务。
当前音频和推理使用独立 Python 进程，本地语音安装明确拒绝 frozen 环境，直接冻结 EXE 会改变既有机制。

选择：随包携带固定 hash 的 CPython 3.12.13 完整私有运行时，将锁文件导出的依赖及隔离构建的 wheel 安装在其中。
自有小型 C# WinExe 启动器通过相对路径调用私有 pythonw；Inno Setup 6.7.4 制作无管理员权限的当前用户安装器，同时提供 ZIP。
Inno 编译器通过官方 portable 模式放入 ignored build 目录，校验 SHA256 与发行者签名，不安装全局工具。
原创几何 SVG 使用现有暖纸／灰绿色板，确定性生成多尺寸 ICO，用于 EXE、Qt 窗口、任务栏和快捷方式；AppUserModelID 保持一致。

影响：运行时保留真实 sys.executable、venv 与 subprocess 行为，不改业务数据模型或 core 依赖。
分发版显式读取用户目录配置或 LINGUALOOP_CONFIG_FILE，保留环境变量优先级，不复制开发者凭据。
Mock 分发入口使用临时学习库与 INI 偏好。安装不关闭其他应用，卸载保留用户目录。
构建白名单、资源 hash 与私密文件检查覆盖包体；普通回归、离屏分发启动与独立目录安装／卸载分别留证。

未解决：代码签名、自动升级、干净 Windows 镜像矩阵、安装升级文件占用及真人连续语音仍另验收；
在另一个任务持续修改源码时，包是构建开始时的开发快照，后续完成的修正需要重新构建。
命令、私有运行时来源、配置与许可证边界见 [Windows 分发指南](../desktop/WINDOWS_DISTRIBUTION.md)。


<a id="decision-0033"></a>

## Decision 0033: 独立的语音准备任务与按需展开的模型列表

日期：2026-11-06。状态：采用。

背景：串行 `busy` 会锁住整个模型页，用户无法并行下载 STT/TTS；全宽大卡片和全局进度也无法说明正在下载哪个组件。缺少当前语言模型时，笼统的语音连接错误会误导设备排查。

选择：资产准备使用最多 3 项的独立任务队列，提供逐项身份、组件进度、取消与重试。内容寻址 blob 和同类运行环境等待共享锁，现有推理锁默认继续快速拒绝；权重与环境就绪标记仍经原校验和探针。模型页分 STT/TTS 标签，简要状态常显，声音、完整资源与许可按需展开，使用原生可滚动列表。

影响：新增桌面下载列表接口和安全语音错误码，不改变学习数据模型、当前语音绑定或用户环境配置。旧 `busy` 汇总保留，界面用 `operationBusy` 区分串行操作。缺少 TTS 可继续 STT／文字；模型选择必须匹配会话语言。下载队列仅在本次运行内保存，重启手动续传；跨应用的同一组件依旧由文件锁保护。

验证与限制：并发、共享锁、退出、真实 QML、缩放及安装资源单独验证；合成下载不冒充真实权重安装，真人听感和扬声器门禁仍另列。见[验收记录](../validation/engineering/SPEECH_DOWNLOAD_UX_2026-11-06.md)。

<a id="decision-0034"></a>

## Decision 0034: 默认使用内置语音示例，显式测速并选用

日期：2026-11-06。状态：采用。

背景：测速默认打开文件选择器，用户需要自行寻找录音；文件安装与按语言／用途的模型选用分散，容易误认为下载完成即可开聊。

选择：随包提供固定来源和 SHA256 的中英日公开 FLEURS PCM16 示例与 CC BY 4.0 署名，普通单测及配对直接使用它们，自有录音移入详情。首次「测速并选用」通过真实测速和原准入后才写入配置，取消或失败不替换现有选择。

影响：新增资源与桌面组合入口，不更改已有 CLI 的显式 WAV 契约、已保存模型选择、会话语言或当前语音绑定。顶部显示当前语言／用途的选择，不把转录或其他语言的配置当作对话配置。示例用于性能探针，不代表麦克风识别质量；未附示例的语言明确提示，禁止拿别的语言音频代测。


<a id="decision-0035"></a>

## Decision 0035: 手动闭麦保留未发送语音

日期：2026-11-06。状态：采用，覆盖旧「静音丢弃半句」的产品约定。

背景：用户在嘈杂环境需要短暂关闭麦克风，旧实现重置句段并丢弃未提交语音，不适合说到一半等待噪声过去。

选择：手动暂停关闭采集和提交入口、取消旧识别但保留有界 PCM；恢复接续同一句段并更换麦克风代际。暂停后提供显式发送已说内容及单独丢弃，不以闭麦代替丢弃。恢复时等待新起音，不把暂停时长当作停顿发送。设备／传输故障继续独立报错，不能拿不完整音频正常提交。

影响：不更换模型、栈或数据库，不引入后台录音和录音持久化。文字草稿、已发送历史和已提交回复保留，未提交 PCM 及来源仅在当前语音会话内有效。已确认事务优先于暂停时只保留真实用户消息；未确认时恢复 PCM 并按原请求身份防重。合成 RTC、真实设备与噪声环境分别验收，见[验证记录](../validation/engineering/VOICE_PAUSE_2026-11-06.md)。

<a id="decision-0037"></a>

## Decision 0037: 从产品目录删除 SenseVoice 2025 / WSYue

日期：2026-11-06。状态：采用，覆盖此前保留中文和手动英语备选的安排。

背景：用户实际使用后明确要求删除这款模型，不再纳入列表。[已有复核](../validation/speech/SENSEVOICE_2025_FORMAT_AUDIT_2026-10-29.md)显示，其英语 WER 在忽略大小写后仍为 29.35%，格式规范化不能消除与原版的质量差距。

选择：从共享 `catalog.json` 删除 `sensevoice-int8-20250909`，桌面和 CLI 的全部语言、用途均不再提供下载、测速或选用。删除仅针对该版本的推荐限制与提示，不保留隐藏或手动备选。原版 SenseVoice 2024 INT8／FP32 保留。

影响：旧设置指向该 ID 时沿用选择失效提示，用户需重新选用现有模型，不自动绑定替代模型。历史评测、缓存与学习记录保留；不改变模型适配器、运行环境和数据格式。目录与打包检查防止该版本重新进入产品列表。

未解决：原版及其他现有候选的真人麦克风质量仍按独立语音验收处理，本次移除不构成新的模型质量通过证据。

<a id="decision-0038"></a>

## Decision 0038: Melo 中英 ONNX 仅保留中文产品用途

日期：2026-11-06。状态：采用。

背景：用户明确否决 MeloTTS 中英 ONNX 的英语效果，同时认可其中文。直接变更模型能力或名称会改变现有包指纹，使中文安装、测速和选择一并失效。

选择：目录新增默认空的 `disabled_languages` 产品限制，`melo-zhen-onnx` 禁用 `en`。`languages` 继续记录模型能力，`available_languages` 供桌面／CLI 列表、测速与普通语音选择校验使用。英语对话和朗读均不保留此包为备选，旧英语选择提示失效；独立 Melo English 型号不受影响。

影响：产品语言限制不参与资产指纹，未限制语言继续复用原安装、报告与选择。新字段有默认值，旧清单可读取；原指纹与数据格式保持兼容。不卸载中文资产，不自动替换英语声音，不改写历史评测或个人配置。

未解决：现有声音的端到端延迟和设备播放连续性仍按语音验收处理，本次不增加模型推理或试听。

<a id="decision-0039"></a>

## Decision 0039: 对话页语音预检查与合成／交付流水线

日期：2026-11-07。状态：采用。

背景：用户点击开始才发现麦克风或模型未准备；分句合成等待整段 `on_audio` 返回，RTC 实时背压让下一段模型计算落在上一段播放之后，造成明显停顿。

选择：独立桌面 readiness 控制器在进入活动对话页时执行短暂丢弃式麦克风诊断、已选用本地模型加载及组件检查。持续监听仍须显式开始，不下载、转写或调用付费服务。准备不占业务锁，失效及在用配置沿用线程／代际边界。

协调器保留一个冻结后端顺序推理，将波形生产与异步交付解耦；已完成波形含交付中一段限制 3 段／24 MiB，构造中单段另限 24 MiB。首句优先，随后合并已到达的完整句子，保守处理边界近数字静音；不等待全文，不改变语速、音色和句内停顿，不引入并发 GPU 推理、交叉淡化或另一条播放技术栈。停止／插话取消预取及旧代际输出。

影响：本地模型提早消耗资源，继续尊重预算、手动设备策略与空闲释放；远程仅标「已配置，连接待验证」。LLM 流读取不等待波形背压，语音失败不撤销完整文字。音频索引连续，但不再承诺一句对应一个 WAV。

未解决：模型慢于播放或 LLM 长停顿仍可能供给不足；不将整句后端称为原生流式 TTS，不以软件提交间隔代替硬件听感、AEC 和真人门禁。[本轮证据](../validation/engineering/VOICE_READINESS_AND_PLAYOUT_2026-11-07.md)分开记录自动化、真实本地服务与设备诊断。

<a id="decision-0040"></a>

## Decision 0040: 安装包内配置 AI 服务与当前用户密钥保护

日期：2026-11-07。状态：采用。

背景：原「模型与服务」仅展示环境配置，安装包用户仍需手写 `.env`，无法在软件内完成首次接入。用户明确要求可安装包及 API 设置入口。

选择：保留兼容 OpenAI 的 provider，在原设置页内编辑基础地址和 API Key，通过 `GET /models` 读取目录后，从下拉列表选择推理／对话模型，不提供手写模型字段。对话可沿用推理模型；不请求生成、不自动选取或更换模型。保存前复核模型属于当前连接的返回列表，连接编辑使旧列表失效，空列表、权限及接口失败页内重试；无列表接口仍可沿用环境配置。配置文件位于数据库旁 `ai-services.json`，密钥使用 Windows 当前用户 DPAPI 加密后原子保存，QML 仅持有本次输入，不返回已保存密钥。配置校验与存储无 Qt 依赖，HTTP 探针留在 provider，桌面仅负责状态与翻译。

影响：桌面启动时显式保存的连接信息优先于环境；未保存时保持既有 `.env` 和进程环境行为。保存仅在重启后生效，活动会话不切换 provider；可显式恢复环境配置，损坏保存项不静默退回其他服务。CLI 继续读环境。打包白名单排除凭据文件，API Key 不写入 QSettings、安装目录、日志或发行物。Win32 密钥保护范围不跨 Windows 用户或机器，非 Windows 暂保留环境配置。

未解决：本轮只验证本机模拟 HTTP 的元数据请求及真实 Windows 加密／重载，不声明远端模型权限、余额、输出质量或付费调用通过；代码签名和干净 Windows 系统矩阵仍另验收。产物和工程证据见 [0.1.1 验证记录](../validation/engineering/WINDOWS_AI_API_PACKAGE_2026-11-07.md)。

<a id="decision-0041"></a>

## Decision 0041: 关闭主窗口时询问后台运行或退出

日期：2026-11-07。状态：采用。

背景：用户要求关闭窗口时能选择继续后台运行或彻底退出，并像常见桌面软件一样保存偏好。

选择：新增桌面生命周期控制器管理关闭询问、托盘恢复和退出；默认每次询问，支持记住后台／退出选择，
在现有外观设置中修改。窗口控制器拦截原生关闭事件并保留几何状态；标题栏、Alt+F4 和系统关闭走同一策略。
托盘和窗口更多菜单的显式退出绕过偏好，沿用 `aboutToQuit` 清理链。采用 Qt 原生
[`QSystemTrayIcon`／`QMenu`](https://doc.qt.io/qtforpython-6.11/examples/example_widgets_desktop_systray.html)，
主入口改为 `QApplication`，业务界面仍为 QML，不引入其他 UI 框架或常驻后台服务。

影响：后台只是隐藏同一窗口，已有准备、下载、语音、草稿和会话继续；不会隐式发送草稿或生成复盘。
默认 `ask` 与偏好校验兼容缺失／无效旧设置；不改变数据库。系统托盘不可用及系统注销时关闭直接退出，
避免不可恢复的隐藏进程；纯 QGuiApplication 探针不创建托盘。保存新模型配置后须真正退出再启动。

未解决：跨平台托盘与干净系统／更新后安装包需独立验收；Mock 后台保活不代表真实语音设备质量通过。
关闭策略测试与可见 Windows 检查命令见[桌面指南](../desktop/WORKSPACE.md#关闭窗口与系统托盘)。

<a id="decision-0042"></a>

## Decision 0042: 保留私有 Python 的依赖裁剪与升级清理

日期：2026-11-07。状态：采用。

背景：0.1.2 安装器约 298 MiB、解包约 911 MiB，包含整套 PySide6、Chromium 调试资源、开发工具与无关模块。用户要求缩小下载与实际磁盘占用，不能只提高压缩率。

选择：保持 Decision 0032 的非冻结私有 Python，不引入另一个打包框架。构建时通过产品 import、实际绑定加载、QML import scanner 及普通／延迟 PE 导入计算运行时闭包，保留发布版 WebEngine、必要平台／音频插件、软件图形回退和字体。删除 Qt 调试资源、开发文件、未用模块、额外语言资源及 Python 缓存／Tcl 开发部分，保留 `venv` 和 `ensurepip`。策略命名 `windows-slim-v1`，只作用于受限的全新构建目录；先验证完整计划再删除文件，不触及开发环境、用户配置、模型缓存或学习库。安装器改用 LZMA2 normal。

影响：源码 wheel 的应用资源不裁剪，私有运行时的改动通过实际发行物验证。构建保留完整裁剪报告；安装成功复制后，由包内无 Qt 的清理脚本仅删除明确退役项，拒绝越界和当前保留文件，避免升级后仍遗留旧包体积。卸载继续保留用户目录。新依赖或升级 Qt 必须重新检查闭包和动态资源，不能仅检查 Python import 成功。

验证边界：需要分别验证 QML、EPUB 可见渲染、音频解码、RTC/APM、离线 venv/pip bootstrap、首次安装及完整旧版到裁剪版升级；这些工程证据不替代真实 STT/TTS、硬件出声或真人语音验收。Qt WebEngine 仍是主要固定成本，后续若改为可选组件须另作产品与架构决策，不在本轮替换阅读器。


<a id="decision-0043"></a>
## Decision 0043: 单一状态所有者与可验证的后台退出

- 背景：功能增长使 7 个模块超过 800 行、17 个函数超过 100 行；取消 asyncio future 后执行器线程仍可能让退出后的进程存活。
- 选择：按材料准备、会话提交、投影、来源加载、安装测速、provider 配置／prompt／解析分责。Qt 使用一个 QObject 门面与普通职责基类，避免多份状态和重复元对象；Workbench 的会话事务仍由唯一实例提交。
- 执行：文件／投影、长材料索引、原件保存与运行环境安装使用具名受管进程，普通数据跨边界；每个事件循环最多两个任务。取消先给 5 秒协作时间，再仅终止所属进程树。退出协调器保留 Qt 循环、等待实际线程／进程／客户端清理；15 秒未完成时显示错误、允许重试。
- 兼容：CLI 保留命令，增加显式已读范围确认；默认 Mock 对齐当前语义主线，LegacyMock 明确覆盖旧 provider。历史 payload、数据库结构、缓存和来源坐标不变，分轮语音继续保留。
- 门禁：自有生产文件不超过 800 物理行、Python 函数含嵌套不超过 100 行，控制器通过公开接口协作。静态约束、离线行为、可见 Mock 和 wheel 分别记录。
- 限制：本轮不重建安装器，不将 Mock 等同真实 AI／真人语音验收；具体 SQLite 资产目录耦合在出现资产生命周期功能时再处理。
