# 材料整理与快速对话参考方案对照评审

评审日期：2026-10-24。结论是保留现有 Python 材料准备、Pro 后台准备、Flash 流式回应三层边界，吸收方案对证据、预测消费和测量的约束；无需为了这份参考文档扩大本机 LiveKit 探针范围。完整回复小于 1 秒仍是优化目标，不能改成首字目标，也不再作为用户已同意先行的本机探针硬门槛。

本文件是参考方案与代码的设计对照，不是执行状态源或新增排期。实际状态、授权及证据更新仍统一见 [Roadmap](../planning/ROADMAP.md)；实测数据见 [文本独立验收](../validation/text/TEXT_ACCEPTANCE_2026-10-24.md)，服务事实见 [服务选型](./SERVICE_SELECTION_2026-10-24.md)。本评审只新增本文件，没有修改 core、provider、桌面、README 或 Roadmap，也没有发起模型调用、STT/TTS、RTC 部署或购买。

## 参考材料与证据边界

原文为用户提供的 `LinguaLoop_材料整理与快速对话方案.docx`，标题“LinguaLoop 材料整理与快速对话方案”，副标题“研究与产品设计建议 2026年10月24日”。通过 python-docx 读取，共 48 个顶层段落、0 个表格。下文 P 编号按 DOCX 的 `Document.paragraphs` 从 1 开始编号，包含标题和参考来源；不依赖 Word 分页。原文件 SHA256 为 `a57a9d7c3f3d54ea5005d31f22a79986d38c6aa2b28051b14fee6a55f2924b90`。仅提取内容用于评审，文内的建议和引用均不构成新的实施授权。

代码在协作中的工作树上只读核对，取样时间为 2026-10-24 12:06 +08:00；后续实现可以变化，本文不替其他工作包签署通过。已阅读 AGENTS、当前执行地图、PROJECT_BRIEF、MVP_SPEC，并核对 material_preparation、learning_workbench、domain、provider、session_runner、来源选择和对应测试。本文所说“已有”指代码存在；测试或真实调用的通过结论仅在注明既有验收报告的地方使用，未重新执行全仓或付费测试。

最新事实补充：下文已纳入 [历史执行记录 E35](../archive/2026-10/ROADMAP_SNAPSHOT_2026-10-28.md#e35) 对应的 04:07:19–04:07:31 UTC 最终背景探针，证明一次真实候选可用并进入 Flash prompt；原代码取样指纹及先前失败历史仍保留。完整证据见[文本独立验收](../validation/text/TEXT_ACCEPTANCE_2026-10-24.md)“最终背景修正：一次准备与一次真实消费”。

## 对当前交付的直接影响

1. **LiveKit 探针可以按既定边界继续。** DOCX P23–27 的即时路径不等待推理，与文本核心一致。探针先验证本机房间、双参与者连续音轨、文本增量、取消和资源释放；不需要先建立阅读器、向量库、图数据库、完整剧透系统或真实 STT/TTS。
2. **预制包保留为证据与交流方向。** P18–20 反对穷举问答剧本，正好支持现有 `AnswerBranch.user_intent/response_points/source_excerpts`。`suggested_reply` 只能是示例，不应直接替代 Flash 对本轮真实输入生成回复。
3. **预测的就绪和准确性必须分开。** P25 要求真实下一轮仍匹配；现有代码只证明 revision 与来源有效，尚未实现可核实的语义命中判定。不能把包进入 prompt 写成“预测准确”。
4. **保留用户的性能目标和最新先后顺序。** P26 讨论“有效首回应 <1 秒”，P35 建议第三阶段才做预测；用户当前要求保留完整模型回复 1 秒优化目标、保留 Pro 后台准备并先行本机 LiveKit 探针。因此吸收测量和对照方法，不用该文改写目标、删除预测或重排为完整材料工作台先行。
5. **可信来源的当前保证有限。** 精确子串校验可排除不存在的引文，不能证明引文蕴含回答观点，也不能证明引用在用户已读范围内。这些差别应保留在能力说明和验收中。

## 已有能力与方案的对应关系

| 原文定位 | 方案要点 | 当前代码证据 | 可据此确认的范围 |
| --- | --- | --- | --- |
| P4；“三 准备可复用的话题和答法包”P18–20 | 标准化、有限答法包、即时回应分层 | `application/material_preparation.py:49`；`core/domain.py:78`、`:102`；`providers/openai_compatible.py:230` | 有分片准备、话题/意图分支、Flash 紧凑包；不是全问题答案缓存 |
| “二 先建立可信的材料底座”P13–16 | 原文与派生内容分开，保留来源 | `core/domain.py:92`、`:264`；`infrastructure/material_import.py:25` | raw/normalized、source_path、字符范围、内容 hash、字幕 cue 已有；不等于完整原文件托管和章节/单元格锚点 |
| P15–16 | 分片、恢复、仅重做必要部分 | `application/material_preparation.py:15`、`:36`、`:52`、`:77` | 约 12,000 字符、按换行/句号找边界，逐片保存进度，同位置同 hash 复用；没有材料编辑后的依赖图或版本迁移 |
| P18、P21、P24 | 对话只装少量相关内容 | `providers/openai_compatible.py:234`、`:239`、`:572` | 当前题最多 3 分支、近期 6 条历史且限制字符、引用去重；尚非按本轮意图动态选择最相关分支 |
| “四 把即时回复与后台准备分开”P24–25 | 后台失败不能阻塞实际回应 | `application/learning_workbench.py:263`、`:507`、`:515`；`kernel/session_runner.py:132` | 发送前取消旧准备；新讨论没有逐轮 Pro 纠错，后台单并发、45 秒、代际校验；失败仍可走 Flash |
| P25、P27 | 预测不能当用户事实，材料不是指令 | `providers/openai_compatible.py:251`、`:306`、`:519`；`core/preparation_validation.py:24` | 有假设和不可信材料边界提示、结构和精确引用校验；不构成全面语义安全证明 |
| P31–33 | 默认不逐句测验，少量结束反馈，展示不算掌握 | `core/domain.py:70`；`kernel/session_runner.py:237`、`:256` | 默认结束后反馈，重点和复习项受限且关联真实输出；没有引入完整提示阶梯或自动习得评估 |

现有离线测试提供了针对性行为证据，例如 `test_foreground_stream_does_not_wait_for_reasoning_and_measures_both_times`、`test_stale_prediction_is_discarded_even_if_provider_ignores_cancellation`、`test_duplicate_send_and_failed_stream_do_not_save_partial_messages`、`test_legacy_unverified_snapshot_is_not_consumed_by_dialogue_model`。这些不能替代真实预测可用性、日语回答语义和语音体验验证。

## 预制话题与常见答案分支

DOCX P18–20 的核心价值是按“解释、比较、反驳、澄清、关联经历”等交流目的准备，而非枚举用户的原句。当前 `AnswerBranch` 已能表达 `user_intent`、回应要点、示例回复、追问和引文；材料分析生成 8–12 题、每题 2–4 分支，自定义题提示生成 3–5 个意图。新生成结果由 `validate_prepared_topic` 过滤无意图、无要点、无示例/追问或引文无效的分支，再限制为至多 5 个有效分支；汇总话题预算为 60，按各片轮流选取，避免仅覆盖前章（`material_preparation.py:92`）。

这支持“先离线准备常见回答依据，再由快模型回应”，但仍有三条边界：

- 引文校验是 `quote in source`，不是事实蕴含判定。带有真实引文但错误推论的分支仍可能通过。建议在有界质量样本中人工标注“直接支持、合理推断、缺证据”，推断应以推断语气表达；不能只查子串后公布准确率。
- Flash 包固定取题目的前 3 分支，尚未依据真实本轮表达排序。P19 的意图分类可以先作为准备 prompt 和测试样本的约束，不必新增一轮 Pro 分类。若以后做本地轻量选择，未匹配时继续使用少量来源与真实输入，不能强行套一个预测。
- 当前 `suggested_reply` 仍在包里，可能成为模型照抄的捷径。需要覆盖同一材料下赞同、反驳、改口、不完整意见和材料外问题，验收“接住当前表达、没有替用户假定理由”；不能把命中示例问题作为预制机制整体收益。

可吸收的小契约是保持有限分支，用同一 `evidence` 数组引用事实，分支表达交流意图而非预期用户事实。先沿用已有字段，只有在确认要提供分级提示/语言目标/剧透进度后，才为 P19 的新增字段作领域模型决策。

## Prompt 压缩与检索范围

现有 `_compact_reply_packet` 将重复引文放入单一数组，分支和后台结果通过 `evidence_ids` 引用；当前用户消息也从历史中去重。`test_dialogue_packet_deduplicates_evidence_and_current_user_without_changing_output_budget` 明确保证引用一次、当前输入一次和 Flash 160 token 预算未被改变。它证明压缩结构，没有证明同任务真实延迟提升。

`_reply_messages` 保留近期 6 条消息、历史尾部 2,000 字符、材料摘要前 300 字符。证据单条前 300 字符、示例/追问前 200 字符，分支只取前 3 个。这能限制输入，但字符截断可能丢掉否定、单位或引文的关键后半句。进一步压缩应保留来源关联和足够的完整语义，避免通过删证据、删当前用户条件来追求 1 秒。建议优先去重复规则与重复文本、选择完整相关证据窗口，再考虑减少分支；对超长句、关键事实位于引文尾部、用户改口加入限定条件分别设断言。

自定义题已有 `custom_topic_context`：在全部已存 chunk 的摘要、结构化内容及源文中做本地词汇匹配，选取相关片段与均衡分布片段，并加入匹配点附近的源文窗口（`core/material_context.py:53`、`:87`）。这是有限的本地相关内容选择，不是向量检索、完整长篇语义召回或跨来源知识搜索。现有尾章细节测试覆盖的是特定匹配窗，不能宣称小说任意情节都可召回。

DOCX P21 要求模型输入前完成剧透过滤；当前全书摘要、全书话题与自定义题选择没有用户已读位置或授权范围字段。当前应明确讨论范围来自已导入材料，避免宣传“严格无剧透”。真正实现已读范围时，必须先过滤原始 evidence、摘要和包，再构造 prompt；仅写一句“不要剧透”无法满足方案要求。这属于新范围模型决策，不是 LiveKit 传输探针前提。

## 前后台任务与预测消费

当前调度的实际约束如下：

- `LearningWorkbench` 单个准备锁；每次新会话最多调度 12 次，准备被 `wait_for(..., 45)` 限时。
- 新发送、切材料、分析、结束、reset、退出都会使代际失效并取消旧任务；任务返回时核对 generation、session id、message count、ACTIVE 状态及引用，才保存为 ready。
- 消费点再次校验当前消息数与引用，历史空来源准备不会因为 payload 可读取就进入模型。
- 本评审快照的 provider 已有微型 JSON 输出、DeepSeek low effort 和 4,000 token 覆盖、最多两次尝试；若供应商明确 `finish_reason=length`，报告预算耗尽，不原样重试。其前一个冻结候选仍是 2,500 token，不能把新代码配置当旧实测结果。

其中 generation/session/message count 对当前“单个 active 会话、不能会中换题、材料无原地编辑”的路径有效；它不是 P21/P25 的完整状态版本契约。`DialoguePreparation` 只有 `based_on_message_count`、意图、要点和引文，尚无 material revision、topic revision、options fingerprint、可见范围、生成时间或 TTL。调用次数也仅在内存中计数，新进程不会恢复持久费用预算；取消本机任务不能证明供应商没有已经计费。

现有 consumer 在任何真实回答到来时，若包的消息数仍匹配就把它放入 prompt，并由 Flash 的提示约束不要把预测当事实。它没有证明“真实下一轮意图匹配”。建议把指标区分为：

| 指标 | 含义与判定 | 当前证据 |
| --- | --- | --- |
| `preparation_available` | 当前轮前有结构、来源、revision 有效的包 | 最新 E35 单次真实探针 ready，精确引用与消息修订校验通过；此前未 ready 的历史保留 |
| `preparation_included` | 这个包确实进入该轮 Flash prompt | 最新 E35 唯一 Flash 请求含刚生成的候选意图，布尔断言通过；不保存内容 |
| `intent_match` | 本轮真实意图与候选相符 | 最新 E35 仍未测；需标注或经审查的轻量规则，不能从前两项推出 |
| `preparation_benefit` | 同条件下质量、延迟或成本的增量改善 | 最新 E35 仍未测；需开关对照，单次 included 不证明收益 |

E35 的 19 文件聚合 SHA256 在调用前后均为 `dbbd27eb66d3097ba8eb67cf8f8839d40b3df7e53362e684f8b0f635f6d6610a`。唯一 Pro 请求为 low/4,000 token，输入 403、输出 939 token，耗时 10,690.96 ms，`finish_reason=stop`；随后唯一 Flash 确认纳入该包，首字 645.12 ms、完整 1,060.34 ms。由此可确认 available/included 的一次真实闭环；完整回复仍超过 1 秒，后台约 10.7 秒也不保证快速连续每轮都就绪。该结果不与旧候选混算预测准确率、提速幅度或 P95。来源见[文本独立验收](../validation/text/TEXT_ACCEPTANCE_2026-10-24.md)“最终背景修正：一次准备与一次真实消费”。

既有 benchmark 的 `prepared_hit` 更接近第一项，`prepared_intent_visible` 接近第二项。保留历史字段可复现性，但在后续报告注明语义，不把旧字段改名后重算成预测准确率。

后续小契约建议是将准备视为 advisory candidate；缺失、过期、意图不匹配时继续 Flash 和原有有界证据，不新增前台 Pro 判断。新增编辑、已读范围或会中换题前再引入包含 `material_id/content_revision + topic_id + session_id + confirmed_message_revision + options/scope fingerprint` 的有效性键；预算/TTL 和键一起定义。验收应覆盖改口、跳题、换范围、取消后晚返回、同长度不同消息内容，且旧结果不能覆盖新状态。该扩展不应提前混进本次 RTC 探针。

## 缓存分层与失效

DOCX P16、P21、P25、P27 涉及不同缓存；不能合成一个“缓存命中率”。当前对应关系及建议如下。

| 层 | 当前实现 | 可吸收的约束与验收 |
| --- | --- | --- |
| 导入原文与规范化副本 | `LearningMaterial.raw_content/normalized_content/source_path`；保存文字和路径，不复制托管原文件 | 不声称“原文件始终可恢复”；未来移动/删除源文件仍可读已存文字，二进制附件保管另决策 |
| 分片分析恢复 | 按 `(start_char, end_char, content_hash)` 复用本材料的 `analysis_payload`；改变 profile 会清空分析 | 目前是断点恢复缓存；parser/prompt/schema/model 变化未进入键，插入前文后后续偏移改变会重算，不能称仅精准重做受影响语义片段 |
| 材料话题与答法包 | 跟随材料 analysis 和 profile 存 SQLite | 不是跨用户缓存；若以后引入多用户/能力/已读进度，先定隔离键，测试不同范围不得复用未读包 |
| 会话背景候选 | 存入 session，按消息数和原文再验 | 尚无 TTL/持久预算；应与历史 confirmed Message 区分，过期只丢候选，不改真实会话 |
| 供应商前缀缓存 | 没有本地控制层；探针可读 cache usage | 单独计 hit/miss token；不是答案缓存、不是预测命中，也不是本机可控制的隐私删除能力 |

DeepSeek 官方文档明确前缀缓存尽力匹配，输出仍需生成，可通过 `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens` 观察；不能由此承诺亚秒。稳定系统规则放前面、动态输入放后面有利于形成重复前缀，但重排后是否受益仍须用实际 usage 和同条件延迟验证。[DeepSeek Context Caching](https://api-docs.deepseek.com/guides/kv_cache/)

P27 的“删除时清索引、派生包与缓存”应解释为清理由应用管理的数据；不能宣称本地删除能同步抹去供应商的前缀缓存或调用留存。当前尚未实现材料原地编辑/删除及所有关联派生物清理，不将本方案写成现有隐私保证。

## 模型角色与延迟口径

`LearningLLMProvider` 仍是 core 端口，业务调用 `analyze_material/prepare_custom_topic/prepare_dialogue/stream_reply`；具体模型与协议参数留在 provider。当前实现将 reasoning client 与 dialogue client 分开，并对 DeepSeek 用请求体级适配保留 `max_tokens`。官方现行接口支持 thinking 开关及 low/high/max effort；这是参数能力，不能推导本项目准备速度。[DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)

DOCX P25 的时间、令牌和重试上限值得保留，但 low effort 不等于“会在用户思考期间完成”。独立验收第二候选的两次 low+2,500 请求约 22.9/20.2 秒均无可消费结果；当时未采集 finish_reason，预算耗尽是推断。新快照加入诊断和微型输出后，E35 已补充自己的有界真实证据，证明一次 ready 与 included；该成功不覆盖旧候选失败，也不证明意图匹配或预测收益。当前微型背景任务只获得一条既有引文、候选意图/要点与最近两条消息，它证明的最多是对已有证据的下一轮小整理，不能称“后台发现了新证据”。

计时建议沿用既有口径并增加体验指标，而非替换：

| 指标 | 起止 | 使用限制 |
| --- | --- | --- |
| provider/client 首字 | 开始模型调用到首个非空可见 content | 空 keepalive、CoT 不算；仍不保证内容有用 |
| provider/client 完整 | 开始模型调用到完整可用文本 | 继续用于用户提出的完整回复 1 秒目标；不能换成首字 |
| 服务首回调/完成 | `send_message` 前到首次回调/服务返回 | 包含服务额外开销，不能宣称真实 UI 绘制延迟 |
| UI 有效首回应/完整 | 用户确认发送到真实界面显示有效内容/完成 | 需要 UI 事件点及内容评价；“好的”、动画不算有效内容 |
| 准备耗时 | 导入分析、自定义题、后台任务各自的开始到结束/失败 | 独立披露，不隐藏在前台计时起点之前 |
| 语音首段 | 用户发言结束/本地端点确认分别到第一段实际可听音频 | 无真实 STT/TTS 和播放时应标未测，音轨首帧不能替代语音首段 |
| 取消与清空 | 发出取消到确认取消、最后旧文本/旧音频 | 区分传输收到、播放队列清空与模型请求停止 |

`ReplyTiming` 只有 `ttft_ms/total_ms/streamed`；kernel 在遍历 provider stream 前启动计时，包含调用封装工作，不是直接在网络层观测的服务器纯推理时长（`session_runner.py:178`）。新探针需保留现有字段解释，若增加网络/排队细分，应新增事件而不伪造拆分。P37 的 P50/P95 适合后续有足够样本时统计；第二候选差异为 3 轮，完整 731.4/1259.6/1060.7 ms，1/3 小于 1 秒；最新 E35 的独立单轮完整为 1,060.34 ms，仍未达标。不能估计可信 P95，也不能把不同候选/输入的数据混算优化提升率。

## 对 LiveKit 本机探针的最小接口建议

这是一组建议验收契约，尚未因本文而成为已交付能力。继续以 `LearningWorkbench.send_message(..., on_delta)` 为已确认文本的业务入口，RTC 集成层独立管理连续 PCM 和房间生命周期；背景准备仅归应用层调度。无需把 LiveKit 类型加入 domain 或让 RTC 修改 `DialoguePreparation`。

建议探针适配层给文本增量、完成、取消事件附加 `session_id`、`turn_id` 或 generation、递增序号；核心最小含义如下：

- 只有已确认输入进入 confirmed Message；将来的 STT partial 保持为 transcript 草稿。本阶段可用固定/人工确认文本驱动，不称 STT 已通过。
- 每个流的 delta 能归属唯一轮次。取消后旧 generation 的晚到文本不再显示，旧音频不再进入播放；completed 与 cancelled 互斥，断开的半段 assistant 不得保存为完成消息。
- cancel、leave、close 可重复调用；取消和离开会清理后台准备、生成任务及音轨/房间资源，结束复盘不由断线自动触发。
- 文本失败保留已确认历史，并允许重试。当前文本策略是整轮成功后保存用户和 assistant，失败不保存半轮；若语音要保留已说出的用户句，须单独明确“确认输入/生成完成”持久化边界，不能静默改变现有策略。
- 指标区分连接成功、音轨首帧、文本首 delta、文本完整、取消确认和资源归零；本机合成/测试 PCM 不能当成真实 STT/TTS 或可听回复质量证据。

对应离线/本机验收至少包含：连续音轨与文本并存；流中取消后故意晚到的 delta/frame 被丢弃；取消后新 turn 正常完成；模拟 provider 忽略取消也不污染新轮；断开/重复 close 后任务和音轨释放。现有 `_sending` 只防重复发送、`on_delta` 只传字符串，并不是完整的可打断 RTC turn 协议，因此探针应先验证适配层边界，不把文字回退计为三轮真人语音验收。

## 需要新决策或后续路线的内容

| DOCX 定位 | 尚缺的能力 | 为什么不直接纳入本次探针 |
| --- | --- | --- |
| P8–11、P30、P33 | 材料阅读/视频工作台、同步回听、划词/截图/音频制卡、继续已读位置 | 产品入口和媒体能力扩展；当前主线是利用已经接触过的材料练输出，不能增加“必须先在应用内读完”的门槛 |
| P13–16 | 小说章节/句子、Excel 单元格/单位/公式、视频说话人/置信度等统一来源模型；材料修订依赖映射 | 当前导入为线性文字；XLSX 以 `data_only=True` 读取缓存值与工作表名，不保留结构化公式/单元格锚点；视频只读旁挂字幕；需要模型与存储迁移决策 |
| P19、P21 | 分级提示、语言目标、严格剧透范围、用户/进度隔离 | domain 尚无这些边界；先定义最小场景和能力说明，不把其缺失误写成当前多用户产品漏洞已被复现 |
| P16、P27 | 原文件托管、材料编辑/删除、索引及派生物级联清理 | 涉及数据生命周期与恢复；当前 source_path 和保存文字不等于复制原文件，删除供应商数据也不受本地控制 |
| P22 | 外部事实检索和 Excel 精确计算 | 需要独立来源与确定性计算边界；不能让 LLM 凭有限答法包补全现实事实或公式 |
| P29–33、P36–38 | 支架自适应、迁移检验、长期学习效果研究 | 有价值的后续产品/研究方向；短文本/RTC 探针不能验证长期习得 |

P35–38 的对照实验方法可以低成本吸收：未来在同材料、同任务和同模型配置下比较“有界原文选择”“话题包”“话题包加预测”，明确首次/重复使用、跳题、无证据、改材料及冷热缓存。由于用户已经指定本轮实现双模型准备，不据此撤回现有方向；先用开关隔离预测增量，不新增并行架构，也不为该报告自动发起实验。

## 可执行的小改动与验收条件

以下是建议，不是另一份执行状态表。协调者可在现有工作包中吸收，避免另建 Roadmap。

| 建议 | 最小改动范围 | 完成时应出示的证据 |
| --- | --- | --- |
| 澄清候选命中语义 | benchmark/报告对已有字段补充定义；下一轮新增 available/included 独立统计 | mock 可用包进入 prompt 的布尔断言；未做意图标注时 intent_match 明确未测 |
| 坚持有限、按交流意图组织的分支 | 现有准备 prompt/质量夹具，沿用领域字段 | 同材料的赞同、反驳、改口、未知事实都接住真实输入；引文存在与语义支持分别报告 |
| 压缩保留关键证据 | 现有 packet 的去重或本地选择，不串行加推理 | 重复字节/实际 token 单独测；关键事实在长引文尾部、否定/数字/限定条件不丢失；不能仅凭字节缩短宣称实速提升 |
| 后台失败有明确终止原因 | 延用当前安全 diagnostics，固定尝试/时间/输出预算 | 记录 finish_reason、elapsed、usage 和安全 result；length 不相同参数无限重试；不保存原始 prompt/CoT/个人内容 |
| 为探针加轮次归属与取消隔离 | 独立 RTC/应用适配层，核心仍消费确认文本 | 同 turn 的 delta 有序；旧轮晚到不显示/不播放；失败不存半段完成回复；close 后资源归零 |

不建议为了“参考方案”立即新增向量库、图数据库、完整权限服务、阅读器或重新设计所有领域对象。更完整的 source/version/scope 模型应在相应产品任务进入范围时记录技术决策；本次先守住证据、前台路径和取消这三个已经影响交付的边界。

## 代码快照指纹

以下为本评审读取的关键文件 SHA256，定位工作树快照而非 release 标识；不同于早前独立验收的 19 文件聚合 hash，不能互相替代。

| 文件 | SHA256 |
| --- | --- |
| `application/material_preparation.py` | `318546968864bf4c7437cd9db04729390b201f48b4e0e8ea3cf4fd28e934ba33` |
| `application/learning_workbench.py` | `8844e1cf59b0069d6fde0e9143afe18c93795ce34e39f2f53af06ef72d9f5128` |
| `core/domain.py` | `d47a0ba2ae3e4e94fc9be6b9df3ed22702bb4ec370aaa825bb1661ab95aa28a8` |
| `core/material_context.py` | `20bdd0270542a2d63ccaa53f46c55a7c49d093b39c3bfb25d049a256decfed05` |
| `core/preparation_validation.py` | `92978022808653e78a4736c70093641fe673f8906a471e1f7157a7de5bb50cce` |
| `kernel/session_runner.py` | `5457aca88a15fde3c349db81bd99807a3be97855bb50acdad62753a487495350` |
| `providers/openai_compatible.py` | `757261785bc553bc78be34831aee2ed7927362eee5b1602454556baca617820d` |

上述路径均相对于 `src/lingualoop/`。参考文档的学习方法来源只作为设计背景；本次没有验证 Refold、contextual retrieval 或个人指南对 LinguaLoop 学习收益的有效性，不将它们写成产品实证。
