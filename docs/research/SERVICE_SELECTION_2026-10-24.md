# 双模型文本链路、实时语音与服务选型

核查日期：2026-10-24。本文记录官方能力、接口和实现建议；不是供应商实际可用性或延迟验收报告。执行状态统一见 [Roadmap](../planning/ROADMAP.md)，当前产品范围见 [MVP Spec](../product/MVP_SPEC.md)。

## 本轮结论

本阶段先完成材料与纯文本对话，并使用用户已配置的 DeepSeek 做有界真实测试；不要求配置 STT/TTS，不将已有分轮录音原型当成实时通话。用户随后明确选择“1 秒保留为优化目标，文本功能通过后先做 LiveKit 探针”（[历史执行记录 E32](../archive/2026-10/ROADMAP_SNAPSHOT_2026-10-28.md#e32)），替代早先的延迟硬门。探针先限定本地，不推定公网或真人语音已通过。完整回复未达到 1 秒的事实仍须保留，不能把“首字小于 1 秒”写成原目标达成。

推理和对话是两个独立调用角色：推理负责导入整理、自定义话题准备与后台预测；对话负责每次实际回复。后台准备只能为真实回答提供候选依据，不能把预测写成用户已经说过的话。

后续在线日语语音建议先试阿里百炼北京地域的流式 ASR + Qwen3-TTS；火山作为第二候选。两者都需要真实日语、国内不同网络和连续打断测试才能确定默认值。腾讯独立 TTS 文档目前只列中英文，不能作为已核实的日语默认方案。离线内嵌具备技术可行性，适合做按需下载的可选语音包；本轮不下载或集成模型。

## DeepSeek 官方契约

用户提供的 `deepseek-v4-pro` 和 `deepseek-flash` 都是当前官方 ID，无需改成旧的 `deepseek-reasoner` / `deepseek-chat`。截至核查日，官方当前表分别对应 Pro-0813 与 V4.1-Flash-1017；ID 为滚动服务名，后续测试要记录服务返回的模型标识。两者支持 JSON 输出与 1M 上下文；这些容量上限不意味着适合把整本小说放入每轮提示词。[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)、[模型发现接口](https://api-docs.deepseek.com/api/list-models/)

| 项目 | 本项目用法 |
| --- | --- |
| Base URL | `https://api.deepseek.com`，官方兼容 OpenAI Chat Completions |
| 请求 | `POST /chat/completions`；不依赖 Responses API 特性 |
| 材料/自定义题推理 | `deepseek-v4-pro`，显式 `thinking.type=enabled`、`reasoning_effort=high` |
| 微型后台准备 | 同一 Pro 保持思考开启，按任务显式覆盖 `reasoning_effort=low`；最终一次真实 4,000 token 预算探针约 10.7 秒生成有效准备，随后 Flash 实际消费。仅此单样本，不是每轮命中或延迟保证 |
| 对话角色 | `deepseek-flash`，显式 `thinking.type=disabled`；短回复、流式输出 |
| 原有全局关闭思考 | `OPENAI_DISABLE_THINKING=1` 可继续表达快速对话偏好，不能连带禁用推理角色 |
| 返回 | 展示及持久化最终 `content`；不保存或显示 `reasoning_content` |

两种模型默认都开启思考，默认强度 high；官方支持 `low/high/max`，`medium` 被映射到 high 而不是独立档。SDK 的 `thinking` 要通过 `extra_body` 传入。无工具调用时不需要传回历史思考内容。不要给每轮对话加入工具调用或等待推理完成。以上是官方参数事实，按角色和任务覆盖是本项目的实现选择。[首次调用](https://api-docs.deepseek.com/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)

官方当前价格按每百万 token 分缓存命中、未命中、输出及峰谷；这是服务费用，不是软件授权费。应记录实际 usage 和调用次数，分别显示材料分析、后台整理、对话的消耗。本轮不购额、不创建供应商账号、不扩大到自动长篇整本测试。官方公开文档未给出本项目条件下完整回复小于 1 秒的保证，必须实测。[价格](https://api-docs.deepseek.com/quick_start/pricing/)

## 四类 AI 能力之外需要什么

四种能力可以由少于四家供应商提供；推理和对话也可以共享同一账号但独立配置模型、思考模式、超时及并发预算。

| 服务或组件 | 何时需要 | 推荐边界 |
| --- | --- | --- |
| 推理 LLM | 当前文本阶段必需 | 导入分析、自定义题准备、背景整理；失败保留原材料和已有会话 |
| 快速对话 LLM | 当前文本阶段必需 | 所有实时回复只走此角色；不得在关键路径等待推理 |
| STT | 启用语音时必需 | 流式音频转写、中间/最终结果、日语及中日切换；接口独立 |
| TTS | 启用语音时必需 | 文本流输入、音频流输出、取消、日语音色；接口独立 |
| LiveKit RTC / SFU / TURN | LiveKit 阶段必需 | 云服务或自托管均可；是传输层，不代替 STT/TTS/LLM |
| Agent worker | LiveKit 阶段必需 | Python 常驻服务或本机进程；执行流式语音 pipeline 和现有应用服务 |
| 短期 room token 签发 | 分发给普通用户时必需 | 服务端保管 LiveKit secret，验证身份、房间权限与额度；桌面仅拿短期 token |
| VAD、轮次判断、回声消除 | 自然双工语音必需的能力 | 可以本地或由 RTC/Agent 提供，不一定另购云 API；尤其验证学习者长停顿和短附和 |
| 视频字幕/音轨提取 | 导入视频时条件必需 | 优先已有字幕；没有字幕时才离线或在线转写，明确耗时/费用/能力边界 |
| 文件上传/对象存储 | 供应商只接 URL 或跨端同步时条件必需 | 优先本地流和短期上传；不为文本 MVP 引入公开文件桶 |
| 账号、配额与计费后端 | 产品代管服务密钥时必需 | BYOK 本地版可暂不建设；不能向所有桌面客户端分发同一个厂商密钥 |
| 云数据库、向量库、embedding、reranker | 当前不是必需 | SQLite + 片段索引/结构化预制内容足够本阶段；有检索证据后再引入 |
| OCR、翻译服务、发音评分 | 特定来源/体验下可选 | 扫描件才需 OCR；翻译可由现有模型承担；ASR 文本不能替代发音评测 |
| 录音 egress、SIP 电话、avatar | 当前可选且未启用 | 学习会话不默认录音、不需要电话网；不随 LiveKit 自动部署 |

LiveKit 官方明确要求生产 token 在后端生成，并提供 Python Agent、原始音轨与可替换模型插件。将 token、Agent、SFU 分成服务职责，不意味着必须买三套云产品；单机开发可以共置。[鉴权](https://docs.livekit.io/frontends/build/authentication/)、[Agents](https://docs.livekit.io/agents/)、[Python SDK](https://github.com/livekit/python-sdks)

## 国内在线语音候选

下表“可用”只表示有对应官方接口/区域/语言说明。未做真实调用、学习者口音准确率、SLA 合同核对或国内三网测试，不能据此宣称稳定或达到某毫秒延迟。不同产品的“流式”含义不同：只有音频流输出的 TTS，仍可能要求一次提交完整文本。

| 候选 | 已核实的中日语与流式能力 | 接入与后续测试重点 | 判断 |
| --- | --- | --- | --- |
| 阿里百炼 ASR | `qwen3-asr-flash-realtime` 支持中文/日语，WebSocket、PCM/Opus；较新的 `qwen-audio-3.1-asr-flash-streaming` 和 message 系列支持日语、热词及上下文 | 北京地域 Key/端点配对；需核对具体语音协议，不能直接复用当前 WAV HTTP adapter。比较原始日语转写与润色后文本，避免改写掉学习错误 | 第一轮在线 STT 候选；实时接口和语言见 [官方概述](https://help.aliyun.com/zh/model-studio/asr-model) |
| 阿里百炼 TTS | `qwen3-tts-flash-realtime` 支持分批文本输入与连续会话；官方音色表有日语，`Ono Anna` 为云端参数，注意与本地权重的 `Ono_Anna` 不同 | 北京支持；选择正式音色后试听日语专名、长音/促音、汉字多音。Qwen-Audio/CosyVoice 官方另提供任务取消，不能假定所有系列事件相同 | 第一轮在线 TTS 候选；[实时合成](https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide)、[音色表](https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list) |
| 火山/豆包 ASR | 大模型流式 API 提供双向流，语言参数列出 `ja-JP`；不能把默认空 language 的语言检测范围等同为全部日语能力 | 开通对应资源 ID，固定日语实测；比较不同版本/模式的中间结果修正、结束判断及热词。官方页面依赖 JS，核查使用官方搜索摘要，集成时再读完整协议 | 第二候选；[流式识别 API](https://docs.volcengine.com/docs/DoubaoVoice/LargemodelstreamingautomaticspeechrecognitionAPI?lang=zh) |
| 火山/豆包 TTS | V3 WebSocket 双向流可边发文本边收音频，列出 `ja`；音色与模型资源 ID 有版本约束 | 需选择明确支持日语的音色/资源；验证取消与旧音频清空，不借用营销“首包”数字作项目指标 | 第二候选；[双向流式 V3](https://docs.volcengine.com/docs/DoubaoVoice/WebSocketBidirectionalStreaming-V3?lang=zh) |
| 腾讯 ASR | 实时 WebSocket 官方有 `16k_ja`，也有普通话和多语种 | `AppID/SecretID/SecretKey` 签名；大陆站与国际站/跨境版分别计费，需逐一核对所选引擎 | 可单独比较 STT；[实时识别](https://intl.cloud.tencent.com/zh/document/api/1118/53937) |
| 腾讯独立 TTS | stream_wsv2 可流式输入文本，但当前接口明确中/英音色；不能从“实时音视频 AI 智能语音”的日语例子推定这个接口也支持 | 若继续选择腾讯，需要厂商正式确认日语直连 API/voice；TRTC 是另一套产品，不因有日语能力而取代用户指定 LiveKit | 日语默认暂不选；[流式文本 TTS](https://cloud.tencent.com/document/api/1073/108595)、[音色列表](https://cloud.tencent.com/document/product/1073/92668) |
| 讯飞 ASR | 听写流式 WebSocket，日语需开通小语种；单次用于 1 分钟内语音。动态修正当前仅中文 | 小语种端点不同；AppID/APIKey/APISecret 或对应产品鉴权。连续会话要处理分段、重连和权限 | 备选；[流式听写](https://www.xfyun.cn/doc/asr/voicedictation/API.html) |
| 讯飞 TTS | 在线 WebSocket 支持日语，需控制台授权小语种发音人；当前 v2 接口每会话发送一次文本，音频流式返回 | LLM 输出须分句提交，需额外验证拼接和取消；不要把“WebSocket”当成任意增量输入。日语 WebAPI 能力不能外推离线 SDK | 可用备选；[在线合成协议](https://www.xfyun.cn/doc/tts/online_tts/API.html) |

### 费用口径

下表是核查日公开刊例/指定资源包样例，不含优惠、并发增购、网络、LiveKit 和应用服务开销，不直接等同实际账单。资源包不能横跨产品或地域套用。

| 产品样例 | 核查到的计费单位/示例 |
| --- | --- |
| 阿里北京 Qwen3-ASR realtime | 0.00033 元/输入音频秒，约 1.188 元/小时（算术换算）；新 ASR-3.1 streaming 改为输入 6 元/百万 token、输出 4.5 元/百万 token，不能用秒价估算 |
| 阿里北京 Qwen3-TTS realtime | 1 元/万输入字符；新 Qwen-Audio-3.1-TTS-Flash 是输入 1.5 元、输出 12 元/百万 token |
| 火山大模型流式识别资源包样例 | 30 小时/132 元，4.4 元/小时；不同新旧版本、并发版/时长版不同 |
| 火山语音合成资源包样例 | 模型 2.0 的 10 万字/28 元，即 2.8 元/万字符；旧大模型 10 万字符/45 元；须按所选日语资源确认 |
| 腾讯大陆普通实时 ASR | 后付费 0–299 小时/日档为 3.20 元/小时；当前大模型 2.0 另列 1 元/小时，但不推定该档覆盖同一个日语引擎 |
| 讯飞 | ASR 套餐按调用次数，并另有小语种/方言授权；TTS 按产品/音色套餐的调用次数或字符量。日语最终价格和并发需看已开通控制台报价，本轮未冒充取得报价 |

对应官方价格：[百炼](https://help.aliyun.com/zh/model-studio/model-pricing)、[火山](https://docs.volcengine.com/docs/DoubaoVoice/Billinginstructions-21?lang=zh)、[腾讯 ASR](https://cloud.tencent.com/document/product/1093/35686)、[讯飞听写](https://www.xfyun.cn/service/voicedictation)、[讯飞 TTS](https://www.xfyun.cn/services/online_tts)。

### 面向未来用户的接入方式与隐私

本地开源版先保持 BYOK：用户自己的供应商 Key、配额和模型配置，凭据留本机。后续普通用户版可代管账号与计费，但必须由应用后端保管长期服务密钥、发短期房间 token、限额和隔离用户数据；不能把开发者 Key 打进安装包。BYOK 和后端代管均需遵循对应 API、SDK 与音色的服务协议，不把 API 额度当成可自由转售的许可证。

阿里当前隐私说明区分“不用于训练”与“存储模型/应用调用数据”；不能声称零留存。国际站企业的 ZDR 能力有申请和适用范围，不自动适用于北京个人账号。[隐私说明](https://help.aliyun.com/en/model-studio/privacy-notice)、[国际站留存政策](https://www.alibabacloud.com/help/en/model-studio/data-retention-policy)

讯飞明确其 SDK/API 会处理终端用户的音频、文本；在线 TTS SDK 隐私政策写明大陆服务/大陆存储和必要期限留存，并未给当前方案一条统一固定天数。[平台政策](https://www.xfyun.cn/doc/policy/privacy.html)、[在线 TTS SDK 政策](https://www.xfyun.cn/doc/total_sdk_privacy/online_tts_privacy.html)

本次未取得火山和腾讯所选具体语音 SKU 的可核实统一留存天数、API 专用“不训练”保证或本项目 SLA。接入前需针对实际服务确认；不要用集团隐私政策或产品品牌替代合同事实。项目自身默认不录制通话、不把原始音频写入业务数据库；传云的原文/对话同样属于敏感学习数据。

## STT/TTS 能否内嵌

可以，但“SDK 开源”“权重允许商用”“适合普通 Windows CPU 实时”是三条不同结论。优先采用按需下载、明确模型版本/校验和、可删除语音包，不把数百 MB 到 GB 权重塞进基础 wheel。以下均是候选研究，未在本机加载、试听或测速。

| 方案 | 能力与体积证据 | 许可证与限制 | 建议 |
| --- | --- | --- | --- |
| sherpa-onnx + SenseVoice INT8 | 官方支持 Windows/Python、中英日；2024 转换模型 ONNX 文件约 228 MB，另需 tokens、VAD 和 runtime。SenseVoice 属非流式模型，借 VAD 分段模拟连续转写，不等于每帧原生流式 | sherpa runtime Apache-2.0；SenseVoice 源码 MIT，官方权重另依 FunASR Model License，不能套用 runtime 许可证。转换权重与实际包内依赖需单独核对 | 最小离线 STT 候选，先测日语学习者/人名与 VAD 截断 |
| sherpa-onnx / Qwen3-ASR 0.6B | 官方 Qwen3-ASR 支持多语，0.6B 权重属于更大下载/内存档；runtime 及量化产物大小要固定版本后测量 | Qwen 官方模型页 Apache-2.0；第三方量化产物核查其来源和附加文件 | 可比 SenseVoice 质量，但不直接承诺 Windows CPU 延迟 |
| Kokoro-82M | 82M 参数，官方原始权重 327 MB、仓库约 363 MB；有日语和普通话音色、需要对应 G2P | 官方权重 Apache-2.0；日语音色页有部分 CC BY 来源，需保留归属；G2P/词典/可选 eSpeak 的许可证独立审计 | 小型本地 TTS 候选；日语专名与读音质量必须听测 |
| Qwen3-TTS 0.6B CustomVoice | 官方支持中文/日语及 `Ono_Anna`；官方示例采用 CUDA/FlashAttention，不能把其 97 ms 研究指标套到普通 CPU | 官方模型 Apache-2.0；实际 tokenizer、运行时和权重合计以固定快照统计 | GPU 可选语音包候选，先做 Windows CPU/GPU 分档实测 |
| Supertonic 3 / sherpa-onnx | 小型 ONNX TTS 官方有日语但当前列表无中文；仓库 2026-09-09 已归档，停止维护 | 源码 MIT，权重单独条款；不能只凭源码许可证打包 | 不作中日双语默认；保留日语专项探针价值 |

来源：[sherpa-onnx 平台/许可证](https://github.com/k2-fsa/sherpa-onnx)、[SenseVoice 接入](https://k2-fsa.github.io/sherpa/onnx/sense-voice/index.html)、[转换产物大小](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)、[SenseVoice 官方许可证说明](https://github.com/QwenAudio/SenseVoice/blob/main/README.md)、[Qwen ASR 模型](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)、[Kokoro 模型](https://huggingface.co/hexgrad/Kokoro-82M)、[Kokoro 文件](https://huggingface.co/hexgrad/Kokoro-82M/tree/main)、[Kokoro 音色/G2P](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)、[Qwen TTS 权重](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)、[Supertonic 归档](https://github.com/supertone-oss-archive/supertonic)。

本地验收应记录：Windows/CPU/GPU/内存、首次加载与热态、实际安装/模型字节数、首段音频时间、生成 RTF、10–30 秒日语转写耗时、专名/否定/中日混合错误、断句/取消、卸载与离线运行。官方别的硬件成绩只用于选择探针，不能当本机通过证据。

## LiveKit 实施边界

LiveKit 提供音轨、房间、WebRTC 传输、Agent pipeline、轮次与打断控制，不能消除远端模型生成和网络耗时。沿用 Python core，新增可选 `livekit` / `livekit-agents` 集成层；QML 仍只消费会话状态，不绑定厂商协议。

Qt 没有本次已核实的 LiveKit 专属 QML 控件。建议先用官方 Python RTC SDK 做独立进程探针，通过音轨 PCM 与 Qt 音频输入/输出桥接，再决定同进程或 sidecar。原始 PCM 路径要显式处理重采样、缓冲、AEC、设备切换与退出；不能假定 Qt 录制完整 WAV 的原型直接变成自然双工。[Python SDK](https://github.com/livekit/python-sdks)、[模型 pipeline](https://docs.livekit.io/agents/models/pipelines/)、[噪声与回声消除](https://docs.livekit.io/transport/media/noise-cancellation/)

| 路径 | 能力事实 | 对本项目的影响 |
| --- | --- | --- |
| LiveKit Cloud | 托管 SFU/TURN/Agent 等；官方区域表目前 Asia Pacific 为日本、新加坡，未列大陆区域 | 可以做开发探针；国内三网连通、丢包与跨境隐私均需测量，不能宣传大陆稳定 |
| 国内自托管 LiveKit | 官方开源服务支持自托管及自有 provider；需要域名/TLS、SFU、UDP/TCP/TURN 防火墙和 Agent 运行资源 | 可作为未来国内路线候选；本轮不部署公网服务器、不购买资源。开发 localhost 与公网验收分开 |

来源：[自托管比较](https://docs.livekit.io/transport/self-hosting/)、[区域](https://docs.livekit.io/deploy/admin/regions/endpoints/)、[网络端口](https://docs.livekit.io/transport/self-hosting/ports-firewall/)、[轮次调优](https://docs.livekit.io/agents/logic/turns/tuning/)。模型插件可以自接国内 API，不强制使用 LiveKit Inference；自托管不自动包含托管推理或高级降噪授权。

## 文本验收门与有界素材

### 公开测试材料

首选芥川龍之介《蜘蛛の糸》日文短篇：[图书卡 No.92](https://www.aozora.gr.jp/cards/000879/card92.html)、[青空正文](https://www.aozora.gr.jp/cards/000879/files/92_14545.html)。卡片记录初刊 1918、作者 1927 年去世；青空的公版处理规范允许下载/再分发，并希望保留作者、底本、录入/校对与文件来历。本项目测试保留这些信息，若做去 ruby/断行清洗记录转换方式，不将青空所有作品一概视为公版。[处理规范](https://www.aozora.gr.jp/guide/kijyunn.html)

小说适合覆盖梗概、人物、动机、道德评价和结局争议；涉及的观点是讨论角度，不是系统给用户打分的标准。首轮真实调用上限：一份短篇（小于约 2 万字符），分析一次，最多 10 轮代表性回复/重试；失败先读证据，不自动改跑整本、加并发或无限重试。离线单元测试优先用自写夹具；真实测试不得把完整模型调用日志、个人数据或密钥写入仓库。

### Gate A：材料与文本正确性

- 原文先保存，规范化文本、章节/片段、人物和话题可回溯来源；长内容不静默截断，需明确当前覆盖范围。
- 丰富话题覆盖核心内容、角色、动机、观点与结局；每题有常见回应分支、简短回答要点、追问与证据。材料不足时减少数量或标注不足，不能为凑数虚构事实。
- 自定义题先由推理准备；进度可见、可取消/重试，已有材料和会话不丢失。
- 实际逐轮回复只由 dialogue 角色生成；推理后台失败/超时不会阻断发送。
- 测试人物偏好、理由、改口、未预测输入、材料外问题、注入指令、后台过期结果、自定义题、失败重试及重启恢复。候选包需要按 material/topic/session/turn 修订校验，过期不覆盖当前状态。

### Gate B：真实文本与性能

在真实服务上执行导入 → 选择预制题 → 至少 3 轮日语交流 → 自定义题 → 多轮 → 复盘/重启。分别记录冷/热连接、背景准备命中/未命中，公开脚本、版本/配置名、统计和限制，输出内容只保留必要脱敏断言。

| 指标 | 起止与用途 |
| --- | --- |
| provider TTFT | 发出 HTTP 请求至首个非空可见 `content`；忽略 keepalive / reasoning chunk |
| provider complete | 发出请求至最终可用回复；用户要求的模型 1 秒目标按此单独判断 |
| UI 首字/完整 | 用户发送至界面显示首字/完成，包含排队、持久化与桥接开销 |
| preparation | 材料分析、自定义题准备、后台整理单独耗时；不能藏进对话计时前 |
| 质量/调用 | 有依据、接住当前输入、长度适当、无预测冒充事实；记录重试、错误和 token usage |

1 秒完整输出不能从 token 缓存、供应商模型名或流式功能直接推导。优化顺序：连接复用；缩短请求/上下文；限定自然的一至两句；热点分支预制；异步整理限流/取消/合并；流式 UI；比较实际输入长度和输出 token 数。缓存命中是费用/前缀复用机制，不能假定会缓存任意新回复。即使首字达标，完整回复超时仍记性能失败，不能偷偷换验收口径。

本轮实际 HTTP 共 10 个前台回复，分三个候选分别记录，不合并冒充同一版本性能分布：旧候选 6 轮完整 904.7–1668.3 ms，短 prompt 候选 3 轮 731.4–1259.6 ms，最终背景修正后一次为 1060.3 ms。后台最终一次 low/4,000 token 请求约 10.7 秒有效就绪，引用校验与后续 Flash 上下文实际消费均通过；不能推导每轮 1 秒内整理或自然会话命中率。完整回复 1 秒优化目标尚未达成稳定证据，见 [独立文本验收](../validation/text/TEXT_ACCEPTANCE_2026-10-24.md)。

### Gate C：之后的 LiveKit 探针与语音验收

文本正确性与真实前台链路验证后，可以按用户 E32 决定先做 LiveKit 本地探针；Gate B 的完整回复 1 秒仍是优化目标，当前失败不会被改写成通过。先做本机双参与者音轨和 token/worker 生命周期，再接选定中日语 STT/TTS；不因本地探针而自动部署公网或购买语音服务。正式语音验收至少三轮真人语音、自然停顿、边说边识别、流式播放、用户打断、播放队列清空、回声/耳机、断网重连、设备切换、终止清理及原始音频不落库。端到端另测“用户说完 → 首段可听语音”，不能拿文本指标代替语音延迟。

本轮独立本机首探针返回 `ConnectError`，后续静态追查确证该候选的空 ICE URL 项不符合 native WebRTC 校验，不能把它解释为环境不支持。修正为仅指向已审计 UDP endpoint 的合法 `stun:127.0.0.1:17882` 后，仅追加一次差异验证：在 `client_connect` 的 45 秒外层 deadline 取消，native 创建状态 `not_observed`，未到真实双参与者音轨/data/取消。两次的 loopback server 与进程/端口清理均经 OS 复查；合法配置后的连接根因仍未确定。离线协议测试不能替代 RTC 通过。具体运行、冻结指纹与范围见 [独立验收](../validation/text/TEXT_ACCEPTANCE_2026-10-24.md#本机-livekit-独立探针)、[LiveKit 文档](../desktop/LIVEKIT.md)。

## 后续增量：RTC 通过后的最小流式语音接入

用户新增目标是先解决本机 RTC 超时、真实连续音轨和取消，再推进 STT/TTS。以下是 2026-10-24 的只读接入契约建议，**尚未实现或验收**；执行状态仍以 Roadmap 为准，不覆盖上轮失败或安装包指纹。本次只读期间没有启动 server、RTC 或任何 AI/语音服务。

### 本地配置与现有接口

05:58 UTC 对当前进程环境与仓库 `.env` 作非空存在性检查，未输出任何配置值：

| 现有必填键 | 是否齐备 |
| --- | --- |
| `LINGUALOOP_STT_BASE_URL`、`LINGUALOOP_STT_API_KEY`、`LINGUALOOP_STT_MODEL` | 三项均未配置，STT 不齐备 |
| `LINGUALOOP_TTS_BASE_URL`、`LINGUALOOP_TTS_API_KEY`、`LINGUALOOP_TTS_MODEL`、`LINGUALOOP_TTS_VOICE` | 四项均未配置，TTS 不齐备 |

也未发现常见阿里/火山/腾讯/讯飞或本地语音模型配置键；这只是当前进程和这一份 `.env` 的有限检查，不代表机器其他位置没有账号。现有 DeepSeek 凭据不能被当成语音凭据，更不能据此试探音频 API。

`core/voice.py` 与 `providers/speech.py` 当前只有整段 `transcribe(WAV) -> str`、`synthesize(text) -> WAV`，由 HTTP 请求返回完整结果。Qt `AudioController` 使用 `QMediaRecorder/QMediaPlayer` 和临时文件。应保留该分轮回退，另加流式端口；将完整 WAV 拆小发送并不会变成已经验证的流式识别/合成。

当前 `SpeechSettings` 的 URL 校验与 `/v1` 规范化服务于 HTTP-compatible 端点，不能接收带 model query 的 `wss` realtime 地址。后续需要独立流式设置与明确 protocol，分别配置 WS endpoint、model、voice 和语言，再按供应商契约构造 model query；Key 只放鉴权 header。不要把旧 BASE_URL 原样替换为 WebSocket 地址，或隐式继承 `OPENAI_*` 凭据。本段是配置设计建议，没有新增环境字段、自动连接或试探服务。

### 已补核的官方协议事实

阿里 Qwen-ASR-Realtime 可发 PCM 音频片段，支持 16kHz/8kHz；手动模式通过 commit 划定一句，VAD 模式由服务识别边界。结束 session 会等待最后识别结果，不是中断正在进行的识别。语言已知时可指定日语；不要混入 Omni 或翻译模型事件。[ASR 客户端事件](https://help.aliyun.com/en/model-studio/qwen-asr-realtime-client-events)、[ASR 接入指南](https://help.aliyun.com/en/model-studio/real-time-speech-recognition-user-guide)

ASR 中间事件的 `text + stash` 是本次预览，后半部分允许修正；应按 utterance/item ID 替换预览，不能把每次预览追加到同一个字符串。只有 `conversation.item.input_audio_transcription.completed` 的 `transcript` 才是该 item 的最终转写。`speech_stopped` 本身不是最终文本。[ASR 服务端事件](https://help.aliyun.com/en/model-studio/qwen-asr-realtime-server-events)

Qwen-TTS-Realtime 支持增量文本 append 和手动 commit，可请求 PCM，并列出 8/16/24/48kHz 输出和 Japanese 语言选项。接入时固定所选模型/音色，并等待 session 配置确认。当前客户端事件页只有 append、commit、clear、finish 等，**没有核实到 `response.cancel`**；clear 清缓冲文字，finish 反而返回剩余音频。不能将它们解释为停止在途合成或停止计费。[TTS 客户端事件](https://help.aliyun.com/en/model-studio/qwen-tts-realtime-client-events)、[TTS 服务端事件](https://help.aliyun.com/en/model-studio/qwen-tts-realtime-server-events)

以上 Qwen realtime 是独立 WebSocket session；另一类 `/api-ws/v1/inference` 使用 task 协议。不要把 CosyVoice 的取消、Omni 的 response 事件或其他模型的采样参数移植过来。端点、鉴权和地域须与实际账号匹配；此处没有新增配置项或采购服务。[WebSocket 协议区分](https://help.aliyun.com/en/model-studio/realtime-websocket-overview)

### 最小端口与编排边界

以下名字表达契约，不是现有 Python API：

| 边界 | 最小行为 |
| --- | --- |
| `StreamingSTTSession` | `push_audio` 接受带格式的原始 PCM；`events` 迭代 speech-start、可修正 partial、final、error；`finish_input/close` 明确收尾、可重复关闭 |
| `TranscriptEvent` | 带 session/input-utterance ID、revision、partial/final 和文本；final 按 item ID 去重。输入 utterance 的身份独立于正在播放的 reply generation |
| `StreamingTTSSession` | 逐句/短语 `append_text`，`finish_text` 后排空；`audio_chunks` 迭代带采样率/声道/编码的 PCM；`cancel/close` 首先停止本地消费和关闭连接，不承诺远端已停止或费用归零 |
| 语音编排 | 只把确认后的 final 交给 `LearningWorkbench.send_message(on_delta=...)`；Flash 仍是实际回复模型，Pro 不进语音关键路径。TTS 只消费可见回复，不消费 CoT |
| RTC/设备边界 | 使用同一 reply `TurnRef/generation`；一轮一条连续音轨，不能每个 token 建新轨。RTC 目前为 48kHz mono S16LE；STT 16kHz 要有状态重采样；TTS 可先请求已支持的 48kHz，实际不符则显式转换 |
| 桌面 | PCM 采集/播放需独立 `QAudioSource/QAudioSink` 桥接与有界缓冲，Qt 对象留主线程。旧录音文件与播放器不能充当可清空的实时设备队列 |

进入连续语音模式必须有明确“开始”操作，之后按该模式的端点策略把 final 作为确认输入驱动轮次，partial 只作可编辑预览。不能在未开启语音模式时自动发送转写。VAD/静音阈值、长停顿和短附和需要后续日语学习者实测；服务端默认值不是学习体验验收。

当前应用服务在整轮成功后才保存用户与 assistant，`send_message` 仅提供字符串 delta；桌面 `AsyncWorker.submit` 不返回可用于单轮取消的 handle。因此需要独立编排 task/代际门，取消时等待旧发送清理 `_sending` 再提交新轮。最小方案可保留现有整轮提交规则：未完成轮次的用户 final 留作明确的 pending 转写供重试，不能把未保存状态假称历史已确认保存；若改为用户 final 立即入库，需另行定义中断 assistant 的状态和历史兼容，不可静默改变持久化语义。

打断先同步关闭旧回复的呈现门、清 RTC source 与设备播放缓冲，再取消旧 LLM/TTS task、关闭对应 TTS 连接；后续晚到 delta/PCM 一律按代际丢弃。新的麦克风/STT utterance 应继续收集，不能用“取消旧回复”清空新发言。TTS 失败仅重试 TTS，不能重新生成已完成回复或重复调用 Pro。原始 PCM、partial、厂商原始错误和凭据不写业务库或报告。

### 无新增服务费用的接线验收

RTC 真实连续 PCM/取消/重入先独立通过，随后可用 fake WebSocket + Mock LLM + 已通过的真实本机 RTC 完成接线，仍不称真实 STT/TTS 已通过。最小测试应包含：

- ASR partial 修正和 final 去重，乱序/旧 utterance 事件不触发重复发送；空、静音、失败结果不进入业务历史。
- LLM 日语分句缓冲只把单调可见文本交给 TTS；网络 PCM chunk 被拆成奇数/不足一帧时正确组帧或报格式错误，不截掉字节、混入 WAV 头或假报采样率。
- 假服务在取消后故意继续发旧转写/旧 PCM，旧音频呈现数应为 0；新 utterance 和 generation 正常继续。取消确认、最后旧帧与设备队列清空分别量测。
- 模拟 401/403/429、断连、半段 TTS、晚到 final、队列背压及重复 close；保留已完成消息，重试不重复 LLM/Pro 调用，不自动无限重播音频。
- 流结束、超时、切材料、结束与退出都释放自有 tasks/socket/track/设备，临时音频无新增落库。mock 仅证明协议和接线，不能证明日语准确度、自然打断或音质。

当前没有可用语音凭据，所以本次不启动付费语音验证。未来已有配置并获得该阶段调用授权后，可先限定最多三句、总输入音频不超过 60 秒、TTS 不超过 500 字符的一次试验；记录实际上传音频秒/合成字符或 token、请求数、取消请求用量未知。不要开长期静音传输、并发多供应商比较、自动购买或把远端取消当作免计费。该建议预算不是供应商免费额度或报价承诺。

官方流式/语言研究仅达到静态证据等级；mock 只能证明边界/调度/UI；真实文本只证明当时账号/网络/材料；语音、跨网稳定性和商用多用户仍要分别验收。本文不将任何未跑项目记为通过。
