# 双模型文本独立验收（2026-10-24）

本文保留当时候选的验收结果，原执行地图见[历史快照](../../archive/2026-10/ROADMAP_SNAPSHOT_2026-10-28.md)；当前计划见[路线图](../../planning/ROADMAP.md)。本报告由 `research_services` 独立执行，不修改被测后端/UI；供应商能力研究见 [服务选型](../../research/SERVICE_SELECTION_2026-10-24.md)。

## 范围与证据边界

- 离线：后台推理失效与中断后的重试、前台模型路由、旧反馈偏好、复盘与 SQLite 重启恢复；全仓单元/服务/Qt Test 回归。
- 真实 HTTP：一份公开日文短篇分析、四轮预制题、一个自定义题及两轮讨论、两次结束复盘、临时 SQLite 恢复；后续仅同源最小夹具的有界差异与背景修正验证。累计前台 10 轮。仅此负责人运行真实探针，不并行重复调用。
- 性能：分别记录 provider 首个可见 content、完整回复、应用服务回调与完成；本脚本不构成实际 UI 渲染或语音延迟测量。
- `prepared_hit` 指发送前确有有效准备包，其 `based_on_message_count` 与当前消息数严格相同，且非空来源引用仍存在于当前材料。该历史字段实际表示 `preparation_available`，并不判定真实用户意图与预测匹配；后续消费验证表示 `preparation_included`，仅记录候选意图是否进入实际 Flash prompt 的布尔值。`intent_match` 与 `preparation_benefit` 均未测，指标区分见 [参考方案评审](../../research/REFERENCE_PLAN_REVIEW_2026-10-24.md#前后台任务与预测消费)。
- 文本基准不调用 LiveKit；本机 RTC 探针另节记录，不运行 STT/TTS 或设备录放。文本、离线协议和本机探针结果不能互相外推为真实语音通过。

## 可复现入口

默认脚本不读 `.env`、不联网、不调用模型：

```powershell
uv run python scripts/benchmark_prepared_dialogue.py
```

真实调用须同时显式参数和开关，使用当前本地 `.env`：

```powershell
$env:RUN_REAL_AI_TESTS = '1'
uv run python scripts/benchmark_prepared_dialogue.py --real
```

真实输出默认仅包含汇总元数据，落在忽略目录 `build/text-acceptance/results.json`；原文、对话、密钥、CoT 不写日志。原文和业务数据库只存在临时目录，退出清理。取消中的请求可能已计费，无法获取的 token 用量明确未知；汇总不是账单。SDK 自动重试在探针中关闭，避免隐藏请求和掩盖失败。

来源为芥川龍之介《蜘蛛の糸》青空文库 No.92：[图书卡](https://www.aozora.gr.jp/cards/000879/card92.html)、[正文](https://www.aozora.gr.jp/cards/000879/files/92_14545.html)、[公版文件处理规范](https://www.aozora.gr.jp/guide/kijyunn.html)。仅提取 XHTML 正文、移除 ruby 读音，保持原字形；作者、底本、录入/校对及版本日期在脚本/本报告保留。底本《芥川龍之介全集2》ちくま文庫，筑摩書房；录入平山誠、野口英司，校对もりみつじゅんじ；青空发布 1997-11-10，修订 2011-01-28。

## 验收记录

| 项目 | 等级 | 命令/定位 | 结果与限制 |
| --- | --- | --- | --- |
| 独立失效恢复与路由 | 单元/应用服务 | `RUN_REAL_AI_TESTS=0 pytest -q tests/test_prepared_dialogue_acceptance.py` | 首轮 2 passed；最终扩展为 **5 passed，2.68 秒**，含默认不联网、失效/重试/旧偏好、长篇/尾章细节与真实调用上限守卫；不以 mock 证明 HTTP 可用 |
| 全仓离线首次回归 | 单元/应用服务/Mock Qt | `RUN_REAL_AI_TESTS=0 pytest -q --ignore=tests/engine/test_real_provider.py` | 86 passed / 1 failed，20.03 秒；失败为新 QTest 键盘大小写断言，UI 负责人确认运行期间正在修正 harness；未据此推定产品输入失效 |
| UI 负责人局部修复 | 实现者自验 | `test_text_streaming_categories_custom_topic_and_shortcut` | 负责人报告 1 passed，修正大小写期望及 offscreen Shortcut 上下文；待独立全仓复验 |
| 全仓离线第二次回归 | 独立单元/服务/Mock Qt | `RUN_REAL_AI_TESTS=0 pytest -q --ignore=tests/engine/test_real_provider.py` | 107 passed，23.47 秒；严格空引用/无分支修复候选及 UI 核心路径通过。后续性能/长篇修订还需另验 |
| 长篇均衡夹具 | 独立应用服务 | `tests/test_prepared_dialogue_acceptance.py::test_long_material_topic_budget_retains_every_chapter_including_last` | 9 章/108,000 字符/72 个原候选题，60 题预算下每章包含末章均保留；无 HTTP，不代表整本真实质量 |
| 尾章细节自提题首验 | 独立 provider prompt 捕获 | `test_custom_topic_can_reach_detail_in_last_raw_chunk_beyond_summary` | 初验失败：目标细节位于末 chunk 内偏移约 6,000 字符、摘要/预制题未记录，lexical 选中 chunk 后没有把实际匹配处原文送给模型；已交后端修复，未放宽断言 |
| 冻结后全仓离线复验 | 独立单元/服务/Mock Qt | `RUN_REAL_AI_TESTS=0 pytest -q --ignore=tests/engine/test_real_provider.py` | **115 passed，23.42 秒**；包括尾章匹配窗口修复、均衡、严格引用、旧候选消费和 UI 核心交互。不包含真实 HTTP 或实际语音 |
| 最终背景候选全仓首验 | 独立单元/服务/Mock Qt | `RUN_REAL_AI_TESTS=0 pytest -q` | 118 passed / 1 failed / 1 skipped，23.56 秒；失败为分类点击后未筛选。UI 负责人后续 viewport 诊断证明点击中心在材料可视区外，修复测试滚动/定位且保留业务断言；未将其直接认定为分类产品失效 |
| UI 最后诊断与修复 | 实现者自验 | `tests/desktop/test_desktop_workflow.py` | 负责人报告 9 passed，16.83 秒；除修复分类点击 harness，还发现真实 composer 在后台状态出现时按钮上移 37px，固定状态区并加入前后坐标不变断言。两者分开归因；等待最终独立全仓复验 |
| 首次 RTC 配置候选全仓复验（历史） | 独立单元/服务/Mock Qt/RTC 协议 | `RUN_REAL_AI_TESTS=0 pytest -q` | 138 passed / 1 skipped，29.31 秒；包含最后 UI 点击/布局修复与 17 项 RTC 离线协议/生命周期测试。该轮不曾覆盖 native ICE URL 合法性，不能把离线全绿当真实 RTC 通过 |
| 合法配置最终全仓复验 | 独立单元/服务/Mock Qt/RTC 协议与诊断 | `RUN_REAL_AI_TESTS=0 pytest -q` | **166 passed / 1 skipped，25.81 秒**；包含 45 项 RTC 配置/协议/生命周期/诊断回归，generic timeout 和外层 deadline 不再误推断 native 创建。被跳过项为显式关闭的真实 AI 测试；RTC 实测失败仍单列 |
| 第二候选分发包（历史） | 构建/隔离加载 | `uv build --wheel --out-dir build/package-check`；`python scripts/check_wheel_resources.py build/package-check/lingualoop-0.1.0-py3-none-any.whl` | 39 QML/SVG/许可证资源齐全；隔离解包加载 WindowController、隐藏 frameless QML、窗口三按钮/拖动区/缩放句柄通过；当时 19 个后端源模块与工作树逐字节一致 |
| 首次 RTC 配置候选包（历史） | 构建/隔离/字节比较 | 同上构建及隔离资源命令 | 19 后端模块 + 4 realtime 模块 + 39 QML/SVG/许可证资源与当时工作树相同；隔离 QML/无 extra 业务 Mock 通过。后续确证空 ICE URL 配置无效，包完整性不等于 RTC 可用 |
| 合法配置最终分发包 | 构建/隔离/字节比较 | 同上构建及隔离资源命令，另读取 wheel metadata 并逐字节比较源文件 | **19 后端模块 + 5 realtime 模块 + 39 QML/SVG/许可证资源与冻结工作树相同**；隔离 QML 控件通过。两 SDK 只在 `realtime` extra；阻断 `livekit` 导入后隔离包业务 Mock 仍完成导入/开始/发送，构造 RTC 给 `install_lingualoop_realtime_extra` |
| 有界真实 HTTP：修复前候选 | 真实 DeepSeek HTTP | `python scripts/benchmark_prepared_dialogue.py --real` | 结构/路由检查通过，完整回复 1 秒门失败；后台准备超时，不能证明预测实际有效。具体数据见下文；不是修复后最终全链路证据 |

独立测试首次失败还包括一项验收夹具边界错误：mock 的结束复盘内部会计算纠错，被“禁止前台逐轮纠错”的 stub 一并拦截。已将结束复盘单独标记后重跑，2 passed；这是 harness 修复，不是修改或放宽产品前台路由要求。

最终分发文件：`D:/code/project/LinguaLoop/build/package-check/lingualoop-0.1.0-py3-none-any.whl`；SHA256 **`5ae286b5304e3562d3c920fa47abb2f594069dec78a6710c44af1dcbb4b40916`**。19 后端模块聚合指纹为 `dbbd27eb…6610a`（完整值见末轮模型探针）；新增 `diagnostics.py` 后 realtime 共 5 模块。wheel metadata 中只有 `livekit==1.1.21; extra == "realtime"` 与 `livekit-api==1.2.2; extra == "realtime"` 两项 RTC 直接依赖，没有强制所有基础安装引入 RTC。

此前第二候选包 `021733ce…c135` 和 UI 负责人早期包 `d05017…` 均为已被替代的历史包；前者早于最终背景/UI/RTC 修正，不能作为最终包证据。这里的 wheel 是 Python 安装包，不是包含 Python/Qt/native 运行时的 Windows 安装器。

## 真实 HTTP 第一轮

运行时间为 2026-10-24 03:38:07–03:45:25 UTC。素材正文 2,928 字符，UTF-8 SHA256 `e7fc3e099f46730b9ba671aa626544b662bfe0293f83b72c4815e0036b1ab9e5`。脚本退出码 1 是性能目标未达标，不是 HTTP 或结构化解析失败。

请求配置为 `api.deepseek.com`、`deepseek-v4-pro`（思考 enabled）、`deepseek-flash`（思考 disabled）。API 返回的模型元数据也是这两个服务 ID，没有提供本次可核实的具体权重 revision；不能用官方当前价格表所列版本冒充实际返回的 revision。未保存 request ID、CoT 或原始回答。

候选身份限制：进程在前一轮后端源码迭代时启动；03:43 读取到的修复前 provider SHA 为 `de8a9fa2d969f0335c794c48cb72c03a2250e180a5043c83c35e42d46c191c5a`，workbench 为 `673236d421e34129aa277fbabad9e2ead96a1dc3cef99c53447ab395641e1666`。provider 在进程启动附近（03:38:05）有修改，首版脚本又未在 import 前固定快照，因此不能严格保证这两个文件哈希就是已加载代码。此轮只作修复前历史运行事实；后续差异探针在调用前后记录完整关键文件哈希。

### 功能与内容证据

- 分析约 170.4 秒，生成 10 个话题、20 个分支、9 条大纲、4 个人物；每个话题都有分支，话题/分支/人物的引用逐一检查为原文子串，分片覆盖全文。
- 预制开场从已保存材料开始，约 8.56 毫秒；这不是一次新模型生成。
- 四轮预制题分别覆盖人物偏好、改口、材料外虚构餐馆问题、索取系统指令/Key 的越界请求；两轮自定义题覆盖非预测意见和理由。6 轮全部通过实际路由计数（前台只有 dialogue）、流式文本与最终保存内容一致、非空日语的检查。材料外问题命中不确定性措辞、越界标记和配置 Key 未出现在回答中。
- 自定义题推理准备约 69.4 秒，返回 5 个分支、有效原文引用。两次结束复盘的 Pro 耗时约 103.4 / 41.5 秒，首场保存 1 个反馈和 1 个复习项，重启恢复最后会话与自定义题成功。
- 初次后台 Pro 准备在 45 秒被取消，状态 `unavailable`。所有 6 轮 `prepared_hit=false`；后续脚本连续发送，没有模拟真人思考间隔，不能据此统计真人会话的背景命中率。这证明未命中时前台仍能回复，但**不能证明真实预测整理能够及时就绪、命中或带来提速**。
- 退出后后台任务数量 0，临时业务数据库清理。

这些检查证明结构、引用存在性、路由和少量定向边界；没有独立日语母语人工评审，也没有逐条证明每个回答要点在语义上被引用蕴含。不得把它们包装成全面准确率或学习效果认证。

### 延迟结果

| 场景 | 模型首字 ms | 模型完整 ms | 服务完整 ms | 回答字符数 | 后台命中 |
| --- | ---: | ---: | ---: | ---: | --- |
| 人物偏好 | 774.1 | 1174.3 | 1180.3 | 51 | 否 |
| 改口 | 1210.9 | 1531.7 | 1541.8 | 42 | 否 |
| 材料外事实 | 1176.5 | 1564.9 | 1572.4 | 51 | 否 |
| 越界请求 | 1249.4 | 1668.3 | 1674.8 | 54 | 否 |
| 自定义题意见 | 493.6 | 904.7 | 915.0 | 56 | 否 |
| 自定义题理由 | 930.9 | 1263.9 | 1276.1 | 60 | 否 |

N=6，模型首字范围 493.6–1249.4 毫秒，中位 1053.7；模型完整 904.7–1668.3 毫秒，中位 1397.8；服务完整中位 1408.9 毫秒。仅 1/6 完整回复小于 1 秒，**性能目标失败**。不是足够估计 p95 的样本，未伪造 p95，也未实际测 UI 渲染首字。

Flash 输入 token 分别为 1145/1265/1380/1401/2024/2131，输出为 39/29/33/40/38/42；已有很短回复。3 轮首字本身就超过 1 秒，单纯缩短输出不能保证达标。缓存读取分别为 0/1024/1152/768/0/1920 token，也没有证明缓存与低延迟存在单调关系。下一步宜拆分连接/服务首字成本、进一步压缩上下文，背景准备要先证明可在预算内完成；不能通过瞬时占位回复或静态缓存冒充对话模型完整生成。

### 调用与消耗

观测到 11 次模型调用启动：6 次 Flash 完成、4 次 Pro 完成（分析、自定义、两次复盘）、1 次 Pro 取消。可观测 token 为输入 17,815、输出 40,582、合计 58,397，缓存读取 4,864；取消请求用量未知。这是局部 usage，不是完整账单。Pro 输出包含供应商计入 usage 的思考 token，但没有保存其内容。

## 修复后差异复验与最终门槛

第一轮后独立审查发现空来源后台结果仍可 ready、自定义题没有有效分支仍可成功、历史无效候选可能继续被消费。后端已收紧验证器。长篇话题偏重前章的风险也已要求修正为均衡预算及自定义题相关源文选择，独立回归曾发现窗口未覆盖真正匹配处的失败（见上表）。

协调者批准最多一轮有界优化：去重快速模型上下文；后台思考仍开启但采用官方支持的 low 强度与更小输出预算；分析保留 high。真实差异复验使用同源公版最小准备夹具，运行 **1 次自定义准备 + 有界等待一次后台准备 + 最多 3 轮 Flash**，累计前台最多 9 轮，避免重复昂贵的整篇分析。准备等待单独计时，不能藏入前台 1 秒计时之前。差异入口：

```powershell
$env:RUN_REAL_AI_TESTS = '1'
uv run python scripts/benchmark_prepared_dialogue.py --real --revision-only --output build/text-acceptance/revision.json
```

这份后续证据覆盖验证器、短 prompt 和后台预算路径，不能冒充修复后重新跑完最初整篇分析/两次复盘。

### 第二候选差异结果（背景修正前）

运行时间：2026-10-24 03:56:53–03:59:23 UTC。源文哈希与首轮完全相同。19 个后端模块按仓库相对 POSIX 路径排序，对“路径 UTF-8 + NUL + 文件字节 + NUL”计算 SHA256，运行前后均为：

`2cb469854183193c5a84c971ddcce15a1bf834856e08cb79fb1b3edf0208db59`

候选在整次运行内未变化。完整逐文件哈希保存在忽略目录中的脱敏汇总 `build/text-acceptance/revision.json`；当时构建的 wheel 内这 19 个文件与该候选工作树逐字节相同，后续背景修正后的最终包另列。

- 自定义题实际 Pro 配置为 high、24,000 token 上限；约 103.7 秒完成，生成 4 个完整有效分支，引用检查通过。此次使用原文片段手工构造的最小已准备夹具，没有重复整篇模型分析。
- 后台请求明确观测到 `reasoning_effort=low`、`max_tokens=2500` 的逐调用覆盖，思考仍开启。两次请求分别约 22.9 / 20.2 秒，都报告输出恰好 2,500 token；最终状态 `unavailable`，没有非空有效来源可消费，第一轮背景等待约 43.2 秒。可能是输出预算耗尽造成结构化结果不完整，但该次脚本未记录 `finish_reason`，只能作为推断，不能断言根因。后续脚本已补充该非敏感字段的采集，未为此再次调用。
- 3 轮实际回复均只走 Flash，输出上限保持 160 token；流式内容与保存内容一致，非空日语和材料外问题的不确定性措辞检查通过。background hit 均为否；退出任务数量 0，临时目录已清理。

| 第二候选场景 | 模型首字 ms | 模型完整 ms | 服务完整 ms | 输入/输出 token | 回答字符数 |
| --- | ---: | ---: | ---: | --- | ---: |
| 对丝线与自私的看法 | 424.2 | 731.4 | 739.1 | 1624 / 44 | 63 |
| 改变解释 | 1007.1 | 1259.6 | 1271.5 | 1694 / 29 | 44 |
| 材料未提供的改编情节 | 686.2 | 1060.7 | 1067.4 | 1751 / 36 | 55 |

第二候选 N=3，模型完整范围 731.4–1259.6 毫秒，中位 1060.7；仅 1/3 小于 1 秒，性能目标仍失败。此处不混合首轮旧候选计算“优化提升率”，样本和输入不同，也不能估计 p95。结构/路由等文本局部检查通过；后台真正生成可用准备包并被下一轮消费的真实门未通过。`text_functional_pass=true`，`background_ready_pass=false`，因此联合 `functional_pass=false`，脚本 exit 1 与报告一致。

差异轮新增观测输入 11,649、输出 17,124，合计 28,773 token；两轮合计观测 87,170 token、17 次调用启动（9 Flash 完成、7 Pro 完成、1 Pro 取消）。取消请求仍可能计费，不能将观测合计当账单。实际前台累计 **9 轮**，未无限重试或另起长篇调用。

### 最终背景修正：一次准备与一次真实消费

运行时间：2026-10-24 04:07:19–04:07:31 UTC。使用同源最小准备夹具，不再次调用整篇分析、自定义题或模型复盘。19 个后端模块聚合 SHA256 在调用前后均为：

`dbbd27eb66d3097ba8eb67cf8f8839d40b3df7e53362e684f8b0f635f6d6610a`

本轮将背景输入限为当前题、少量候选意图/已备要点、一条原文引用和最近两条消息，采用紧凑结构输出。生产实现仍为 Pro 思考开启，显式 low/4,000 token；探针设置 `background_max_attempts=1`，审计 wrapper 在第二次调用进入实际传输之前阻断。只有准备有效就绪才允许一个 Flash；发送后不再调度新 Pro。命令为：

```powershell
$env:RUN_REAL_AI_TESTS = '1'
uv run python scripts/benchmark_prepared_dialogue.py --real --background-only --output build/text-acceptance/background.json
```

| 检查 | 实测结果 |
| --- | --- |
| Pro 后台 | 1 次完成，10,690.96 ms；`finish_reason=stop`；输入 403、输出 939 token；无同预算重试 |
| 背景状态 | `ready`；等待 10,752.31 ms；非空来源引用精确匹配原文，修订与当前消息数相同 |
| Flash 消费 | 实际发送给 Flash 的结构化上下文包含刚生成的候选意图；`prepared_hit=true`、`preparation_consumed_in_dialogue=true` |
| Flash 延迟 | 首字 645.12 ms；模型完整 1,060.34 ms；服务完整 1,066.70 ms；输入 808、输出 40 token；59 字符 |
| 调用与清理 | 实际前台仅 Flash；两次响应模型元数据仍是 `deepseek-v4-pro` / `deepseek-flash`；关闭后后台任务 0 |

这一轮 `functional_pass=true`，首次证明真实 Pro 可生成有效准备包且被后续真实 Flash 消费。背景约 10.7 秒，不能承诺每个快速连续轮次都及时就绪；只验证一次有效包的可用与纳入，未判定真实下一句意图匹配，也未作有/无预测的同条件对照，不构成自然会话命中率、预判准确率或提速因果证据。完整回复仍略超过 1 秒，`complete_under_1s_pass=false`；脚本因此 exit 1，不能将其误报成 HTTP/结构失败，也不能用首字 645 ms 替换完整回复结果。单样本不能估计 p95 或稳定性。

本轮新增输入 1,211、输出 979，合计 2,190 token。所有真实轮次合计观测 **89,360 token、19 次调用启动**（10 Flash 完成、8 Pro 完成、1 Pro 取消）；被取消的请求用量未知。前台 **10 轮封顶**，未追加真实生成。以上仅观测 usage，非供应商账单。

## 本机 LiveKit 独立探针

### 首次候选：空 ICE URL 配置缺陷

在代码/脚本和 UI 均冻结、R1/R2 清理缺陷完成离线独立审查后，只运行一次，不读取 AI 凭据，不请求 LLM/STT/TTS、不采集麦克风或播放设备：

```powershell
$env:RUN_REAL_AI_TESTS = '0'
.venv\Scripts\python.exe scripts/probe_livekit.py --output build/livekit-probe/independent-results.json
```

2026-10-24 04:23:38 UTC 开始；Windows / CPython 3.13.5，RTC SDK 1.1.21、API SDK 1.2.2，官方 server 1.13.10。固定资产 SHA256 为 `fd4b7c2c3c1e4c71adaa4f6a046ad1c0abaaaf1e09fae904b35bf231ffae11d2`，已缓存，未再次下载。具体配置与官方依据见 [LiveKit 文档](../../desktop/LIVEKIT.md)。该候选使用非空 `[IceServer(urls=[])]` 覆盖继承的 server ICE 列表。**后续静态追查已确证这是配置缺陷**：SDK 固定源码转换不丢弃该空项，WebRTC `ParseIceServersOrError` 对空 urls/uri 返回 `SYNTAX_ERROR / Empty uri`，安装的 native DLL 也有相应字符串。此轮失败不能作为 ICE 环境问题的证据。历史 `ice_servers=[]` 不能证明没有外部 STUN，未假称存在抓包证据。

| 项目 | 独立实测 |
| --- | --- |
| server 监听 | PID 69988，仅 TCP `127.0.0.1:17880`、UDP `127.0.0.1:17882`；RTC TCP fallback 关闭 |
| 参与者连接 | **失败，`ConnectError`，脚本 exit 1**；首个 client 未完成 `connect`，没有 connected/首 delta/首 PCM 指标，根因未确定 |
| 下游真实断言 | 双参与者、连续 PCM、可靠 data、真实取消后旧帧阻断和 leave/rejoin **均未到达**；不能用 17 项离线测试替代 |
| 隔离和清理 | RTC 子 PID 27392 exit 1、已退出，探针记录子进程 socket/server 清理为真；Python tasks/streams 清理为真、错误数 0 |
| 独立 OS 复查 | `Get-Process` 确认上述两 PID 都不存在；`Get-NetTCPConnection` 查 17880 为 0、`Get-NetUDPEndpoint` 查 17882 为 0。native 释放以子进程退出和 socket 检查为证，不从 Python task 数推导 |

调用前后四个源码/脚本 SHA256 均相同：

| 文件 | SHA256 |
| --- | --- |
| `realtime/livekit_transport.py` | `9367b95831b5782474cf82547b3b40be7a1d9477df28270dbfa381836048260d` |
| `realtime/protocol.py` | `dbd1ae6a61332a67503149d350d752e4b7af40a909d4dbc9209bfcb7de746f8b` |
| `realtime/local_server.py` | `7a2e49e8cc7dbb127f80b1d367e00f8a50c47fbb92b670153c3b5daef730c9e4` |
| `scripts/probe_livekit.py` | `a78e9c331a5191474c07e53aff707a138c34a88f22aabb77a84f275cd0612b37` |

这次只确认 loopback server 启动、范围检查和最终退出回收；**真实 RTC 链路未通过**。最终只采集安全异常类型，未保存原始异常，不能证明与早期 ICE 超时有相同根因；后续确证的空 ICE URL 配置缺陷必须先修正，不能把自造无效配置解释为环境限制。协调者仅批准合法 literal loopback STUN URL 的最小更正、安全错误分类，以及冻结后一次有界差异探针；不改为 LAN/公网绑定或系统网络，不调用任何模型。

### 合法 loopback URL 差异探针

空 URL 配置已改为 canonical `stun:127.0.0.1:17882`，只指向已审计 server 的现有 UDP endpoint，不新增服务、监听、DNS 或公网 STUN/TURN。adapter 要求显式 ICE URL；probe 校验 URL 必须和该 literal loopback 端口完全一致。新增 allowlist 诊断只保存 phase/error 枚举和 elapsed；仅固定源码位置的 `wait_pc_connection timed out` 可标 native 创建后的**推断**，泛化超时及外层 deadline 均为 `not_observed`。独立审查通过后执行唯一一次：

```powershell
$env:RUN_REAL_AI_TESTS = '0'
.venv\Scripts\python.exe scripts/probe_livekit.py --output build/livekit-probe/independent-revision-results.json
```

开始时间 2026-10-24 04:38:55 UTC，版本/固定资产同前，无新下载，无模型或语音 API 调用。结果 **exit 1 / `TimeoutError`**，`error_phase=client_connect`、`error_code=operation_deadline`。首 client 的 `connect` 在 **44,899.859 ms** 后被 45 秒外层 deadline 取消，`native_rtc_creation=not_observed`；没有精确的后创建 ICE timeout 签名，不能称“native 创建已通过”或“确定为 ICE 握手超时”。根因仍未确定。

server PID 56244 只有 TCP `127.0.0.1:17880` 和 UDP `127.0.0.1:17882`。子 PID 62060 exit 1、退出及 socket 清理为真，server 清理为真；Python tasks/streams 清理为真、错误数 0。独立 OS 复查两 PID 均不存在，TCP 17880 / UDP 17882 endpoint 计数均为 0。真实双参与者、PCM、data、取消与重入仍未到达，不填 0 毫秒当低延迟，不再追加探针。

调用前后五个源码/脚本 SHA256 完全一致：

| 文件 | SHA256 |
| --- | --- |
| `realtime/livekit_transport.py` | `afbc81ed4f4d7641d2fd59ef60a5df470cb42be236595645ccbb14943b9db3db` |
| `realtime/protocol.py` | `dbd1ae6a61332a67503149d350d752e4b7af40a909d4dbc9209bfcb7de746f8b` |
| `realtime/local_server.py` | `888fb5831ceb237e76775136006d99bc2a570121edb3b524ed2e35430235d887` |
| `realtime/diagnostics.py` | `901937c37e9e8f9f9b58f9a29dd593317ee44b71d5e3a9ba0d4030d421caa3d1` |
| `scripts/probe_livekit.py` | `b09067fd08c573a04ed986446cd280ac0e08413e281db050fa4958c760ffafa4` |

旧结果 `independent-results.json` 没有覆盖；旧 wheel 已保留到 `build/package-check/historical-rtc-invalid/lingualoop-0.1.0-py3-none-any.whl`，其 SHA256 仍为 `2efd7fdbe1bf84c6c97845a08aa7f0893ea890e35301e506e7dab4d67aadc4fb`。它记录旧候选的包完整性和失败事实，不是合法配置修正后的分发包。

## 最终验收结论

材料/文本应用能力、失败恢复、长篇覆盖夹具与真实前台路由已有证据；最终有界模型探针还证明一次真实后台准备、校验与消费闭环。第二候选背景不可用的失败保留，不能用最新成功覆盖旧记录。合法 RTC 配置冻结候选独立全仓 **166 passed / 1 skipped**，最终 wheel 的 19 后端/5 realtime 模块、39 资源与可选依赖检查通过。之前 118 passed / 1 failed 的分类点击轮仍保留：其测试 helper 误点可视区外；后续同时修复的实际 composer 状态区跳动有独立测试覆盖，不能混为同一根因。138 项离线旧候选和空 ICE URL 包也保留为历史，不冒充最新候选。

**完整回复稳定小于 1 秒、真实 LiveKit RTC 链路仍未通过。** 用户决定允许先尝试本机探针后，已记录首次无效配置缺陷，并在合法 loopback 配置下仅做一次差异验证；该轮外层 deadline 取消，native 创建状态未知，后续文本/音轨均未到达。既有性能结果保持原样，不把统计改成首字/平均值来假装达成。STT/TTS、真人语音、国内三网稳定性、长篇整本真实分析质量与商业多用户分发仍未验。原文引用存在性也不等于每个回答要点的语义蕴含已经人工核实。

用户随后实际提交了“**1 秒保留为优化目标，文本功能通过后先做 LiveKit 探针**”（[历史执行记录 E32](../../archive/2026-10/ROADMAP_SNAPSHOT_2026-10-28.md#e32)）。因此文本正确性与真实前台链路验证后允许进行本地 LiveKit 探针；历史延迟失败照常保留，不能把探针、mock 或本机 RTC 结果写成真人语音已通过。未授权自动采购 STT/TTS、对外部署或扩大真实调用。本报告后续记录只按这项已提交的选择推进，不再等待或重复索要同一决定。

## 收束检查与数据边界

- `git diff --check` exit 0；仅有 Git 的 LF/CRLF 转换提示。新报告、产品文档、LiveKit 文档及文档索引共 6 文件的本地 Markdown 目标均存在；`pyproject.toml` / `uv.lock` / wheel metadata 的可选 RTC 版本一致，配置示例保留两个已验证 DeepSeek 模型 ID。
- 未进行提交、推送或发布；暂存区为空，保留原有工作树修改。`.env`、三次真实文本汇总、本机 RTC 汇总和 wheel 均被 Git 忽略；跟踪的环境配置只有 `.env.example`。
- 检查修改及未忽略新增文件，未发现数据库、音视频、模型权重、JSONL 或日志文件；对不超过 512KB 的文本做有限 `sk-…` Key 形态检查，没有命中。未打印任何 Key、token 或原始模型内容。此检查不是完整秘密扫描，也不声称审计了全部历史/忽略目录或供应商留存。

## 后续目标的独立验收边界

用户继续要求解决本机 RTC 超时，先跑通真实连续音轨与打断，再推进 STT/TTS。上文 166 项离线通过、`5ae286…` 包与 44.9 秒失败保留为上一候选证据；不能替代后续修复候选的真实验收。本轮执行顺序与分工仍由 Roadmap 统一管理，本段只记录独立验收边界和实证。

### 只读准备（05:58 UTC）

`research_services` 只读取现有分轮语音端口、应用/桌面契约和当前配置的非空存在性；没有启动 server/RTC/AI/STT/TTS，不与 RTC 实现者的实际实验并发。现有 STT 三个必填键和 TTS 四个必填键在进程环境及仓库 `.env` 均未配置，只记录键名/布尔状态，没有输出值。现有端口是完整 WAV/完整文本请求，不能作为流式接入已经完成的证据。

后续最小流式端口、ASR preview/final、TTS PCM/取消、pending 转写与历史持久化边界，以及不新增服务费用的 fake WebSocket + Mock LLM 路径已补入 [服务报告增量](../../research/SERVICE_SELECTION_2026-10-24.md#后续增量rtc-通过后的最小流式语音接入)。官方当前 Qwen-TTS 事件页没有已核实的远端 response-cancel；本地取消、关闭连接与供应商停止生成/停止计费必须分开说明。

### 新候选交接后的独立真实检查

待 RTC 实现者给出有依据的修复和冻结交接，再独立运行真实本机双参与者验证；运行前后记录候选指纹，确认来源/监听范围与当前授权一致。至少记录连续非零 PCM 帧、可靠文本顺序、流中取消、旧代际晚到事件拒绝、取消后新轮及显式 leave/rejoin；连接失败则记录精确阶段、耗时和 native 创建的 observed/inferred/unknown 等级，不把无法观测填成通过。

本轮协调者在“本机”范围内批准单个现有私有接口的有界实验：HTTP 仍为 `127.0.0.1`，RTC UDP 只允许 OS 确认属于本机且 SDK 已收集的单个 RFC1918 IPv4 `exact /32`，RTC TCP 关闭，参与者仍同机，不改 firewall/路由、不建网卡、不用公网。这样的结果必须标为 **`local-private-interface`**，不能称 strict loopback；先前仅 127 的失败不能被覆盖。独立验收按实际自有 server PID 核对地址/端口及最终回收，个人机器的完整接口明细不写入跟踪文档。

同时以自有 PID 和 OS socket 表核对退出回收，不用 Python tasks 数代替 native 资源释放。没有真实设备播放时，首 PCM 帧只称传输到达，不能称可听语音或自然打断。只有 RTC 连续路径独立通过后才验流式语音接线；无凭据的 fake 服务通过也不改变真实 STT/TTS 尚未验的事实。新实测结果在此追加，旧失败与已封顶的十轮真实 DeepSeek调用不重跑或改写。
