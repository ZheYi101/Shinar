# 历史路线图与执行地图快照（2026-10-28）

> 归档状态：以下为整理前的完整历史快照，不是当前执行指令；其中角色、进行中状态、费用授权和技术方案不自动延续。当前工作见[路线图](../../planning/ROADMAP.md)，当前 AI 设计见[专项方案](../../architecture/ai/PREPARATION_AND_DIALOGUE.md)。

当前主线以 [Project Brief](../../product/PROJECT_BRIEF.md) 为准：沉浸提供语境，语音对话练输出。Phase 1 保留已有文本原型进展，Phase 1.5 补齐正式 MVP 的话题与语音路径；不得用文本原型的完成替代语音 MVP 验收。

## 当前工作：自由聊天与成本修订（2026-10-28）

根据新反馈，默认桌面取消选题和付费全书题库门槛。新增已读位置、本地原文索引、自由开场、真实兴趣产生后的少量方向与有预算的后台参考，保留既有付费资料和历史。主助手通过可见窗口重新导入完整小说，在 28.86% 已读范围完成六轮实际交流、复盘及重启恢复；新例子在独立本地库，默认个人库保留。

离线 244 passed / 1 skipped，Ruff 和 wheel 41 项资源及隔离启动通过。完整回复实测 1049.78–2448.47ms，0/6 低于一秒；上下文成本已缩减，尚未证明服务延迟改善。取舍、token、质量问题与证据见[自由聊天记录](../../validation/text/FREE_CHAT_2026-10-28.md)。语义召回、章节映射与连续语音仍待后续验证。

## 此前完整小说文本验收（2026-10-28）

用户已明确停止agent-orchestrator及子agent协作；后续由主助手亲自实现、运行与判断。本节保留此前整书题库验收状态，下面的角色分工与RTC实验记录仅保留历史，不再驱动当前任务。所有子agent已停止；RTC暂不新增实验。

当前验收材料为用户提供的完整《Lolita》EPUB：681437 字符、120942 词，已完成实际预处理、讨论、复盘和恢复。未用短篇、手工摘要或局部章节代替。推理和对话是独立角色；用户中途修改本地配置后已重启，当前两个模型均为 deepseek-flash，已有 Pro 准备保留。

- 余额恢复后复用 30 段，Pro 整书汇总 195.21 秒完成；现有 9 个人物、60 个预制话题 + 1 个自定义题，109 个有效回答分支，引用能回溯原文。资料已保存默认应用 SQLite，`prepared_notes.md` 更新为完成稿。
- 已通过可见 Windows 窗口完成 3 段共 17 轮真实交流（5 / 9 / 3）、3 次复盘、材料重导入、切换历史和重启恢复。包括错误前提纠正、异议、个人态度改变、跨场景承接与自然结束。后台包实际进入 10 次 Flash 请求，失败不阻断聊天。
- 性能目标未达成：17 轮模型完整回复中位数 1557.09ms，范围 1387.25–3003.05ms；15 轮按键至 UI 完整操作中位数 1641.95ms，最大 5101.24ms，慢轮次保留。最新三轮 UI 为 1614.14 / 1603.12 / 1443.41ms。1 秒继续作为优化目标，不用首字替代完整回复。
- 修复自由分类泛滥、自定义题未准备就跳回旧对话、重复导入覆盖自定义题等实机问题；讨论规则提升为 system 指令。按角色设置 120 秒空闲连接池，localhost 复用已验证，线上 SSE 仍重连，尚未证明提速。
- 最新当前工作区离线回归 230 passed / 1 skipped（62.07s），Ruff 通过；含新增本地语音库的 wheel 40 项 QML/图标/许可资源及隔离启动检查通过。实际文本记录、早期失败和质量限制见[小说验收](../../validation/text/NOVEL_ACCEPTANCE_2026-10-28.md)，STT/TTS 和 LiveKit 尚未真实验收。
- 剩余优化：更自然的开场和回应、保守的表达建议、线上连接/服务等待与 UI 长尾分析，以及随后独立推进连续语音。当前文本功能已实际跑通，不能据此称整个语音产品完成。
- 原文与实际会话保存在正常应用的本地 SQLite，工具副本位于忽略目录；不提交电子书、凭据、原始推理或完整模型日志。

本地交付增量：正常打开软件可看到《Lolita》的准备资料和 3 段真实历史；重复导入及更改模型后均保留完成资料，不自动重做付费分析。SQLite WAL、材料历史选择和只读本地模式可用。操作证据与最新状态见上方验收记录；后文余额不足和协作角色表均为历史。

## 历史执行地图：解决RTC连接并接通连续音轨（2026-10-24）

以下为 2026-10-24 当时的执行快照，表内“进行中”等状态不代表当前工作。现由上面的真实长篇文本验证主线替代；用户已停止该协作方式。历史目标是排查 LiveKit 连接超时、先验证 RTC/连续音轨/打断，再接 STT/TTS；未完成的真实 RTC 验收仍保留，不以文本阶段进展冒充通过。

长期专业协作价值：**高**，复用当前任务内稳定subagent，父Agent只做协调、依赖恢复与证据整合；不新建用户可见对话。当前并发为父Agent＋3个专业负责人。

完成标准：定位连接等待的具体阶段并解决；真实两参与者连接，单轮持续数十个以上非零PCM帧、文本增量/完成；用户取消后旧文本/PCM不再呈现、下一轮可正常恢复；显式退出/重入、异常清理及独立OS进程/端口检查。RTC独立通过后推进可替换流式STT/TTS接入，区分mock、真实网络服务与真人设备证据。默认本机loopback、隐藏自有子进程；不新增公网部署、采购或防火墙/管理员改动。若固定SDK确需受控本地私有接口，先交具体证据和最小替代由协调者裁决，不把自设127限制当永久产品约束，也不擅自开放公网。

| 工作包/角色 | 负责人 | 文件/责任边界 | 依赖 | 状态 | 验收输出/下一步 |
| --- | --- | --- | --- | --- | --- |
| 协调与集成裁决 | `/root` | 本执行地图、goal、范围/接口、证据审查 | 各负责人证据 | 进行中 | 先解决真实RTC，再接语音；不把局部失败写成整体完成 |
| RTC根因与实现 | `livekit_probe` | realtime、probe脚本/测试、LIVEKIT/README/env/Decision0013、必要可选依赖 | 已观测候选地址不匹配 | 进行中：单个本机私有UDP接口修复 | 唯一实际RTC实验者；HTTP127保留，RTC UDP精确单个OS本机/SDK候选RFC1918地址，TCP0；按真实media/取消结果修复并交独立验收 |
| 独立根因/代码审查 | `independent_audit` | 只读官方/安装源码及Fake复现，CODE_AUDIT新小节 | 与RTC owner横向分工 | 进行中 | 不并行启动server；给可证伪缺口/来源，后续复验新缺陷 |
| 独立RTC验收/语音接入边界 | `research_services` | TEXT_ACCEPTANCE新节、服务与产品文档/索引；不改实现 | 实现冻结；STT/TTS实现依赖RTC通过 | 进行中：先只读 | 当前核配置存在性/流式接口方案，不输出值；owner交接后真实独立PCM/取消/重入验收 |
| 桌面与业务集成 | `desktop_surface` / `dialogue_backend`（可唤醒） | 各自已有实现边界 | RTC与语音契约就绪 | 未开始本轮修改 | 保留前轮稳定UI/Flash核心，仅有明确接线需要再分派 |

| 证据 | 工作包/负责人 | 结论 | 等级与定位 | 时间/候选 | 覆盖与限制 |
| --- | --- | --- | --- | --- | --- |
| <a id="l0"></a>L0 | 用户决策/协调 | 用户明确继续全自动，要求解决RTC并先通过音轨/打断，再STT/TTS；1秒仅优化目标 | 当前用户实际指令，新goal active | 2026-10-24 | 替代前轮‘有界探针收口’执行状态；前轮事实不删，不将1秒重新设成硬门 |
| <a id="l1"></a>L1 | RTC/livekit_probe | 已形成阶段分解并开始实际读查 | 负责人消息；尚无新运行结果 | 2026-10-24 本轮开始 | A asyncio/FFI/子进程，B HTTP/WS与代理绕过，C native/ICE；仅代理变量名/存在性、白名单阶段/候选类别等，不落秘密或用户内容 |
| <a id="l2"></a>L2 | 独立根因/independent_audit | 未发现已设置代理环境变量或明显Python错loop接线；native候选过滤仍是假设 | 本机环境存在性与安装SDK/脚本只读审查 | 2026-10-24 初读 | HTTP/HTTPS/ALL/NO_PROXY大小写均未设置；asyncio.run内创建Room，SDK用call_soon_threadsafe投目标loop。不能据此排除所有代理/FFI问题；正查connect timeout和固定WebRTC loopback约束，owner负责实际信令/阶段观察 |
| <a id="l3"></a>L3 | 语音边界/research_services | 当前STT/TTS配置均不齐备；现有WAV adapter不是流式接口 | 只读process/.env存在性、官方增量协议及speech/Qt代码检查 | 2026-10-24 | 未输出任何值；RTC通过后再加独立流式端口。QwenASR预览可修正、completed才最终；TTS clear不等于远程取消，不承诺停止计费。无key先fakeWS+Mock LLM+真实RTC验证接线，不能当真实服务/真人通过 |
| <a id="l4"></a>L4 | 独立根因/independent_audit | 旧外层45s可能先于SDK原生连接重试结束，掩盖真正错误 | 固定官方Rust：signal connect_timeout10s，join_retries=3最多4轮，每轮native ICE15s | 2026-10-24 静态源码 | 最多约60s原生重试尚未结束即被45s取消；这是诊断接线不足，不能据此定因错loop/native未创建。已交owner采15s重试/阶段计数，必要有界延长观察或显式短内部参数；延长等待不算修复 |
| <a id="l5"></a>L5 | RTC实际诊断/livekit_probe | 信令/FFI调度正常进入native，实际候选地址族不匹配 | ignored build/livekit-probe/diagnostic-20261024-01.json；安全白名单原生/服务日志与心跳 | 2026-10-24 真实本机 | HTTP200，0.54sJoinResponse+publisher answer，0.57sConnecting，15.54/30.56s原生wait_pc超时重试；441心跳最大gap115.7ms。local18条均private（udp9/tcp9）、loopback0，remote3仅udp/host/loopback。进程清理通过；这是具体候选证据，不以静态假设替代运行事实，未保留raw日志 |
| <a id="l6"></a>L6 | 本机实验边界裁决/协调 | 批准基于L5的单个本机私有UDP接口最小修复，不需要新增公网权限 | 用户全自动本机RTC目标内的可回滚实现选择，root向owner/auditor/research交接 | 2026-10-24 | HTTP仍127，RTC TCP0，UDP只OS证明本机拥有且SDK采集到的单个RFC1918 IPv4 exact/32（优先已有host-only）；不新增接口/路由/防火墙/公网服务，随机短期凭据、参与者仍同机，STUN只同一自有IP/端口。结果标local-private-interface，不冒充strict-loopback；此为协调者实现裁决，不伪称用户新网络偏好 |
| <a id="l7"></a>L7 | 独立根因/independent_audit | 固定WebRTC默认过滤loopback链与诊断实测一致，私有接口替代合理 | CODE_AUDIT本轮节；Rust固定webrtc89d790b，默认IGNORE_LOOPBACK→factory options→allocator mask过滤；真实SDK线程队列离线复现正常 | 2026-10-24 | 已独立读取并核对L5 artifact，不另起server；旧45s/native未知不能当FFI故障证据。只审固定源码/候选与边界，不冒充修复通过 |
| <a id="l8"></a>L8 | RTC前置实测/livekit_probe | 本机选定私有接口已被SDK实际收集，开始单IP媒体实验 | 3s strict127候选预检，candidate-preflight-20261024-02.json；selected_local_candidate_observed=true | 2026-10-24 | OS无可用RFC1918 host-only接口，选唯一Preferred+Up物理RFC1918接口；排除198.18/VPN与169.254。HTTP200/Join/answer/Connecting、清理通过。最终验收需双向连续PCM、打断后旧帧0与新轮恢复，不能只用单向轨代替完整RTC基础 |
| <a id="l9"></a>L9 | RTC私有接口实测/livekit_probe | 地址匹配后仍原生ICE失败，loopback过滤不是唯一问题 | server6840：HTTP127+UDP单个本机私有地址；SDK完整60.30s/4轮native等待后ice_handshake_timeout，FFI connect回调已到 | 2026-10-24 本机真实实验 | local/remote均private，selectedIPobserved=true；Join/answer各4次、心跳最大gap115.8ms，所有清理通过。已得到真正底层错误，不能称修复通过；owner正增加Pub/Sub/STUN配对阶段与single-peer单变量对照，audit独立核默认兼容/接线，不凭空归因FW或改系统策略 |
| <a id="l10"></a>L10 | 独立根因/independent_audit | 当前server支持single-PC且target分派相符；SDK额外传输特性仍需隔离，FW profile未见显式阻断 | 固定SDK/server源码，Get-NetFirewallProfile只读摘要 | 2026-10-24 | SDK固定运行时启WARP/SPED与SCTP SNAP，不能仅从特性存在说它有bug；3个FW profile均未启用且未见显式Block，不排除其他WFP/虚拟层。root允许必要时只用一个有发行/源码依据的官方旧Windows SDK作隔离版本对照，不先改共享lock/环境或扩大网络范围 |

## 上一轮执行地图：DeepSeek 预整理与快速对话（2026-10-24，已结项）

以下两表及E0–E63为上一轮历史证据，当前进度以上一节L系列为准。

本节为本轮唯一权威状态源，历史初版记录保留在 `INITIAL_VERSION_2026-10-24.md`。模式：用户明确选择**全自动**，并授权使用现有 AI 配置进行有界真实文本测试；本阶段不要求 STT/TTS。总体 goal 已建立。

长期角色协作价值：**高**，涉及材料契约、后台推理、桌面交互、真实性能验收与 LiveKit 后续交接；本轮使用同一任务内稳定 subagent，不创建新的用户可见对话。父 Agent 仅协调、维护状态与审查证据。并发上限为父 Agent 加三个 subagent。

完成标准：长材料可导入并规范化为大纲、人物、丰富话题及常见回答分支；前台只使用对话模型，后台推理按需准备且不阻塞、过期结果不污染会话；真实公开素材验证对话质量、首字和完整回复延迟；移除 Windows 原生标题栏，材料/对话为两个主入口；整理国内服务与本地可集成性。完整回复 ≤1s 是待实测目标，不能用首字速度或 mock 替代。**用户已在实测后明确选择：1秒保留优化目标，文本功能通过后先做LiveKit探针**；因此不再以1秒为LiveKit探针硬门槛，性能未达事实仍保留。

| 工作包/角色 | 负责人 | 文件及责任边界 | 依赖 | 状态 | 验收输出/下一步 |
| --- | --- | --- | --- | --- | --- |
| 协调与集成裁决 | `/root` | 本执行地图、共享契约、goal、证据复核 | 各负责人报告 | 完成本轮阶段收口 | 纯文本/UI/有界RTC探针/服务与参考方案交付；明确完整语音MVP未完成，见本节结项边界 |
| 材料/快速对话后端 | `dialogue_backend`（可唤醒） | core/application/kernel/providers/infrastructure、非桌面测试；共享配置的RTC增量现归LiveKit负责人 | 官方模型参数及独立审查 | 完成并冻结 | 最终119 passed/1 skipped自验，19模块源hashdbbd27eb…；真实后台ready/Flash包含验证通过，最终离线与wheel待稳定 |
| 桌面界面 | `desktop_surface`（可唤醒） | desktop、桌面测试/预览、UI方案与runtime文档 | 后端流式与材料DTO | 完成并冻结 | workflow9 passed自验；分类滚动夹具和composer固定40px状态区各自回归，待最终独立整仓与wheel身份 |
| 产品与服务事实 | `research_services`（可复用） | SERVICE_SELECTION报告、PROJECT_BRIEF/MVP_SPEC | 官方资料 | 完成：静态调研 | 模型、国内STT/TTS、本地可能性、LiveKit依赖与公开素材已落盘，未证明供应商真实稳定性 |
| 独立文本/RTC与分发验收 | `research_services`（可唤醒） | benchmark脚本、独立验收测试/报告与文档索引，不改实现 | 合法ICE候选及唯一差异完成 | 完成 | 最终166 passed/1 skipped、wheel5ae286b5…、资源与依赖/文档检查通过；RTC连接失败及完整1秒未达如实保留，无新增调用 |
| 独立代码审查 | `independent_audit`（可唤醒） | 只读后端/RTC契约与生命周期，CODE_AUDIT报告 | 合法ICE配置/诊断窄差异冻结 | 完成：无未闭必修缺陷 | 独立33项diagnostics/transport与原始反例通过；固定官方源码/DLL静态证据落盘，R1/R2保持；不替代真实RTC |
| 新方案文档对照 | `reference_review`（可唤醒） | REFERENCE_PLAN_REVIEW报告；只读DOCX与现有代码 | 用户新增DOCX参考与E35 | 完成：最终事实同步 | 已保留旧快照并交叉引用一次available/included通过；intent_match/benefit仍未验，不扩实现范围 |
| LiveKit 对话层 | `livekit_probe`（可唤醒） | realtime新模块/tests/scripts、LIVEKIT文档、依赖/env/README窄RTC增量与Decision0013 | 合法127-only配置与最终独立probe | 完成有界探针交付：真实连接未通过 | client_connect约44.9s被外层operation_deadline取消，native创建not_observed；不称ICE定因。未到真实双参与者/PCM/data/cancel，未接桌面语音；最终wheel/文档已冻结 |

| 证据 | 工作包/负责人 | 结论 | 等级与定位 | 时间/候选身份 | 覆盖、结果及限制 |
| --- | --- | --- | --- | --- | --- |
| <a id="e0"></a>E0 | 前一轮初版 | 70项通过、1项真实测试跳过；wheel资源36个 | 历史单元/Mock UI/资源检查，见 INITIAL_VERSION | 2026-10-24 前一轮工作树 | 保留历史；不覆盖本轮新架构、真实DeepSeek性能或LiveKit |
| <a id="e1"></a>E1 | 产品事实/research_services | 用户两个模型ID均有效；推理/对话需分开thinking参数 | 官方静态文档：api-docs.deepseek.com/quick_start/pricing/、guides/thinking_mode/ | 2026-10-24 03:28 UTC附近 | 当前Flash为V4.1-Flash-1017，Pro为V4-Pro-0813；未证明本机凭据调用与延迟 |
| <a id="e2"></a>E2 | 后端/dialogue_backend | 最小兼容契约已交接 | 接口静态方案，后端负责人消息 | 2026-10-24 本轮 | Topic新增category/answer_branches；analysis新增outline/characters/chunks；send_message(on_delta)与timing；实现和行为待验 |
| <a id="e3"></a>E3 | 服务/research_services | 已识别日语支持差异及额外RTC依赖；选定青空文库『蜘蛛の糸』作为公开测试素材 | 官方资料静态调研，完整来源待 SERVICE_SELECTION 报告 | 2026-10-24 本轮 | 阿里/火山列候选；腾讯独立流式TTS不能外推为支持日语；LiveKit还需token/agent/RTC/turn能力，未部署、未实测稳定性 |
| <a id="e4"></a>E4 | 后端/dialogue_backend | 增量分块/断点与后台准备实现方案已形成 | 负责人静态实现进度，尚未独立运行 | 2026-10-24 本轮工作树 | 约12k字符分块、hash复用和落库；话题预算60；单并发/调用上限/超时/代际校验；默认材料预算须可配置且显式提示 |
| <a id="e5"></a>E5 | 后端/dialogue_backend | 首轮后端45项通过（实现者自验） | 单元/服务测试：pytest tests/test_prepared_dialogue.py tests/test_discussion_workflow.py tests/providers/test_openai_compatible.py tests/kernel tests/application tests/infrastructure，RUN_REAL_AI_TESTS=0 | 2026-10-24 本轮 | 分块断点、流式失败回退、后台不阻塞/代际、双thinking、CoT过滤、EPUB/XLSX/视频旁挂；不覆盖真实HTTP与UI，待独立复核 |
| <a id="e6"></a>E6 | 服务/research_services | 服务研究和阶段产品文档已交付 | 静态官方资料调研：docs/research/SERVICE_SELECTION_2026-10-24.md | 2026-10-24 | 覆盖四种AI服务、RTC/token/agent等附加依赖和本地分发；价格及地区可变，未实测SLA、音质或国内网络 |
| <a id="e7"></a>E7 | 桌面/desktop_surface | 首轮QML加载/渲染通过（实现者自验） | Mock/UI：test_desktop_imports 8 passed；9张offscreen截图 | 2026-10-24 本轮 | 首次失败为AbstractButton.action FINAL命名冲突，改glyph后修复；当前两主入口/自绘顶栏/流式桥已接线，长话题交互与窗口控制仍在验；offscreen不能证明原生拖动/DPI |
| <a id="e8"></a>E8 | 后端/dialogue_backend | 后端46项通过；旧active会话继续发送不回退到Pro关键路径 | 单元/服务测试，同E5命令组；替代E5的45项快照 | 2026-10-24 后端稳定工作树 | 仅升级旧会话未来配置，不改历史；当前.env非敏感字段已与用户配置一致，key仅查存在未输出；真实HTTP和性能仍待验 |
| <a id="e9"></a>E9 | 桌面/desktop_surface | Windows真实平台隐藏窗口没有原生标题栏 | 目标Windows本地静态原生窗口检查：scripts/check_desktop_window.py，exit0；platform=windows，visible=false，style=0x860b0000，WS_CAPTION=false，DPR=1.0 | 2026-10-24 本轮 | 无可见窗口；另有offscreen最大化/恢复/最小化/关闭/Alt+F10/8边缘/geometry测试；不能证明物理拖动和跨DPI |
| <a id="e10"></a>E10 | 独立验收/research_services | 2项离线独立验收通过，真实HTTP开始 | 单元/服务测试：独立验收测试；有界probe输出 build/text-acceptance/results.json（ignored） | 2026-10-24 本轮 | 首次夹具误把结束复盘的correct_answer当作前台调用，修正计数边界后通过，非产品失败；真实结果未回报，不记通过 |
| <a id="e11"></a>E11 | 后端/dialogue_backend | 68项非桌面测试通过（实现者自验） | pytest tests/test_prepared_dialogue.py tests/test_discussion_workflow.py tests/providers tests/kernel tests/application tests/infrastructure tests/core，RUN_REAL_AI_TESTS=0 | 2026-10-24；扩大E8覆盖 | 包括后台互斥锁、取消、预算与确认成功才保存；不代替独立真实HTTP或桌面验收 |
| <a id="e12"></a>E12 | 独立验收/research_services | 首次完整离线86 passed / 1 failed（20.03s） | 独立单元/Mock UI全套，RUN_REAL_AI_TESTS=0 | 2026-10-24；UI并行修改期间快照 | 唯一失败为test_desktop_workflow键盘大小写夹具，已交desktop_surface判定；当前不是全套通过，等待稳定树复验 |
| <a id="e13"></a>E13 | 桌面/desktop_surface | E12失败已定位为QTest键码/字符重载夹具；单项复验1 passed | Mock/UI测试，精确保留`customTopic == 'friendship choices'`断言 | 2026-10-24 稳定UI候选 | 改用显式Qt.Key键码重载；保留QQuickWindow逐键、自定义话题/流式/确认消息/计时检查，完整独立复验待回报 |
| <a id="e14"></a>E14 | 独立审查/independent_audit | 70项离线测试通过，但额外FakeClient复现两个准备契约缺口 | 独立单元/静态复核，CODE_AUDIT报告待收口 | 2026-10-24 本轮 | 缺source_excerpts的后台结果仍ready；缺answer_branches的自定话题未重试仍成功；不能以现有测试通过掩盖，已排修复。首次唤醒后端因并发槽满失败，等待审查员结束释放槽位，其他工作继续 |
| <a id="e15"></a>E15 | 独立审查/independent_audit | 首轮审查正式交付并完成缺陷交接 | docs/validation/engineering/CODE_AUDIT_2026-10-24.md（含候选HEAD与6文件SHA256） | 2026-10-24 | A1高、A2中，皆本轮必修；后端已唤醒修复。修复前真实探针保留历史，后续仅对受影响路径作有界差异复验 |
| <a id="e16"></a>E16 | 桌面/desktop_surface | 16项桌面自验通过，代码与参考记录稳定 | Mock/UI测试；UI_SURFACE_PLAN/QML_RUNTIME；build/ui-preview/material-topics.png、streaming.png | 2026-10-24 本轮 | 分类/搜索/大纲人物/分支折叠，两主入口与次级nav2/nav3，流式及计时；截图为Mock。旧语音模拟测试保留；真实拖动/Snap/跨DPI与多屏未验 |
| <a id="e17"></a>E17 | 真实文本/research_services | 修复前预制题前4轮完成，完整回复≤1s目标0/4，当前失败 | 真实DeepSeek HTTP探针，临时DB仅计数/计时元数据；最终汇总待完成 | 2026-10-24 本机账号/网络/公版短篇 | 分析10题/20分支/4人物；TTFT774/1211/1176/1249ms，完整1174/1532/1565/1668ms。正在自定义题；不等同最终质量/费用或修复后候选。已交后端有界优化，LiveKit不启动 |
| <a id="e18"></a>E18 | 后端/dialogue_backend | A1/A2双层校验已修，88项非桌面自验通过 | 新core preparation_validation与provider/Workbench边界；新增20回归参数用例 | 2026-10-24 修复后工作树 | 新生成分支/证据严格，部分无效剔除、全无效有限重试；不破坏旧payload默认值。独立审查已唤醒，真实仅差异复验，不据此先标gate通过 |
| <a id="e19"></a>E19 | 真实文本/research_services | 基线6轮结束，完整≤1s仅1/6，性能门失败；前台仅Flash且流式保存一致 | 真实DeepSeek HTTP：TEXT_ACCEPTANCE_2026-10-24.md；03:38:07–03:45:25 UTC，exit1为性能失败 | 2026-10-24 修复前候选；加载字节码与采集SHA恰逢变更，候选精确性有限 | 完整904.7–1668.3ms，中位1397.8；TTFT493.6–1249.4，中位1053.7。10题20分支9大纲4人物、自定5分支、两次复盘/恢复通过结构启发式；后台45s超时、命中0，预测提速未证明。分析170.4s/自定义69.4s/复盘103.4和41.5s；已观察58397 tokens，取消请求计费未知 |
| <a id="e20"></a>E20 | 独立审查/independent_audit | A1新入口/A2定向复验通过，但发现A1-R历史消费缺口 | 原FakeClient拒绝且2次重试，52项定向通过；CODE_AUDIT追加候选SHA | 2026-10-24 首次修复候选 | 宽松读取保留，但匹配revision的旧无引用snapshot仍可进入reply；已交后端消费点修复，不因107测试通过而关闭该项 |
| <a id="e21"></a>E21 | 独立验收/research_services | 全仓离线107 passed（23.47s） | RUN_REAL_AI_TESTS=0 pytest -q --ignore=tests/engine/test_real_provider.py | 2026-10-24 严格验证器候选 | 覆盖桌面/后端，替代E12失败快照；不覆盖随后A1-R与性能prompt/low-effort改动，须受影响复验 |
| <a id="e22"></a>E22 | 服务/research_services | Pro背景小任务可用enabled+low，材料分析维持high | 官方静态参数：thinking_mode与list-models支持low/high/max（medium映射high） | 2026-10-24 | 已批准后端小任务预算优化，不代表真实准备速度已达标；后续最多1custom+3Flash和一次有界prepare等待，总前台≤10 |
| <a id="e23"></a>E23 | 独立审查/independent_audit | A1/A2/A1-R全部独立复验关闭 | CODE_AUDIT最终8文件SHA；定向40 passed及旧snapshot双样本恢复复现 | 2026-10-24 来源验证稳定候选 | 无效新准备拒绝/最多两次，旧无引用不消费、有效仍可用，历史消息和payload不改；不外推真实语义/性能、跨重启预算或极端退出 |
| <a id="e24"></a>E24 | 独立验收/research_services | 长篇均衡夹具通过，准备召回边界继续完善 | 3项独立验收：自写9章108000字符/72候选，预算60题 | 2026-10-24 尚未最终冻结 | 60题仍涵盖每章和末章、chunk覆盖全文；自定义context前部偏置由后端补全书相关选择。没有真实长篇调用，不冒充整本内容质量验收 |
| <a id="e25"></a>E25 | 独立验收/research_services | 尾章自定义题定向测试失败，已交后端修复 | 自写长材料：最后chunk内部偏移6000处“紫の鍵”，Pro prompt未含匹配原文 | 2026-10-24 全书召回改进中快照 | 已选中chunk但只取头部，属于产品上下文选择缺陷而非harness；须提供query邻近片段并保留出处，真实差异probe继续等待冻结 |
| <a id="e26"></a>E26 | 分发/desktop_surface | 新wheel构建及原资源检查通过39项；增强探针发现选择器缺口 | uv build --wheel；scripts/check_wheel_resources.py，初版均exit0 | 2026-10-24 本轮wheel | 原探针未显式验证WindowController来源/新控制对象且window QSettings未隔离。增强脚本首次resize_topLeft查找失败，因Repeater委托不在QObject树，正改视觉树；非产品或包资源失败，增强后复验待回报 |
| <a id="e27"></a>E27 | 分发/desktop_surface | 增强探针通过：39资源、隔离WindowController和隐藏窗口控件 | check_wheel_resources.py视觉树查找，源码未变；wheel SHA256 D05017B125D0AB515A0EFE9D920795D1B9B073876978FC48FF238F892A413449 | 2026-10-24 UI稳定包；非最终core候选 | 测试设置隔离，无真实API/全局安装/发布；E26夹具覆盖缺口已修。core仍在改，最终交付需冻结后重构包，不复用本SHA作最终核心版本 |
| <a id="e28"></a>E28 | 后端/dialogue_backend | 全套114 passed/1 skipped，但冻结前发现SDK参数改名，需请求体级适配 | 既有离线suite与安装版ChatOpenAI._get_request_payload静态检查 | 2026-10-24 冻结前 | max_tokens被改为max_completion_tokens，不能仅凭settings声称DeepSeek预算已生效；正改同库BaseChatOpenAI适配并用httpx.MockTransport验证真实JSON字段，未追加真实调用 |
| <a id="e29"></a>E29 | 后端/dialogue_backend | 全部修复和有界性能优化冻结，自验115 passed/1 skipped | pytest -q，RUN_REAL_AI_TESTS=0；MockTransport真实JSON断言24000/2500/160及high/low/thinking；19文件aggregate SHA256 2cb469854183193c5a84c971ddcce15a1bf834856e08cb79fb1b3edf0208db59 | 2026-10-24 冻结候选 | source校验、全书均衡/尾章query邻近窗口、Flash包去重37.4%（确定性夹具字节）和240s/1800s可配置期限；不保证实际token等比例或1秒。research开始1custom+一次背景等待+3Flash，累计9前台，不重复整篇分析/复盘 |
| <a id="e30"></a>E30 | 独立验收/research_services | 最终离线115 passed；冻结源码与最终wheel逐字节一致，分发检查通过 | 独立pytest -q --ignore=tests/engine/test_real_provider.py，RUN_REAL_AI_TESTS=0（23.42s）；uv build与增强39资源/WindowController probe | 2026-10-24 冻结树；wheel SHA256 021733CE81A0A0DCABAE1976EFE383F3360421610ADEEEDF1A1AFFB9CE26C135 | 19个后端模块与冻结树逐字节匹配；覆盖尾章细节/均衡/来源/历史消费/UI。仍不证明真实HTTP性能或物理跨DPI；差异HTTP在跑 |
| <a id="e31"></a>E31 | 真实文本/research_services | 冻结后差异probe：文本检查通过；完整≤1s仅1/3，后台仍未ready | 真实DeepSeek HTTP，03:56:53–03:59:23 UTC；19文件aggregate前后均2cb46985… | 2026-10-24 冻结候选 | 1custom103.7s/4有效分支；3Flash完整731.4/1259.6/1060.7ms，TTFT424.2/1007.1/686.2。后台low+2500两次22.9/20.2s、各2500输出tokens，最终unavailable、0命中；未记finish_reason不能断言截断。累计9前台，无重复整篇分析/复盘。功能/引用路由不是后台预测或1秒目标通过 |
| <a id="e32"></a>E32 | 用户决策/协调 | 已实际提交选择：1秒保留优化目标，文本功能通过后先做LiveKit探针 | 本聊天request_user_input_async实际回复，非预选项推定 | 2026-10-24 | 替代此前LiveKit的性能硬门，不抹去E19/E31失败事实；后台准备修复继续，不依赖该选择。随后用户追加DOCX要求参考，先评审再定探针接口 |
| <a id="e33"></a>E33 | 文档评审/reference_review | DOCX三层结构与当前方向一致，不阻塞本机RTC探针；计量需避免把可用包叫预测命中 | DOCX 48段/0表与代码对照；REFERENCE_PLAN_REVIEW报告编写中 | 2026-10-24 | 按意图分支/证据短包/Flash即时生成可吸收；prepared_hit目前仅有效包进入prompt，不代表intent_match或提速因果。文档P26/P35不覆盖用户最新1秒目标/本轮预测要求；TTL/范围版本键、阅读器与剧透控制属后续契约，未冒充当前已实现 |
| <a id="e34"></a>E34 | 后端/dialogue_backend | 最后BG候选冻结：微型证据包+low/4000；119 passed/1 skipped自验 | pytest -q，RUN_REAL_AI_TESTS=0；19模块aggregate dbbd27eb66d3097ba8eb67cf8f8839d40b3df7e53362e684f8b0f635f6d6610a | 2026-10-24 最终后台候选 | 1意图/1–2短要点/1精确引用，安全finish_reason和失败阶段诊断；E29旧预算候选保留历史，真实结果见E35 |
| <a id="e35"></a>E35 | 独立真实文本/research_services | 最终有界BG调用ready，唯一Flash确实包含有效预测包；完整1秒仍未达 | benchmark --real --background-only；前后源hash均dbbd27eb…610a；TEXT_ACCEPTANCE报告 | 2026-10-24 最终后台候选 | Pro input403/output939、10690.96ms、finish_reason=stop；Flash TTFT645.12/完整1060.34ms，prepared_hit=true、前台无Pro、退出任务0。仅证明就绪/包含，不证明意图匹配或提速因果；累计10前台到顶，19启动/89360观测tokens，另1取消用量未知，不再付费调用 |
| <a id="e36"></a>E36 | 独立离线/research_services | 最终整仓快照118 passed/1 failed/1 skipped，UI分类点击失败待修 | pytest -q；test_desktop_workflow.py:364，分类点击后12仍12 | 2026-10-24 最新整仓 | 尚不能记最终全绿；已唤醒desktop_surface判断产品或事件夹具。独立验收文件5 passed，benchmark无--real默认exit0且不读配置/不联网 |
| <a id="e37"></a>E37 | 文档评审/reference_review | 参考DOCX对照正式交付；RTC接口契约分派 | docs/research/REFERENCE_PLAN_REVIEW_2026-10-24.md，原DOCX SHA及7个代码SHA | 2026-10-24 | 可吸收预制意图分支/有界证据包/冷热缓存与四层计量；本机RTC只接确认文本、session/turn/generation/seq和独立PCM生命周期，取消后旧包不呈现，半截不入库。阅读器/严格剧透/跨用户缓存另需后续决策 |
| <a id="e38"></a>E38 | LiveKit/livekit_probe | 最小探针已分派，官方SDK与本机服务准备 | 负责人设计消息；尚未运行RTC | 2026-10-24 | 官方livekit/livekit-api可选extra，无agents框架；官方server下载核SHA，bind/node_ip/RTC均loopback，核对自有PID端口并finally回收；已确认付费进程退出，可安装依赖。不能把设计记为RTC通过 |
| <a id="e39"></a>E39 | 桌面/desktop_surface | E36暂未稳定复现，顺序桌面16项及整仓120 passed/1 skipped自验 | Mock/UI及离线全仓，约25.74s；新加按住按钮期间首次轮询的回归 | 2026-10-24 UI排查中 | 未改产品代码即可通过，不能将轮询重建猜测定为根因；正增强滚动可见性/指针移动/press-down-release的真实鼠标夹具，保留精确筛选和数量断言，不重试点击掩盖失败。独立最终复验仍待稳定 |
| <a id="e40"></a>E40 | LiveKit/livekit_probe | 官方server/SDK准备成功；首次socket审计发现非loopback监听即关闭，未连参与者 | server1.13.10校验下载，实际Windows自有PID端口审计；RTC仍未记通过 | 2026-10-24 探针准备 | 官方RTC TCP实现未按--bind绑定IP；正禁用TCP fallback并复核UDP。后续只接受实际socket均127/::1，接口过滤/广告候选不能替代地址审计；不修改防火墙或放宽边界，若做不到则停止该实际进程并保留约束 |
| <a id="e41"></a>E41 | 桌面/desktop_surface | 严格按下诊断发现composer异步状态造成录音按钮上移37px | 实际Mock/UI鼠标press/down事件，坐标(188,739)→(188,702) | 2026-10-24 UI修复中 | 已据此授权最小固定两行状态区，hover后重新取实时点并验证pressed；分类E36原故障仍不可稳定复现，不能直接等同根因。UI候选变化后需最终全仓与wheel重构 |
| <a id="e42"></a>E42 | 桌面/desktop_surface | E36分类失败已定位为滚动鼠标夹具，另立composer产品几何回归 | topicCategory1中心相对materialScroll为(143,-99)，旧helper只查全窗口而误点标题 | 2026-10-24 增强UI诊断 | 正按稳定布局校准contentY、确认视口内后只点击一次，保留down及精确数量/filter断言。不能用最终成功删除原失败，也不将分类夹具与E41的真实产品位移混为一因 |
| <a id="e43"></a>E43 | LiveKit/livekit_probe | 修正后实际socket均loopback且资源回收通过；首参与者ICE超时，音轨尚未通过 | Windows server1.13.10 PID70384：TCP127.0.0.1:17880、UDP127.0.0.1:17882，无RTC TCP；SDK wait_pc_connection，45s总界 | 2026-10-24 本机真实RTC尝试 | finally server_cleanup=true，SDK任务/streams清空；协议/取消离线15项通过。正在一次有界官方SDK诊断，不放宽地址范围；双参与者/真实PCM/重连未完成不能记通过。首次E40只记录error_code与cleanup=true，未留PID/具体地址明细，不伪造或再开通配监听复现 |
| <a id="e44"></a>E44 | 桌面/desktop_surface | UI修复冻结，workflow9 passed in16.83s；13张Mock预览刷新 | 实际QTest交互与几何回归；UI_SURFACE_PLAN记录；build/ui-preview/代表图 | 2026-10-24 最终UI候选 | 分类夹具只点击一次、viewport/pressed/精确筛选断言保留；composer固定40px有坐标不变回归。原轮询重建猜测未成立；旧包hash不作最终身份，独立整仓与最终重包仍由research负责 |
| <a id="e45"></a>E45 | 文档评审/reference_review | 参考评审已同步E35最新一次准备有效/实际纳入，旧快照和失败保留 | REFERENCE_PLAN_REVIEW报告，交叉引用TEXT_ACCEPTANCE末次真实段 | 2026-10-24 最终参考评审 | 明确Pro10.69s/Flash完整1.060s，不冒充intent_match/benefit；仅文档事实同步，无额外模型调用或实现变动 |
| <a id="e46"></a>E46 | LiveKit/livekit_probe | 最后single_peer_connection诊断仍ICE超时，不继续无界配置探索 | server PID65476实际仅127.0.0.1:17880/17882，finally cleanup=true | 2026-10-24 本机RTC第二诊断 | 未定位为唯一原因，不能断言native必不支持loopback。修正ice_servers空列表可能回退的配置声明，并将native SDK隔离短命隐藏子进程，由父进程限时/按PID核查退出；sdk任务清空不等于native句柄已释放。最终独立安全修正复验与打包待完成 |
| <a id="e47"></a>E47 | 独立RTC代码审查/independent_audit | 15项离线通过，但实证AudioSource关闭异常会中断其余资源清理 | FakeSource.aclose抛错后room未disconnect且connected仍true；CODE_AUDIT追加中 | 2026-10-24 新realtime候选 | 脚本串行finally也可能跳过client清理，已交owner本轮必修；代际/seq/取消草稿/SID门主路径有测试，但不得用15绿掩盖释放缺口。未启动RTC/AI，不背书实际音轨 |
| <a id="e48"></a>E48 | 独立RTC代码审查/independent_audit | R2：disconnect期间回调可再生consumer，close后仍1task/1stream | FakeRoom.disconnect触发track_subscribed的独立离线复现 | 2026-10-24 新realtime候选 | 当前无closing门且任务扫描早于断开；已交owner加关闭状态与尽力收尾，独立复验两项缺陷后再最终打包。其他session/generation/seq/SID主路径未发现新实质缺口，不外推真人语音 |
| <a id="e49"></a>E49 | 独立RTC代码审查/independent_audit | R1/R2原失败样本独立复验关闭；最终17 passed | CODE_AUDIT新RTC节7文件SHA；pytest tests/realtime -q（0.05s），另屏蔽SDK导入检查 | 2026-10-24 RTC修复候选 | R1仍安全报cleanup_failed但Room断开/connected=false/source清空；R2任务和stream均0。基础import不加载可选SDK，adapter缺依赖友好报错；未启动server/AI，实际PCM/ICE/语音仍不在通过结论中 |
| <a id="e50"></a>E50 | LiveKit/livekit_probe | 实现/脚本/依赖及运行文档冻结；只待独立探针结果补录 | docs/desktop/LIVEKIT.md、README/env、Decision0013；transport SHA9367B958…8260D与审查相同 | 2026-10-24 RTC冻结候选 | 明确无agents框架/基础强制依赖；最终非空IceServer空URL屏蔽SDK默认回退，秘密通过stdin；父进程60s截止及自有PID/socket回收。旧空ICE声明已纠正，真实双参与者/PCM仍未通过；research负责最终一次probe/全仓/wheel |
| <a id="e51"></a>E51 | 最终独立离线/research_services | 最终全仓138 passed/1 skipped in29.31s | RUN_REAL_AI_TESTS=0 pytest -q，TEXT_ACCEPTANCE最终段补录中 | 2026-10-24 后端dbbd27eb…+最终UI/RTC冻结树 | 覆盖修复后分类/composer及RTC17项；替代E36失败快照，保留旧记录。真实AI测试跳过，先前有界HTTP结果另列；不能从离线全绿推导RTC通路或真人语音通过 |
| <a id="e52"></a>E52 | 最终独立RTC/research_services | 唯一最终探针exit1/ConnectError，首参与者未握手；OS确认进程/端口清理 | server69988仅TCP127.0.0.1:17880/UDP127.0.0.1:17882；child27392 exit1；另查两PID不存在、两端口0；4源码/脚本前后hash一致 | 2026-10-24 最终真实本机尝试 | 真实双参与者/PCM/data/cancel未到达，不记通过；最终显式空URL IceServer及进程隔离已生效于此候选。清理以独立OS检查为准，不从Python任务数外推native释放；不再重复RTC或模型调用 |
| <a id="e53"></a>E53 | 最终分发/research_services | 最终wheel隔离检查与逐字节核对通过 | wheel SHA256 2efd7fdbe1bf84c6c97845a08aa7f0893ea890e35301e506e7dab4d67aadc4fb；39QML/SVG/license及WindowController probe | 2026-10-24 最终安装包 | 19backend+4realtime+39资源与冻结源一致；两SDK依赖仅extra，无SDK阻断下Mock load/start/send通过、RTC构造友好报缺extra。未装用户全局/未发布；旧E27/E30包仅历史身份 |
| <a id="e54"></a>E54 | 集成分诊/协调→livekit_probe | 空URL ICE entry的底层有效性尚未排除，重开一次只读窄诊断 | E52配置与ConnectError安全摘要；没有原生错误原因，当前仅疑点非定因 | 2026-10-24 E53候选保留 | owner先查实际SDK/官方转换是否允许empty entry；无静态证据不改再测。若无效，再给合法strictloopback方案与非敏感错误分类，不追加AI/公网，旧失败和wheel不抹去；本轮goal暂不标完成 |
| <a id="e55"></a>E55 | LiveKit/livekit_probe | 静态确认empty-URL不是合法disable机制，E54疑点成立 | PyPI1.1.21 attestation→python-sdks cf9aa122…→rust5a656c4b…/FFI0.12.80；C++转换直接push空entry；WebRTC ParseIceServersOrError返回SYNTAX_ERROR Empty uri；本机FFI DLL也含该字符串 | 2026-10-24 只读官方/安装字节证据 | E52候选有自造无效配置，不能据此判断loopback不可用；未重跑RTC/未改源码即提交证据。已授权最小合法stun:127.0.0.1:既有UDP端口、字面loopback校验和安全分类；离线后research最多一次RTC差异，不新增服务/监听/公网/LLM |
| <a id="e56"></a>E56 | LiveKit/livekit_probe | 合法127-only STUN及安全诊断最小修复冻结；43项realtime离线自验通过 | 新diagnostics.py、transport/probe/离线测试；5个realtime模块 | 2026-10-24 新配置候选 | 仅现有server UDP；phase/error枚举、连接elapsed/native创建证据等级，45s外部截止不冒充ICE创建成功；R1/R2关闭门保留。README/0012/0013/LIVEKIT同步旧无效配置与最终4000预算。待auditor窄差异与research唯一RTC/全仓/重包，不改旧失败历史 |
| <a id="e57"></a>E57 | 独立RTC差异审阅/independent_audit | 安全诊断仍需收窄native创建推断条件；唯一差异RTC尚未启动 | generic ICE timeout不能定位固定源码；须只认可精确wait_pc_connection timed out位置 | 2026-10-24 新诊断候选 | owner正修并加两个离线样本，research确认所有验收进程空闲，等重新freeze与审查许可后再运行；不将普通超时或外层deadline说成native已创建，不增加RTC调用数量 |
| <a id="e58"></a>E58 | 独立RTC差异审阅/independent_audit | E57分类误推断已关闭，已交research可运行唯一有界差异探针 | 33项diagnostics/transport独立通过；3份固定官方Rust源码缓存与联网原文逐字节相同 | 2026-10-24 最后诊断候选 | 泛化两种超时及外层deadline为not_observed，只有精确wait_pc_connection位置支持已创建的静态推断。URL为canonical127/精确既有UDP端口，无空列表回退；官方FFI保留空项/C++push/PeerTransport创建→wait链核实。仅静态和离线，不作native直接观测或真实RTC通过 |
| <a id="e59"></a>E59 | 最后独立RTC差异/research_services | 合法127-only配置仍未连接，client_connect为operation_deadline，native创建not_observed | 04:38:55 UTC；TimeoutError，client await44899.859ms由45s外截止取消；server56244仅127TCP17880/UDP17882，child62060 exit1 | 2026-10-24 合法配置冻结候选 | 不称ICE握手超时、不推断native已创建；双参与者/PCM/data/cancel未到达。探针自报进程/socket/server清理true，独立OS/前后hash与最终全仓/重包正在收尾；不再RTC/AI，旧无效候选与包仍留存 |
| <a id="e60"></a>E60 | 最后独立回归/research_services | 合法配置冻结树166 passed/1 skipped in25.81s；独立OS及指纹复核通过 | pytest全仓（真实AI关闭），5源码/脚本前后hash同；两PID56244/62060均不存在、TCP17880/UDP17882计数0 | 2026-10-24 最终合法配置候选 | 新45项realtime/诊断仍为离线；替代E51作为最新回归身份，138项历史保留。真实连接仍未通过，未用离线绿替代RTC；TEXT_ACCEPTANCE已记录，最终wheel等待README同步后重构 |
| <a id="e61"></a>E61 | 最终合法候选分发/research_services | 新wheel全部字节/资源/隔离/可选依赖检查通过，替代E53包身份 | build/package-check/lingualoop-0.1.0-py3-none-any.whl；SHA256 5ae286b5304e3562d3c920fa47abb2f594069dec78a6710c44af1dcbb4b40916 | 2026-10-24 最终交付候选 | 19backend+5realtime+39资源与冻结源相同；隔离frameless QML/控件通过、两SDK仅extra、屏蔽SDK时Mock业务链和友好缺依赖路径通过。原2efd…无效ICE候选包保留historical-rtc-invalid；打包绿不代表RTC通路绿，未全局安装或发布 |
| <a id="e62"></a>E62 | LiveKit文档收口/livekit_probe | 最终事实/旧无效配置/新包身份已同步，不再改实现 | LIVEKIT.md SHA1ae647ad…1458869；README/Decision0012/0013；TEXT_ACCEPTANCE最终段 | 2026-10-24 最终文档 | 本轮只完成‘有界探针代码与实测’，没有完成真实连续语音；外deadline/native未知、旧失败、来源边界均保留。后续完整语音MVP仍需RTC连通、流式STT/TTS及真人三轮验收，Phase1.5/2.5相关项保持未勾选 |
| <a id="e63"></a>E63 | 最后文档与数据边界/research_services | 差异检查、6份文档本地链接、extra/lock与最终/历史包身份核对通过 | git diff --check exit0（仅CRLF提示）；有限文本key形态/数据后缀检查0命中；最终包5ae…及历史2efd…SHA复核 | 2026-10-24 收束快照 | 仅.env.example被跟踪，真实配置/汇总/build忽略，暂存0、无提交/推送；不是完整历史或忽略目录secret审计。已有修改保留，所有真实RTC/模型测试结束 |

本轮结项边界：依据用户先做纯文本、文本功能后先做本机探针的阶段顺序，已交付材料准备/快速文本讨论、MD3桌面、公开素材真实调用、参考DOCX对照、服务清单和有界RTC探针代码与实测记录。**本轮阶段goal收口不等于完整语音MVP完成**。完整回复稳定低于1秒尚未达成；合法本机RTC在连接阶段被外层截止取消、根因未知，真实双参与者/PCM/data/取消/重入及STT/TTS/真人三轮均未通过或未运行。预测意图准确率、提速因果、长篇整本真实语义质量、国内三网与跨DPI体验仍需后续专项验收。最新可交付wheel为E61，最新离线回归为E60；不使用旧包或旧空URL错误替代当前事实。

范围边界：视频文本阶段以旁挂字幕或已有转写进入，不能假装文本模型已观看画面；Excel与EPUB均纳入材料导入，兼容用户所说的小说文件。不会输出密钥或提交真实学习数据/模型原始日志，不自动发布公网或购买服务。

已协调的阶段行为：依据用户本轮“对话全部由对话AI执行、优先速度”，新讨论的前台路径不再调用 Pro 逐轮纠错。设置本阶段提供结束后/关闭；旧 `immediate` 偏好须在 UI 明示延后到结束，保留历史数据及旧 `options=None` 集成语义。不能把这个阶段限制隐去或把未运行的即时反馈标为通过。

## Phase 0: 项目定义

- [x] 初始化基础文档
- [x] 明确“沉浸语境 → 话题推荐 → 语音输出”的产品主旨（2026-10-24）
- [ ] 确定开源许可证
- [x] 确定第一版技术栈
- [ ] 确定 MVP 的首个目标语言和示例材料
- [ ] 定义插件 manifest、capability registry 和权限模型 v0
- [ ] 定义 Pattern manifest、capability requirements 和第一批学习 Pattern 清单
- [x] 确认 Python-first Agent Kernel 方案并将 Decision 0004 升级为 Accepted
- [x] 沉淀真实输入学习闭环的理论依据和 EnglishLearningWorkflow 实践经验
- [x] 实现无 UI CLI POC，打通材料加载、分析、练习、复盘和导出

## Phase 1: 文本原型与已有基础

- [x] 创建应用脚手架
- [x] 建立 PySide6/QML 桌面端和 Android 适配方向
- [x] 实现 Python core Pydantic models 和 session event schema
- [x] 实现 material lifecycle：raw source、lesson-ready text、segment metadata
- [x] 实现 Agent Kernel 的 direct deterministic runner
- [x] 实现材料创建和管理
- [x] 实现材料分析 pipeline
- [x] 实现基于材料的文本对话
- [x] 实现会话复盘和 review items
- [x] 实现 review outcome 和用户控制事件：again、hard、good、easy、pause、ignore、delete、archive、mastered
- [x] 实现本地 SQLite 持久化和启动恢复
- [x] 实现 Markdown/DOCX 材料导入
- [x] 重做桌面端三栏工作台 UI 和窄屏折叠规则
- [ ] 实现最小 plugin registry
- [ ] 实现 capability requirement check
- [ ] 实现内置 input-derived 文本学习 Pattern
- [ ] 实现 LangGraph AgentEngine adapter
- [x] 增加 LLM provider mock 和基础测试

## Phase 1.5: 核心语音 MVP

- [x] 从已提供的沉浸材料生成可选话题、开场问题和来源关联
- [x] 支持选择和自提话题，明确本次讨论内容范围（直接改写已有候选留到后续）
- [x] 实现以内容讨论为默认入口的 deterministic 流程，不强制先完成 lesson
- [x] 提供可选语境 roleplay，允许不扮演直接讨论
- [x] 接入可替换 STT/TTS protocol、独立云端 adapter 和 Qt 分轮录放音
- [x] 支持可编辑转写、文字补充和失败恢复（mock 覆盖；真实设备待验收）
- [x] 提供难度、纠错强度和反馈时机设置
- [x] 将语音会话接入材料、消息、反馈、复盘和 review queue
- [x] 覆盖话题构造、结构化解析、语音失败回退和 provider mock 测试
- [x] MD3 主题、四页组件化、自适应导航与 wheel 资源打包
- [x] Qt Test 实际点击三轮模拟语音并验证重启恢复
- [ ] 使用真实服务和麦克风完成至少三轮语音讨论、复盘和恢复验收

具体实现与限制见 [初版验证记录](../../validation/mvp/INITIAL_VERSION_2026-10-24.md)。当前使用独立的 OpenAI-compatible 文件 STT/TTS 和分轮交互；不以完整插件框架、连续实时双向语音、avatar 或理论编辑器为前置条件。`voice-livekit` 留作连续语音候选。

## Phase 2: 学习闭环增强

- [ ] 增加练习目标模板
- [x] 原生 SRT/VTT 导入和 cue 时间信息
- [ ] 更完整的场景来源定位、材料原地编辑/删除和直接修改话题
- [ ] 增加 roleplay 深度，以及 shadowing / retell 学习 Pattern
- [ ] 将用户选择的学习方法映射为可配置 Pattern，逐步设计理论配置或导入方式
- [ ] 增加复习列表和基础提醒
- [ ] 增加 spaced-review 调度 Pattern
- [ ] 增加 CORA spoken-retrieval Pattern：Cold attempt、Observe、Rebuild、Automate
- [ ] 增加会话历史搜索
- [ ] 增加学习进度概览

## Phase 2.5: 实时语音与表现层增强

用户批准的本地语音增量：目录、硬件检测、下载管理与独立进程计算测速已实现，见[本地语音指南](../../desktop/LOCAL_SPEECH.md)。真人准确率/音质、日语 TTS 包固定、权重/前端再分发审核及本地 provider 连续语音接入仍待交付；本机短样例计算通过不代替下列实时语音验收。

- [ ] 评估 `voice-livekit` 等候选，增强基础语音为连续实时对话
- [ ] 记录语音延迟、打断响应、STT partial 稳定性和单轮成本
- [ ] 实现 `avatar-live2d` 插件原型
- [ ] 扩展更多 Pattern 与语音 modality / plugin capability 的组合方式
- [ ] 评估是否需要把语音插件升级为 voice subsystem

## Phase 3: 开源可协作

- [ ] 完成开发环境文档
- [ ] 增加 issue / PR 模板
- [ ] 增加示例数据和 demo workflow
- [ ] 完成隐私和数据导出说明
- [ ] 完成部署说明
- [ ] 完成第三方插件开发指南
- [ ] 完成第三方 Pattern 开发指南
