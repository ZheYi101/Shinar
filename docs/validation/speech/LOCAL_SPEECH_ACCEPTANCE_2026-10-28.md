# 本地语音阶段 1 / 2 验收：2026-10-28

## 交付范围

已实现模型目录、硬件检测、固定包下载/续传/校验、独立进程计算测速，以及桌面端筛选、试听、候选保存、配对测速和卸载。现有文本/云语音 provider 与学习数据库未切换。本阶段不声明真人语音、完整 LiveKit 对话或停顿到出声 ≤1 秒通过。

本次模型、临时示例、数值报告及 UI 证据保存在 ignored `build/local-speech-evaluation/`。正常 AppData 学习库未写入测试数据。测试只下载官方模型/样例，不读取用户小说、对话记录或文本服务凭据。

## 本机计算实测

Windows x64，i9-14900HX，32 逻辑核心，约 32GiB RAM；检测到 RTX 4060 Laptop 8GiB，但**全部测 CPU**，每模型 2 线程。固定 sherpa-onnx 1.13.8 / numpy 2.4.6。ASR 使用官方 SenseVoice 包的中英日样例，约 5.6 / 7.2 / 7.2 秒；TTS 使用项目自写的三句短讨论提示。5 次热态，另保留冷加载和首次推理。表中 p95 是 5 个样本的最大值，不是对大人群或长时负载的稳定性保证。

| 模型组合 / 语言 | ASR 最后计算 p95 | TTS 首 PCM p95 | 同进程峰值 RAM | 结论 |
|---|---:|---:|---:|---|
| Zipformer + Piper Lessac / 英语 | 12ms | 100ms | 268MiB | 计算延迟有潜力；Piper 具体声音未列默认下载，许可需进一步核对 |
| SenseVoice / 日语，单模型，最终 5 次复测 | 226ms | 未测 | 345MiB | 日语 STT 可继续评估；初次同配置测得 239ms，日语 TTS 仍为候选 |
| SenseVoice + Kokoro INT8 / 英语 | 262ms | 1909ms | 688MiB | TTS 明显超出初步实时预算 |
| SenseVoice + Kokoro INT8 / 中文 | 219ms | 2966ms | 774MiB | TTS 明显超出初步实时预算；串行最慢 3026ms |
| SenseVoice + Melo / 英语 | 282ms | 840ms | 706MiB | 比 Kokoro 快，但尚不足以承担一秒全链路目标 |
| Zipformer + Melo / 中文 | 17ms | 940ms | 489MiB | 流式 ASR 尾计算轻；TTS 仍是瓶颈 |

配对行同时运行 STT 与 TTS。Zipformer 在语音期间增量解码，表中尾计算不含之前已消耗的计算，也不含 660ms flush padding 所代表的真实等待。SenseVoice 的“最后计算”是整段识别耗时，不能将两者当成同样的端点行为。此次没有接麦克风、VAD、LLM、RTC 或扬声器。

冷加载大约 0.6–2 秒/模型，首次推理另记。下一阶段应在开始通话时预热，不能每轮启动新进程。本阶段使用短命进程是为可靠测速、取消和资源释放；不是最终连续语音 worker 的生命周期实现。

原始数值位于 `cache/reports/*.json`，包含逐次样本、冷加载、首次推理、p50/p95、并发与峰值、包指纹及运行时。报告不保存 ASR 文本或输入音频路径。ASR 仅检查产出非空，**准确率没有验收**；没有用 TTS 自产音频给 ASR 虚增准确率。

最终报告带时间戳保存，重复测速不覆盖历史。干净环境只安装 wheel 的 `local-speech` extra 后也能执行真实日语识别；安装器额外显式固定 `sherpa-onnx-core`，避免上游不同分发格式的依赖元数据差异导致缺 DLL。

## 失败与修正

- GitHub 模型下载多次出现中途断流；显式 Range 续传后校验完整大小和 SHA256。下载管理测试覆盖服务器忽略续传、错误范围、大小与哈希错误、取消和重入。
- 初选 sherpa 2.0.1 时，Piper 包得到空音频；实际 native 诊断表明 2.x 不再处理旧 VITS data_dir，需要外部 phonemizer。改用 1.13.8 后复测上述所有组合。旧 2.0.1 数值留在 `reports-sherpa-2.0.1/`，UI 不混用。
- Kokoro 1.1 的声音序号与 1.0 不同，采用官方映射 `af_maple=0 / zf_001=3`；没有把日语声音权重误当作当前 ONNX 日语前端已可用。
- Piper Lessac 技术评估包仅保存在本机；其模型卡引用研究数据许可，未明确完成成品权重再分发审核，因此没有加入公开一键下载目录。不是性能通过就自动发布。
- 软件渲染时 Qt Material Dialog 背景出现透明体区，改用项目 `MDialog`，修复截图后复验。STT 卡片曾错误显示配对 TTS 的试听按钮，已限定为 TTS 显示。
- 进度定时器曾触发模型列表全量刷新，已拆分 progress/models 信号；测试检查后台任务期间进度更新不会重建卡片。

## 验证与证据

- 下载/安装：路径与 Windows 设备名拒绝、安全展开、哈希/Range、崩溃残留、锁、取消、损坏校验、卸载保留其他版本；无运行模型包脚本。
- 计算：真实模型子进程、冷/热/并发与超时退出；UI 的小型模拟下载和数值 fixture 单独用于交互测试，不算真实模型测量。
- UI：实际 Qt 点击打开设置中的模型库，键盘切语言，点击下载/测速/保存，重启恢复；360、600、800、1180、1440px 几何检查，字体显式加载。真实本地 Melo TTS 已从实际按钮运行并保存候选，见 `desktop/real-tts-melo-zhen-onnx.json`。
- 截图：`desktop/model-library-{light,dark}-{360,800,1440}.png`；离屏截图可检查布局，不作真实听感或出声证据。
- wheel：目录 JSON、QML 组件及 Python 适配器随包分发；安装到临时目录后使用 `scripts/check_wheel_resources.py` 加载 QML。
- 开发命令和可重跑的 UI 探针见[本地语音指南](../../desktop/LOCAL_SPEECH.md)。

最终针对本轮的 **33 项测试通过**，Ruff 检查与格式检查通过，临时安装 wheel 的 **41 项资源**与 QML 加载检查通过。本轮较早的全量检查为 231 passed / 1 skipped；随后仓库同期其他修改使领域/准备与旧选题控件等测试失败，全量回归未完成并已停止本轮启动的测试进程，因此**最终全量不记通过**。单独复核旧桌面测试可重现 `selectTopic2` 缺失；本轮没有修改该材料页或领域逻辑以绕过失败。

## 下一阶段门槛

当前 CPU 路线上，STT 有可用的低计算延迟候选；Kokoro/Melo 不能默认用于一秒实时目标，Piper 类轻量声音值得继续固定与验证。日语 TTS 未完成，不以其他语言测试代替。

下一阶段先确定可分发的具体声音，测真人学习者口音与音质，再接长期预热 worker、VAD/AEC、流式文本分句、播放代际/取消及 LiveKit。逐段记录真实停顿到 ASR final、LLM 首个可说短句、首 PCM 和实际出声，检查并发、热降频与长时间队列。只有端到端真人多轮数据才能说明一秒目标是否接近；当前不自动切换云端或上传录音。

## 侧聊关闭后的恢复检查（2026-10-28）

用户要求从文件恢复原计划与原有进度，再继续本地 STT/TTS 测试。本节依据仓库代码、现存模型和原始报告恢复断点；上文保留此前的测试结果与失败记录。

### 原计划与文件入口

原来明确交付的两阶段是：先做固定模型目录、硬件检测和计算测速，再做桌面模型库的下载管理、语言/用途筛选、试听和候选保存。依据是 [MVP Spec](../../product/MVP_SPEC.md) 末段、[Decision 0017](../../decisions/TECH_DECISIONS.md#decision-0017-可选本地语音目录实测准入与独立推理进程)及[本地语音指南](../../desktop/LOCAL_SPEECH.md)。真人质量和连续语音属于这两阶段之后的剩余门槛，没有在此前交付中记为完成。

| 文件 / 目录 | 用途 |
|---|---|
| `src/shinar/local_speech/catalog.json`、`catalog.py` | 固定模型包、语言、来源、许可说明、哈希和候选列表 |
| `src/shinar/local_speech/downloads.py`、`storage.py`、`hardware.py` | 下载/校验/安全展开、缓存与锁、硬件准入 |
| `src/shinar/local_speech/benchmark.py`、`runtime_worker.py`、`library.py`、`__main__.py` | 子进程推理、冷/热/并发测速、报告匹配、CLI |
| `src/shinar/desktop/speech_library/viewmodel.py`、`src/shinar/desktop/qml/components/LocalSpeechLibrary.qml` | 桌面模型库、任务进度、试听和候选保存 |
| `tests/local_speech/`、`tests/desktop/test_local_speech_desktop.py` | 本地模型库与 Qt 交互回归 |
| `tests/providers/test_speech.py`、`src/shinar/providers/speech.py` | 原有独立云端 STT/TTS adapter 及其 mock 测试，不是本地模型接线 |
| `scripts/validate_local_speech_desktop.py` | 可重跑的离屏 Qt 操作与截图探针 |
| `build/local-speech-evaluation/cache/models/`、`cache/reports/` | 已下载模型、原始测速 JSON 与 TTS 样本；ignored，不提交 |
| `build/local-speech-evaluation/desktop/` | 明暗/窄窗口截图、UI 报告与独立测试库 |
| `build/local-speech-evaluation/runtime/`、`install-smoke/`、`piper-evaluation-manifest.json` | 独立推理环境、wheel 安装验证环境及未公开的 Piper 评估包说明 |

### 已恢复的进度

- **已完成并有证据**：两阶段模型库功能；SenseVoice、Zipformer、Kokoro 和 Melo 的本机 CPU 计算测速；中英配对与日语 SenseVoice 单模型报告；Melo 从 Qt 按钮触发真实本地推理及保存候选。全部为 CPU，每模型 2 线程；RTX 4060 只被检测，没有 GPU 测试结果。
- **本次复核通过**：上述四个可下载模型的安装文件校验均为 `true`；报告中的四个模型指纹与当前目录匹配。现存推理环境与模型没有因关闭侧聊而丢失。
- **数值口径**：上表日语 SenseVoice 的 226ms 来自 19:50 的 5 次热态报告；最后一份 19:53 的 wheel 安装复测是 3 次，p95 约 229ms。两份原始报告都保留，不将不同次数的结果覆盖或混为一份。`cache/reports/zipformer-small-zhen-20230216--en.json` 仍有早期 2.0.1 记录；当前推荐代码按运行时版本过滤，不能拿它代替 1.13.8 实测。
- **尚未完成**：日语 TTS 的具体包/声音/前端与许可固定；Piper 类低延迟声音的公开目录准入；真人口音识别准确率与听感；本地 provider 接入长期预热 worker；真实 VAD/AEC、RTC、播放与打断、多轮连续语音。现有报告均未验收准确率或完整链路。
- **主要性能断点**：现有 STT 有低计算延迟候选；Kokoro/Melo 的 TTS 首 PCM 约 0.8–3 秒，不能据此满足一秒完整链路。英语 Piper 技术评估约 100ms，但没有完成具体声音的再分发审核，也不能替代日语 TTS。

### 本次离线验证

显式设置 `RUN_REAL_AI_TESTS=0` 后执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/local_speech tests/desktop/test_local_speech_desktop.py tests/providers/test_speech.py -q
.venv/Scripts/ruff.exe check src/shinar/local_speech src/shinar/desktop/speech_library/viewmodel.py tests/local_speech tests/desktop/test_local_speech_desktop.py tests/providers/test_speech.py scripts/validate_local_speech_desktop.py
```

结果为 **43 passed，17.52 秒**，Ruff 通过。其中 provider 测试为 mock；Qt 测试为离屏交互。本次只核对已有真实推理报告及模型完整性，没有新增真实识别、合成或真人录音证据。上轮全量回归未完成的状态仍保留，本次未重跑整仓，不能用这 43 项代替整仓通过。

### 续做顺序

1. 固定日语 TTS 的具体包、声音、前端、字典和条款，同时核对低延迟英语 Piper 声音的准入条件；候选身份与已可下载包继续区分。
2. 先对新增候选复用现有隔离环境，补冷加载、首次推理、热态及 STT/TTS 并发报告，再测独立真人样本的识别准确率与人工听感；不使用 TTS 自产语音充当真人准确率证据。
3. 有可用组合后接长期预热 worker 和分句/取消，再继续处理已有 LiveKit RTC 未通过的问题，最后测真实端点等待、出声及打断。模型单项计算通过不解除 RTC 和真人多轮验收门槛。

本次恢复只追加本记录，未修改运行代码、个人配置或正常学习数据库。

## 后续严格评测（2026-10-29）

用户随后授权中英日逐模型严格测试，客观阶段已完成；新增数据、Zipformer decoder 修正、原版/WSYue 检查点对照、GPU 结果和未验收听感见[严格评测阶段报告](./LOCAL_SPEECH_STRICT_EVALUATION_2026-10-28.md)。本页此前的数字与“未测”状态保留为对应历史阶段，不代表后续报告的进度。
