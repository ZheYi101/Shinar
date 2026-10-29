# 2026-10-24 独立后端代码与契约审查

审查员：`independent_audit`。候选工作树：`D:/code/project/LinguaLoop`，基线 HEAD `9f52590c7288f70fbd91dab0516d4205222f09d2`，包含本轮未提交修改；本报告不是该 HEAD 已提交内容的验证。审查只修改本报告，未改实现、其他测试或 `.env`，未提交、部署或执行真实模型 HTTP。

当前结论：A1、A2 以及修复复验发现的 A1-R 恢复消费入口均已修复并经独立离线复验关闭；在本报告的代码与来源结构契约范围内通过。下文保留首轮缺陷、首次修复及最终关闭的证据链。真实素材质量、真实 HTTP 与延迟由 `research_services` 唯一负责，本报告不替代其验收。

## 证据等级与候选身份

- A：独立执行的离线测试或合成 FakeClient 复现。
- B：工作树静态代码与数据流检查。
- 未覆盖：没有独立运行或没有足够证据，不记通过或缺陷。

关键文件 SHA-256（本次检查快照；负责人后续修复会改变哈希）：

| 文件 | SHA-256 |
| --- | --- |
| `src/lingualoop/core/domain.py` | `D1CCA6818927CD6BD77C77B3AC8FA30F1BDE5651DC9948D5DFDFD1571D4ABEA3` |
| `src/lingualoop/application/material_preparation.py` | `E31E02D15E83A2CDE7307C057109EE65E806C86E93D43D7B5E51436FF439483B` |
| `src/lingualoop/application/learning_workbench.py` | `673236D421E34129AA277FBABAD9E2EAD96A1DC3CEF99C53447AB395641E1666` |
| `src/lingualoop/providers/openai_compatible.py` | `DE8A9FA2D969F0335C794C48CB72C03A2250E180A5043C83C35E42D46C191C5A` |
| `src/lingualoop/kernel/session_runner.py` | `514E747C5CF9C448AD6D9FAE031693E0019348CA2E90BC4FE2CDA9F02F886DFB` |
| `tests/test_prepared_dialogue.py` | `0A059FE6165FBDBF3B60A0FA063409F5AECD802A1F91F4A81C9CCEFEC9D69EFC` |

## 已确认缺陷

### A1：没有任何来源的后台事实点仍保存为 ready（高，必修）

定位：`core/domain.py:249` 的 `DialoguePreparation` 默认允许空 `source_excerpts`；`providers/openai_compatible.py:296` 和 `application/learning_workbench.py:531` 只检查已有引用是否有效。对空列表的 `any(...)` 为假，因此“有事实点、无引用”通过两层校验。`kernel/session_runner.py` 将当前 revision 的 preparation 传入下一轮 Flash，上述无依据事实点因此能进入前台上下文。

独立复现（A，无外部调用）：FakeClient 的 `ainvoke` 返回 `AIMessage(content=json.dumps({"response_points": ["unsupported synthetic claim"]}))`，调用真实 `OpenAICompatibleLLMProvider.prepare_dialogue(...)` 得到非空 `response_points`、零条 `source_excerpts`，没有失败。另用继承 Mock 的 provider 返回相同 `DialoguePreparation`，通过真实 `LearningWorkbench.start_session()` 调度，等待后台结束后得到 `preparation_status == "ready"`，SQLite 中保存的 session.preparation 非空，引用数为零。

影响：后台格式不完整输出会被当作可用准备资料持久化和复用，违背“回答要点有来源”的本轮要求。应在 provider 与 application 的信任边界拒绝没有有效引用的事实点；失败只降级后台准备，不能阻塞对话。引用存在只能证明文字存在，仍不能自动证明语义推导正确。

### A2：自定义话题缺少所有回答分支仍成功，无结构重试（中，必修）

定位：`providers/openai_compatible.py:261–284`；`DiscussionTopic.answer_branches` 默认空列表。`prepare_custom_topic` 只验证开场及 topic 引用，过滤分支后没有检查是否至少有一个有效分支，直接返回。

独立复现（A，无外部调用）：FakeClient 返回合法 `title`、`opening_question` 和材料中的精确 `source_excerpt`，不提供 `answer_branches`。真实 `prepare_custom_topic(...)` 成功返回 `answer_branches == []`；FakeClient 调用次数为 1，未进入现有的第二次结构重试。原始输入为审查专用的合成日语短材料，不含用户材料。

影响：用户自提题会被标作已整理并进入会话，但本轮承诺的常见回应/要点/追问全部缺失；全部引用无效而被过滤的分支同样会形成空列表。应对缺失或过滤后为空的有效分支执行有界重试，仍失败时保留材料并明确提示准备失败或材料不足。

## 已独立运行的验证

命令（真实测试关闭）：

```powershell
$env:RUN_REAL_AI_TESTS='0'
uv run pytest tests/test_prepared_dialogue.py tests/test_prepared_dialogue_acceptance.py tests/test_discussion_workflow.py tests/providers tests/kernel tests/application tests/infrastructure tests/core -q
```

结果：**70 passed in 4.92s**（A）。这些测试与本次代码阅读共同支持：

- 长材料分块拼接保持全文；显式字符预算；失败已完成块可持久化和接续；未完成分析不能开聊。
- 新讨论前台使用流式回复；后台被阻塞时仍可回复；部分流失败不保存半消息；重复发送有保护。
- 旧 active session 经 Workbench 恢复后继续发送绕过逐轮 reasoning 纠错，历史消息保留。
- 晚到且忽略一次取消的后台预测因代际/revision 不匹配被丢弃；预测不会被写作真实消息。
- DeepSeek 双角色 thinking 参数分离；`reasoning_content` 附加字段不进入显示内容。代码没有把 settings、API key 或 response raw metadata写入业务 JSON 的路径（B）；该结论不覆盖第三方库的外部追踪配置。
- 普通 JSON 无效/引用无效最多调用两次（一次重试）；原文先保存，重试失败不丢已完成块。A1/A2 是这些现有测试没有覆盖的空结构情形。

## 限制及后续复验

- 未重复运行真实 HTTP、真实素材、性能、供应商成本、网络断开或远程取消，不对完整回复 ≤1s 作结论。
- 未运行桌面、麦克风、STT/TTS、LiveKit 或部署；UI 正由其他负责人收尾。
- 后台单并发锁、45 秒 `wait_for`、12 次内存计数及退出 `gather` 已静态检查；没有独立执行持久化预算跨重启、强制取消长期不返回的 provider、全部锁竞争或系统退出压力测试，故不把“每会话跨重启绝对上限”或“所有异常均及时退出”记为通过。
- 压缩上下文使用摘要、选定话题及引用，近期消息与 packet 有截断预算；没有独立验证所有长篇章节/所有话题的语义覆盖，也没有把“引用原文中存在”外推为解释事实正确。大纲的语义准确性和预制话题丰富性仍需真实素材验收。
- 本轮为尽快交还明确缺陷的修复槽位，未穷尽其他边界。修复 A1/A2 后应补充对应缺失字段/空列表/全部引用失效的回归测试，独立复跑并更新本报告候选哈希和结论。

## A1/A2 修复后第一次独立复验

本次仍为同一未提交工作树，未执行真实 HTTP。新增 `core/preparation_validation.py` 在 provider、材料准备与 Workbench 的新生成结果边界校验完整分支/意图/事实点/精确引用；Domain 继续使用宽松默认以读取历史。

修复候选 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `src/lingualoop/core/domain.py` | `D1CCA6818927CD6BD77C77B3AC8FA30F1BDE5651DC9948D5DFDFD1571D4ABEA3` |
| `src/lingualoop/core/preparation_validation.py` | `92978022808653E78A4736C70093641FE673F8906A471E1F7157A7DE5BB50CCE` |
| `src/lingualoop/application/material_preparation.py` | `F2AD000DE819C7023A65A31A63FD7E38D2DEF24FD54C4A285E9EEA51C74B262C` |
| `src/lingualoop/application/learning_workbench.py` | `BA36C47CC79F952BE470432F932CBC53775F9CAE55384C51657B4BBF59D0CC26` |
| `src/lingualoop/providers/openai_compatible.py` | `D869053505395236B03C4F6B68F020C9C7A8A34F22D3E8A355B4C4ADEB73F3E3` |
| `src/lingualoop/kernel/session_runner.py` | `514E747C5CF9C448AD6D9FAE031693E0019348CA2E90BC4FE2CDA9F02F886DFB` |
| `tests/providers/test_preparation_validation.py` | `3873E83A9FD9F130EB4969402C1E809764C704CDDF661EB1FD48EAB5B9CC043B` |

独立命令：

```powershell
$env:RUN_REAL_AI_TESTS='0'
uv run pytest tests/providers/test_preparation_validation.py tests/providers/test_openai_compatible.py tests/test_prepared_dialogue.py tests/test_prepared_dialogue_acceptance.py tests/test_discussion_workflow.py -q
```

结果：**52 passed in 4.04s**（A）。按本轮请求只运行受影响路径，没有重复全量或真实调用。

另外，独立重用首轮合成 FakeClient 复现，加入断言确认：

- A1 原始缺字段 payload 现在恰好调用两次后抛出 `ValueError`；A2 原始缺分支 payload 同样两次后抛错。
- Workbench 接收缺引用的 adapter preparation 后状态为 `unavailable`，内存与 SQLite 均无无效 preparation，没有 fake ready。
- 历史 `DialoguePreparation` 缺省列表及 `DiscussionTopic` 缺省分支仍可 `model_validate`；新增回归覆盖无效后台结果保留旧有效 snapshot，且不污染已确认消息。
- 新生成入口的 A1 和自定义话题的 A2 修复有效；本次新增发现下面的恢复消费入口，因此暂不把 A1 全部关闭。

### A1-R：修复前已落库的无引用 snapshot 在恢复后仍进入前台（高，A1 的恢复入口）

定位：当前 `kernel/session_runner.py:158–163` 复用 `session.preparation` 时仅比较 `based_on_message_count`；`Workbench._hydrate` 允许历史 payload 读取，但没有在消费时验证 snapshot。

独立复现（A，无 HTTP）：创建正常材料/会话后，以 `DialoguePreparation(based_on_message_count=len(session.messages), predicted_intents=["synthetic"], response_points=["old uncited claim"])` 写入测试专用 SQLite，再关闭并构造新的 Workbench。调用第一次 `send_message` 时，CaptureProvider 在真实 `generate_reply` 参数的 `current_instruction.metadata["preparation"]` 中观察到非空事实点、空来源，输出断言 `passed_to_reply == True`。

这正是首轮 A1 可以产生的历史数据形状；宽松读取本身应保留，但复用时应忽略无效历史准备。无需改写历史消息或拒绝整个旧会话。已向父 Agent 和 backend 报告，待消费入口修复后定向复验。

## A1-R 消费入口最终独立复验与关闭

`kernel/session_runner.py` 现在在注入当前 revision 的 snapshot 前调用 `validate_dialogue_preparation`，无效则从本轮 reply instruction 的 metadata 移除。没有让宽松历史模型读取失败，也没有修改原 snapshot 或原有消息。

最终检查快照 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `src/lingualoop/core/domain.py` | `D1CCA6818927CD6BD77C77B3AC8FA30F1BDE5651DC9948D5DFDFD1571D4ABEA3` |
| `src/lingualoop/core/preparation_validation.py` | `92978022808653E78A4736C70093641FE673F8906A471E1F7157A7DE5BB50CCE` |
| `src/lingualoop/application/material_preparation.py` | `F2AD000DE819C7023A65A31A63FD7E38D2DEF24FD54C4A285E9EEA51C74B262C` |
| `src/lingualoop/application/learning_workbench.py` | `BA36C47CC79F952BE470432F932CBC53775F9CAE55384C51657B4BBF59D0CC26` |
| `src/lingualoop/providers/openai_compatible.py` | `6ECFDD33B9F405775F0BC36EC536611F7C44A99DDE41CCA48CC373CE6994614C` |
| `src/lingualoop/kernel/session_runner.py` | `5457ACA88A15FDE3C349DB81BD99807A3BE97855BB50ACDAD62753A487495350` |
| `tests/providers/test_preparation_validation.py` | `672B40E5584B35B199518BA4677A607977DF8BF212B78E182724C3CDE8B05229` |
| `tests/test_prepared_dialogue.py` | `DA9A5721529D22D26D51270F15ED88EA1A5456A48117F557B4D8438A6175806A` |

独立定向命令：

```powershell
$env:RUN_REAL_AI_TESTS='0'
uv run pytest tests/providers/test_preparation_validation.py tests/kernel/test_session_runner.py tests/test_prepared_dialogue.py tests/test_prepared_dialogue_acceptance.py -q
```

结果：**40 passed in 2.73s**（A）。与前次 52 项存在重叠，不相加为独立用例数，也不代称本次全仓运行。

另独立重跑 A1-R 合成 SQLite 恢复复现，分别使用无引用/有合法引用两个旧 snapshot：

- 无引用旧 snapshot：恢复成功，`injected == False`，前台没有消费其事实点。
- 有效旧 snapshot：恢复成功，`injected == True`，没有误禁正常历史准备。
- 两种情况均逐项对比恢复前后的业务 payload，以及发送后的原有消息前缀与 preparation payload；`prior_messages_and_snapshot_unchanged == True`。正常的新发言仍追加保存。后台 provider 在本复现中被有意挂起，避免新的有效准备替换旧 snapshot 干扰比较；关闭可正常取消。

因此 A1 新生成入口、A2 自定义话题分支入口、A1-R 历史消费入口均关闭。现有历史默认列表仍可读取；无效新后台结果会降级为 unavailable，不伪装 ready；最多两次调用（一次重试）与部分无效分支剔除的回归通过。

本次候选还包含同一 backend owner 的性能调整：前台 context 去重、`evidence_ids` 对应引用、当前用户消息只发送一次；DeepSeek 后台预测单独使用 low effort/2500 token 输出限制。相关离线回归在上述命令中通过，不能据此推断真实延迟或语义质量。它们与来源验证修复分开记载；后续纯配置/deadline/README 改动若产生新哈希，不自动获得本报告对其性能的背书。所有首轮“未覆盖”限制继续适用。

## 新增本机 realtime 探针窄审查

本节是独立的新模块快照，不扩大前文文本后端结论。范围为 `src/lingualoop/realtime/*`、`tests/realtime/*`，并只读核对 `scripts/probe_livekit.py` 的异常清理交接。未修改实现、ROADMAP 或任何测试；未启动 RTC server、未下载 SDK/server、未执行真实 AI/语音调用。实现由 `livekit_probe` 独占。

最终窄审查快照 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `src/lingualoop/realtime/__init__.py` | `8B44FA3A73E2926DD307409FDA82006C460F229C5E0DD5719D6778ECBD231E65` |
| `src/lingualoop/realtime/protocol.py` | `DBD1AE6A61332A67503149D350D752E4B7AF40A909D4DBC9209BFCB7DE746F8B` |
| `src/lingualoop/realtime/livekit_transport.py` | `9367B95831B5782474CF82547B3B40BE7A1D9477DF28270DBFA381836048260D` |
| `src/lingualoop/realtime/local_server.py` | `7A2E49E8CC7DBB127F80B1D367E00F8A50C47FBB92B670153C3B5DAEF730C9E4` |
| `tests/realtime/test_protocol.py` | `5FB65D9BCBDA8BD11D4D541C21D93A4284C6064C1882697A2ABAF93F76F37354` |
| `tests/realtime/test_transport.py` | `DCE6E08194B0D971806F3480733A68A535C16F3DCB87EEA2AD6F46C1BCC3ED0B` |
| `scripts/probe_livekit.py` | `A78E9C331A5191474C07E53AFF707A138C34A88F22AABB77A84F275CD0612B37` |

### 两项生命周期缺陷的发现与关闭

初读候选独立执行 `uv run pytest tests/realtime -q` 得到 **15 passed in 0.07s**，但额外合成测试发现以下两项；已直接通知 owner 与父 Agent，由 owner 修复。

- **R1（中，已关闭）：单个 audio 资源关闭失败会跳过其余资源与 Room 断开。** 初读的 `close()` 直接等待 `_release_audio()`；FakeSource 的 `aclose()` 抛错后，独立观测 `room_disconnected == False`、`_connected == True`。owner 改为分别尝试 queue/unpublish/source 清理，汇总安全错误，并继续任务、stream 与 room 清理；脚本也用 `gather(return_exceptions=True)` 独立关闭两个参与者，避免一个失败跳过另一个。
- **R2（中，已关闭）：disconnect 期间的新 track 回调可重新创建消费者。** 初读的任务/stream 扫描发生在 `room.disconnect()` 前，回调没有 closing 门。FakeRoom 在 disconnect 内触发 `track_subscribed` 并让事件循环运行一次，独立观测 close 返回后仍有 1 个 task、1 个 stream。owner 增加同步 `_closing` 门、断开状态以及 `_on_data/_on_track/_spawn` 门控；拒绝的 coroutine 被关闭，显式 connect 可重新开启生命周期。

最终修复后独立命令：

```powershell
$env:RUN_REAL_AI_TESTS='0'
uv run pytest tests/realtime -q
```

结果：**17 passed in 0.05s**（A，仅离线 protocol/Fake SDK）。另重用以上原始失败样本确认：R1 仍报告安全的 `realtime_cleanup_failed`，但 Room 已 disconnect、connected 为 false、source 已清空；R2 返回时 task/stream 均为 0 且 Room 已断开。因此两项生命周期缺陷关闭，当前窄范围没有其他已实证的未关闭缺陷。

### 当前证据支持的范围

- 内容事件检查 session/turn/generation 与连续 seq；跨 session、非递增 generation、重复或乱序内容被拒绝。控制取消/ack 走单独语义，不能把内容流序号测试外推为所有控制包的严格序号证明。
- 草稿只在显式 `text_done` 后产生 completed_text，取消清空草稿/完成态；迟到文本与旧 SID 的 PCM 展示被门控。发送端取消在网络清理前设门，capture await 晚返回后再次检查并清空队列；这些为离线模拟证据。
- adapter 只持有展示草稿/PCM 和临时任务，不把半段或预测写入业务会话。是否持久化完整轮次仍由未来 application 集成负责，本次没有声称该业务链已接通。
- 独立屏蔽 `sys.modules['livekit']` 后，protocol 与 adapter 模块仍可 import；实例化 adapter 得到 `install_lingualoop_realtime_extra`。`pyproject.toml` 将 LiveKit 置于可选 extra，基础 CLI/desktop 无强制 SDK import 路径。
- 错误指标只计数，清理错误返回安全错误码；探针临时 secret 经 stdin 交给隐藏子进程，不进入命令参数和聚合结果。脚本父进程有截止时间与子进程退出/socket 检查路径；本审查仅静态核对，没有独立执行这些进程/端口清理。

### 不属于通过结论的内容

父 Agent 与 owner 当前报告：Windows server 严格 loopback 的 HTTP/UDP socket 检查通过，但 Python SDK 首个参与者 ICE 失败；owner 正进行一次有界官方 API 诊断。此状态不是本审查员独立重跑的证据，**不能将 server 启动或 17 项离线通过写成真实 RTC 文本/PCM 通路通过**。后续真实探针以研究员的独立结果为准，源码/脚本若再变动需关联新快照。

本节不证明真实麦克风/扬声器、STT/TTS、VAD/AEC、自然语音打断、真实网络恢复、完整业务语音对话或实际语音延迟；也未穷尽 SDK await 永久不返回、原生 SDK 取消、所有异常排列或并发 close/connect 压力情形。结论是**来源边界之外的新 transport 协议与已列生命周期路径的离线窄审查通过，不是完整语音验证**。

## 最后差异审查：合法本机 ICE URL 与安全诊断

**证据更正：**前节依据当时交接将空 URL 候选的 `ConnectError` 简写为“SDK ICE 失败”，不足以说明失败阶段。该候选 `[IceServer(urls=[])]` 有静态可证的配置缺陷；它既不能证明 loopback 环境不可用，也不能证明已经创建 native PeerConnection。旧原始异常未保留，不能补造为实际返回 `Empty uri`。本节用新的显式合法 URL 和诊断快照取代该配置，历史失败记录保留。

最终差异候选 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `src/lingualoop/realtime/protocol.py` | `DBD1AE6A61332A67503149D350D752E4B7AF40A909D4DBC9209BFCB7DE746F8B` |
| `src/lingualoop/realtime/livekit_transport.py` | `AFBC81ED4F4D7641D2FD59EF60A5DF470CB42BE236595645CCBB14943B9DB3DB` |
| `src/lingualoop/realtime/local_server.py` | `888FB5831CEB237E76775136006D99BC2A570121EDB3B524ED2E35430235D887` |
| `src/lingualoop/realtime/diagnostics.py` | `901937C37E9E8F9F9B58F9A29DD593317EE44B71D5E3A9BA0D4030D421CAA3D1` |
| `scripts/probe_livekit.py` | `B09067FD08C573A04ED986446CD280AC0E08413E281DB050FA4958C760FFAFA4` |
| `tests/realtime/test_protocol.py` | `5FB65D9BCBDA8BD11D4D541C21D93A4284C6064C1882697A2ABAF93F76F37354` |
| `tests/realtime/test_transport.py` | `C093486BD0FAA52DCFA9E24AC162E554FF8785079714AB4BC87AA55B5C907443` |
| `tests/realtime/test_diagnostics.py` | `AF4E92ADB976708609D0C519D321C064C632179525C409F6286D6CB080D14072` |

### 网络与原生源码边界

`validate_probe_stun_url` 只接受与当前已审计 UDP 端口完全匹配的 `stun:127.0.0.1:<port>` 字面串；拒绝 DNS、公网 IP、IPv6 替代形式、其他端口、userinfo、query、fragment、TURN 及不规范端口写法。脚本在父进程和 exercise 配置入口均检查；adapter 接收显式非空 URL，序列化为非空 IceServer 列表。本次差异没有新增 server 监听或 STUN 服务，也没有把该本机 UDP endpoint 称为已验证通用 STUN 服务。R1/R2 清理与 closing 门保留。

独立读取 owner 缓存的固定 Rust commit `5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb` 三份源码，并从官方 raw URL 重新读取逐字节比较，三者均一致（仅静态源码下载，没有 SDK/RTC 执行）：

| 官方文件 | 独立 SHA-256 |
| --- | --- |
| `livekit-ffi/src/conversion/room.rs` | `95793ec4f039138e7dad7b4bdeb823cfebd8bcc16aa6831cdeed483a45a5771f` |
| `webrtc-sys/src/peer_connection.cpp` | `f8c8125bffcb3265215e256d7fe0a00ceb12bde8d2e688f1b88fc6a16185a187` |
| `livekit/src/rtc_engine/rtc_session.rs` | `72b86ba1413d75538d1571715c91f58913e61cf5cc844060dba47e1c917e65aa` |

FFI 转换保留 URL 列表，C++ 转换没有移除空项；Rust 仅在 ICE server 列表为空时继承 SFU 表，显式合法非空 URL 可避免这条回退。[固定 FFI 源码](https://github.com/livekit/rust-sdks/blob/5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb/livekit-ffi/src/conversion/room.rs#L231)、[固定 C++ 源码](https://github.com/livekit/rust-sdks/blob/5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb/webrtc-sys/src/peer_connection.cpp#L35)、[固定 Rust 合并逻辑](https://github.com/livekit/rust-sdks/blob/5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb/livekit/src/rtc_engine/rtc_session.rs#L2773)。

官方 WebRTC 当前校验拒绝 URL/URI 同时为空的项；独立检查本机 SDK 版本为 1.1.21，其 DLL 的 SHA-256 为 `6795bb63c0a72566d68243d3bd0b40ee5c2a122bbaf8f6db9021a8bbd8bc4e43`，含相同校验字串。这里只支持配置缺陷的静态取证，不是重跑旧候选或完整二进制可重现构建证明。[WebRTC 校验源码](https://webrtc.googlesource.com/src/+/refs/heads/main/pc/ice_server_parsing.cc#343)。

固定 Rust 源码中 PeerTransport 创建路径在前，`wait_pc_connection` 的唯一超时字串在后；因此在该固定版本明确遇到这一字串时，可以标记“从源码位置推断已越过创建”，仍不是直接创建回调观测。普通 ConnectError、泛化 ICE timeout 或外层 deadline 均不能得到该推断。[固定创建与等待源码](https://github.com/livekit/rust-sdks/blob/5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb/livekit/src/rtc_engine/rtc_session.rs#L603)。

### 诊断证据收窄与定向复验

首次差异候选独立运行 `uv run pytest tests/realtime -q` 得到 **43 passed in 0.05s**。额外合成检查发现分类仍把泛化的 `ice connection timed out` / `ice connect timeout` 标为创建后推断，超过固定源码证明范围。已直接通知 owner 收窄为唯一明确的 `wait_pc_connection timed out`，并补回归；此项现已关闭。

最终只重跑受影响的诊断与 transport：

```powershell
$env:RUN_REAL_AI_TESTS='0'
uv run pytest tests/realtime/test_diagnostics.py tests/realtime/test_transport.py -q
```

结果：**33 passed in 0.05s**（A）。独立合成断言另确认：精确源码超时签名得到 `passed_inferred_from_ice_timeout`；两种泛化字串及 `TimeoutError` 外层 deadline 均得到 `not_observed`。phase/error 输出为固定枚举，最多检查四层异常链且原文只在内存分类；输出没有原始异常、token、URL query 或用户原文。每次连接有 elapsed_ms，但没有用耗时本身断言 native 创建。

**交接结论：可以运行已授权的唯一有界本机差异探针。** 已明确通知 `research_services` 与父 Agent；当前静态/离线窄范围没有未关闭必修问题。本审查员没有运行 RTC、AI、麦克风或新服务，也没有重复全仓测试。43/33 项离线结果均不能证明真实 RTC；真实连接、PCM/data、取消、重入和资源退出仍必须按研究员这一次差异探针的实际结果记录。

## 新 goal：连接超时根因调查与本机私有接口替代

用户随后要求必须继续解决本机 RTC，先通过连续音轨/打断再接 STT/TTS；本节不以旧离线通过或一次失败收口。`livekit_probe` 唯一修改实现并执行实际实验；本审查员只读调查、复核安全聚合证据及固定官方源码，没有启动另一个 RTC server/实验，也没有 LLM/STT/TTS 调用。父 Agent 已批准普通、可回滚的 OS 自有 RFC1918 单接口实验；不因早期自定的 strict127 范围再次要求用户确认。

### Python loop/FFI 与代理假设的排查

当前安装 SDK 1.1.21 的 `room.py:183` 在构造时记录 loop；`:556–570` 先订阅房间事件与 connect 回调，再发 FFI request 并按 async_id 等待。`_ffi_client.py:125–160` 用 `call_soon_threadsafe` 把 native 线程事件送到订阅 loop。脚本在 `asyncio.run` 的运行 loop 内构造 Room 并调用 connect，静态未见错误 loop 接线。

独立 AST 提取安装文件中的 `Queue`/`FfiQueue` 类（没有 import 或加载 native SDK），在真实 Windows `ProactorEventLoop` 按同样两订阅模式接收另一个线程发出的 connect async_id 事件：两个订阅均在 1 秒断言期限内收到，取消订阅后数量为 0。这仅排除该 Python 队列路径本身的可复现问题，不能代替完整 FFI/native 执行。

只检查进程环境变量是否存在：HTTP/HTTPS/ALL/NO_PROXY 的大小写形式均不存在；没有输出任何代理值、token 或 key。这不等同于穷尽 Windows 系统代理。后述真实 HTTP200/JoinResponse/answer 已进一步表明当前失败不是信令端点完全不可达。

| 被只读检查的本机文件 | SHA-256 |
| --- | --- |
| SDK `rtc/room.py` | `80CB072B6F7651A7A029697596DD4E3C0F86F61BA96CD7C42D1BEF1DEF9111D8` |
| SDK `rtc/_ffi_client.py` | `F70028CFC1BBBFFD4B7477C0B7BB7641DFD00A8758821DDB49FDEFED2F8F4858` |
| SDK `rtc/_utils.py` | `87F650A968B60451EECA1C54D0B4C2C5871C033ABF29E1C87C895C4DC622AEED` |
| owner 聚合 `build/livekit-probe/diagnostic-20261024-01.json`（ignored） | `4D9A15115F5CB8666542EAEDFAFE2CF5C80C48CD0E74E94A428647DDD3AFA8FD` |

### 已确认的超时观测缺口

安装 `room.py:129–130` 的 connect_timeout 是每次 signaling attempt 的期限。固定 Rust `livekit/src/room/mod.rs:473` 默认 `join_retries=3`，`rtc_engine/mod.rs:548` 包含初次在内最多四次尝试，每次在 session 后等待 native ICE；`rtc_session.rs:74` 为 15 秒 ICE 期限。因此当前外层 45 秒可以早于四轮约 60 秒的 native 失败回调，把结果截为 operation_deadline。**不能从外层超时反推 FFI 队列失败、native 没有创建或没有明确 ICE 错误。** 已将精确位置及“捕捉每 15 秒的安全 retry/阶段计数”最小诊断交给 owner。[固定 Room 默认](https://github.com/livekit/rust-sdks/blob/5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb/livekit/src/room/mod.rs#L473)、[固定重试循环](https://github.com/livekit/rust-sdks/blob/5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb/livekit/src/rtc_engine/mod.rs#L548)。

### 候选不匹配：实际诊断与固定 native 过滤链

owner 执行首个带安全 native trace 的真实诊断；本审查员独立读取上述聚合 JSON，确认：HTTP 200；Room loop 均为当前 loop；441 次心跳、最大间隔 115.667ms；约 0.541s JoinResponse、0.544s publisher answer、0.571s Connecting；15.543s 和 30.561s 明确 native wait timeout/retry。local candidate 出现 18 次，均为 private host（UDP/TCP 各 9），没有 local loopback；remote 3 次仅为 UDP host loopback。这里是候选日志出现次数，不宣称 18 个独立地址。自有进程退出及 socket 清理为 true；本审查员没有复跑。

固定源码提供了与该实测一致的过滤机制：Rust `webrtc-sys/build/src/lib.rs:31` 指定 `webrtc-89d790b`；该 WebRTC 的 `rtc_base/network.h:57` 默认 ignore mask 包含 LOOPBACK，Factory.Options 使用此默认，factory 将 mask 传给 allocator，allocator 按 adapter type 过滤。Rust wrapper 的 factory 没有覆盖该选项；安装 Python `RtcConfiguration` 只暴露 transport/gather/ICE servers，没有 network-ignore-mask 开关。**这是可解释当前 strict127 候选不匹配的证据链，不是“所有本机网络均不受支持”的结论。** [固定构建标记](https://github.com/livekit/rust-sdks/blob/5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb/webrtc-sys/build/src/lib.rs#L31)、[WebRTC 默认 mask](https://github.com/webrtc-sdk/webrtc/blob/89d790b/rtc_base/network.h#L57)、[传给 allocator](https://github.com/webrtc-sdk/webrtc/blob/89d790b/pc/peer_connection_factory.cc#L328)、[实际过滤](https://github.com/webrtc-sdk/webrtc/blob/89d790b/p2p/client/basic_port_allocator.cc#L713)。这些固定文件均由审查员从其项目的官方原始源码独立读取。

### 最小可行替代及待验边界

结合候选证据，使用 OS 证明本机拥有、SDK 确实收集到的现有 RFC1918 地址，是无需修改 native SDK 的合理最小替代。优先现有 vEthernet/host-only 接口；HTTP 保持 `127.0.0.1`，RTC UDP 只绑定所选精确 IPv4 `/32`，RTC TCP 为 0，STUN 仅指向该地址/已审计 UDP 端口，不新增网卡、系统路由、防火墙规则、公网服务或监听。已直接提醒 owner：`ipaddress.is_private` 不等于 RFC1918，必须精确检查 10/8、172.16/12、192.168/16，再核本机归属/接口状态；不得只凭 private 日志标签选择地址。

该范围应标为 `local-private-interface`，不能继续称 strictloopback；同虚拟网段的 VM 可能触达该监听，因此与仅本机 127 不等价。现有短命随机 room/token 和精确 socket 白名单继续适用。当前仅支持实施这一受控差异实验；是否解决 RTC/PCM/data/取消必须由 owner 实验结果证明，随后独立审查其冻结差异。本节不把候选假设当作已经修复或完整语音通过。
