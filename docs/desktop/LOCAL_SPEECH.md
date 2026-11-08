# 本地语音模型与计算加速

2026-10-30：设置闭环增量已接入 VOICEVOX／独立 Melo 英文的普通模型与声音入口、分类型环境及 RTC 依赖准备；实际使用与未完成的验收见[设置闭环指南](LOCAL_SPEECH_SETUP.md)。下文保留此前选型与测量背景，不从旧状态表推断新流程已验收。

2026-10-29 基础 Python 增量：无 UI 服务已支持转写确认、双角色对话复用、分句合成、冻结 profile 和真实 RTC WAV/PCM；VOICEVOX/独立 Melo 英文可显式注册已准备环境，尚未扩展 GUI 下载目录。见 [Python 指南](./VOICE_PYTHON.md)和[基础验收](../validation/speech/VOICE_PYTHON_INTEGRATION_2026-10-29.md)。

当前包含模型目录、独立进程测速、下载管理，以及两个设置子页：“语音模型”和“计算与加速”。支持的本地适配器已接入桌面分轮录音/朗读；选用对话模型会启用对应本地服务，关闭本地识别/合成开关可使用已配置的远程连接。LiveKit 连续语音仍待验收。

逐模型的真人语料准确率、首文本/首 PCM、字速及听评资料另见[严格评测记录](../validation/speech/LOCAL_SPEECH_STRICT_EVALUATION_2026-10-28.md)。严格评测已发现具体 checkpoint 和前端配置会显著影响结果：2025 SenseVoice 包的 metadata 指向 WSYue 粤语微调来源，不能用它的速度或非空输出推断原版多语种 SenseVoice 的质量。产品模型库中的初步计算推荐仍只代表计算预算，不代表准确率或听感通过。

2026-10-29 用户选型见[筛选与试听结论](../validation/speech/LOCAL_SPEECH_SELECTION_2026-10-29.md)：此前 CPU 批次以热态首字算术平均 ≤500ms 筛 STT，保留两个 SenseVoice 版本的中文/英语配置，当时日语暂缺；中文 TTS 保留 Melo、英语优先 Lessac、日语暂留 VOICEVOX，Amy 的 L054 否定词错误已由用户确认。Kokoro 和 Qwen 退出本轮候选，历史结果仍保留。新配置补测见下文；模型库的 STT 对话筛选已改为本机平均计算 ≤500 ms，识别准确率和听感仍取独立严格评测与用户反馈。

允许按语言分别安装与选择 STT/TTS；现有候选键为 `language:scenario:task`，无需一个模型覆盖所有语言。实际分轮语音按当前会话目标语言取模型，库内筛选语言不改变会话语言。模型首次使用加载，后续驻留复用；默认空闲 120 秒释放，可改为每次使用后释放。首次加载/首次计算明显慢于热态，暂未实现会话前自动预热。VOICEVOX 前表的 1703ms 是首次整句合成完成，首次首 PCM 为 346ms，模型已加载后的热态平均首 PCM 为 447ms；不能把完整合成时间当作每句话的首音等待。

后续[GPU、日语 STT 与独立 Melo 英文补测](../validation/speech/SPEECH_GPU_JAPANESE_MELO_FOLLOWUP_2026-10-29.md)已完成 STT：2024 SenseVoice FP32 GPU 三语平均首字 52–58ms；新增日语 ReazonSpeech CPU 平均 323ms、Kotoba GPU 平均 346ms，也过 500ms 线。此前“日语暂缺”指旧批次；新配置、运行时和准确率分别记录。其中 SenseVoice 2024 FP32 与 ReazonSpeech CPU 已进入产品目录与分轮语音；Kotoba、独立 Melo 英文和 VOICEVOX 的产品适配待完成，不把评测可运行写成产品可用。

用户提出 2025 SenseVoice 的大小写疑问后，已完成[格式复核](../validation/speech/SENSEVOICE_2025_FORMAT_AUDIT_2026-10-29.md)：主 WER 本来就忽略大小写，进一步数字/缩写等规范化后英文 WER 为 28.53%，原版为 6.23%；此辅助指标不替换主结果。2026-11-06 用户明确淘汰 2025 / WSYue 分支，现已从全部语言和用途的产品目录删除，不再保留备选；原版 2024 保留。旧选择需重新选用现有模型，历史评测和学习记录不改写。

## 使用

基础桌面端无需在 GUI 进程安装推理库。先在“设置 → 计算与加速”准备 CPU 或 GPU 环境，再到“语音模型”选择语言、下载并测速。对话用途的“选用模型”启用对应本地识别或合成。命令行旧测速可使用可选依赖：

```powershell
uv sync --dev --extra desktop --extra local-speech
uv run shinar-desktop
```

在“设置 → 语音模型”选择语言和用途。下载后可校验文件、测速、试听 TTS，并分别选用当前语言/用途的 STT 和 TTS。配对测速会将两个模型同时加载，并比较串行/同时运行时的计算耗时。识别测速需选择自己有权使用的 **16kHz、单声道、16-bit PCM WAV，最多 60 秒**；录音不复制、不上传，报告不保存识别文本。

本轮开发用独立的 `build/local-speech-evaluation/`，没有把模型、示例材料或报告写入正常学习数据库。需要查看本机已测目录时，单独启动开发实例：

```powershell
$env:SHINAR_DATA_DIR=(Join-Path $PWD 'build/local-speech-evaluation/desktop')
$env:SHINAR_SPEECH_DIR=(Join-Path $PWD 'build/local-speech-evaluation/cache')
$env:SHINAR_SPEECH_PYTHON=(Join-Path $PWD 'build/local-speech-evaluation/runtime/Scripts/python.exe')
uv run shinar-desktop --mock
```

这三个覆盖仅作用于当前终端；普通启动使用正常数据目录。测试不能伪装为用户历史。

## 目录与语言覆盖

具体包、版本、字节数、SHA256、文件路径、前端限制与来源位于 `src/shinar/local_speech/catalog.json`。候选家族与可下载的固定包明确区分。

| 模型 / 路径 | 本轮状态 | 已声明语言 | 增量能力 / 限制 |
|---|---|---|---|
| SenseVoice 2024 INT8（CPU） | 可下载、本机已测 | 中、英、日；日语优先 Reazon 或 FP32 GPU | 整段识别；VAD 分块另做；不是原生 partial |
| SenseVoice 原版 2024 FP32 / INT8，ORT GPU | FP32 可下载并用于分轮语音；INT8 保留评测 | 本轮中、英、日 | FP32 GPU 三语均值 52–58ms；INT8 混合执行、未显示加速优势 |
| Zipformer Small 2023-02-16 | 可下载、本机已测 | 中、英 | 原生增量 ASR；端点等待未测；模型包缺完整许可说明，现阶段仅技术评估 |
| Kokoro v1.1-zh INT8 | 本轮排除，默认列表隐藏 | 中、英 | 当前 sherpa 前端不支持日语；句子合成后回调 PCM |
| MeloTTS 中英 ONNX | 可下载、本机已测；仅保留中文用途 | 中文 | 英语已按用户试听结论移除；短句合成，不是增量文本流 |
| VOICEVOX CORE / Kokoro + misaki 日语 | 评测资产已固定，未开放产品下载 | 日 | 已测 ずんだもん style 3；Kokoro 分别比较 pyopenjtalk / Cutlet 前端，见严格报告 |
| Vosk Small 各语言包 | 已做三语公开真人录音评测，未开放产品下载 | 中、英、日及部分欧洲语言 | 原生 partial；每种语言独立包，准确率与首字另列 |
| Whisper Small + faster-whisper | 候选，未开放下载 | 中、英、日等 | 离线转录优先；窗口重识别不能直接当成流式 ASR |
| ReazonSpeech k2 v2 / Kotoba Whisper v2 | Reazon 可下载并接入分轮；Kotoba 待适配 | 日语 | CPU INT8 / GPU FP16 分别平均首字 323 / 346ms；端点、学习者口音未验收 |
| Melo 独立英文 EN / EN_NEWEST | 独立评测，未开放产品下载 | 英语 | 与现有中英 ONNX 包分别计时与试听，使用官方 Python / BERT 路径 |
| Piper 各声音 | Lessac medium 已开放个人下载与分轮，其余待适配 | 中、英及部分欧洲语言 | CPU 短句合成；声音的许可必须逐个核对 |
| Qwen3-ASR / Qwen3-TTS 0.6B | 独立 GPU 三语基线已完成，未开放产品下载 | 中、英、日等 | Windows BF16 / SDPA 实测整段 Python API；原生流式与并发仍未验收 |

来源：[SenseVoice](https://github.com/QwenAudio/SenseVoice)、[Zipformer](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html)、[Kokoro ONNX 前端](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html)、[Melo ONNX](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html)、[VOICEVOX](https://github.com/VOICEVOX/voicevox_core)、[Vosk](https://alphacephei.com/vosk/models)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[Piper](https://github.com/OHF-Voice/piper1-gpl)、[Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)、[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)。

引擎、权重、词典及声音不是同一许可证。目录显示条款和原始来源；本次没有把权重放入 wheel，也没有声称所有候选可以直接商用再分发。目录中的 SHA256 绑定本次从官方发布地址取得的字节，不代表作者签名或模型语义质量。

## 资源与下载

- 检测 CPU 架构、逻辑核心、当前可用 RAM、缓存盘空闲空间；NVIDIA 显存来自 `nvidia-smi`。自动模式对已验证明显提速的适配器优先 GPU；明确选择 GPU 时失败不静默改用 CPU。GPU 缺失、显存预留或预算不满足时自动模式考虑 CPU；CPU 结果需重新通过平均延迟筛选。测速记录实际设备，单模型最多四线程。
- 目录的进程预算是**测速准入策略**，不是推导出来的模型最低配置。另留 2GiB 给 GUI/系统；配对时累加两个模型预算。真实进程峰值另测。不能从下载大小推断运行内存。
- 下载使用 httpx、固定 HTTPS 地址、明确大小与 SHA256，支持 Range 续传；服务器忽略 Range 时重新开始，范围不匹配直接报错。混拼或损坏数据不会安装。
- 文件先进入内容寻址缓存，校验后在独立 staging 展开；拒绝路径穿越、链接、特殊文件、重复文件与超出展开上限的压缩包。完成清单后原子安装到 `models/<id>/<revision>`。旧版本目录保留，当前未提供跨版本切换 UI。
- 下载/校验/卸载/测速共用每模型跨进程锁；测速期间不删除在用文件。卸载只删除当前包及其下载缓存。崩溃后，相同模型下次安装会清理失去锁所有者的 staging。
- “取消”保留未完成下载；网络读有 30 秒超时，取消不会强制抢占一次阻塞网络读。测速子进程支持取消和硬截止，退出释放模型。

默认缓存是 Windows `%LOCALAPPDATA%/Shinar/speech`，或其他系统的用户 cache 目录；`SHINAR_DATA_DIR` 生效时使用其 `speech/` 子目录。可用 `SHINAR_SPEECH_DIR` 独立覆盖。数值报告在 `reports/`，选择在 `selections.json`；不进入学习数据库。

## 计算测速与链路边界

```powershell
uv run python -m shinar.local_speech hardware
uv run python -m shinar.local_speech list --language ja
uv run python -m shinar.local_speech install sensevoice-int8-20240717
uv run python -m shinar.local_speech benchmark sensevoice-int8-20240717 --language en --wav D:/audio/sample.wav
uv run python -m shinar.local_speech benchmark zipformer-small-zhen-20230216 melo-zhen-onnx --language zh --wav D:/audio/sample.wav
```

所有命令支持 `--root`。默认 2 线程、5 次热态，保留冷模型加载、首次推理、每次热态值、p50/p95、并发干扰与进程峰值 RAM。可用 `--threads 1–4` / `--repeats 3–20`。`SHINAR_SPEECH_PYTHON` 可指定有推理依赖的独立 Python；桌面进程不导入 sherpa/numpy，不下载运行时或执行模型包里的脚本。psutil 只用于硬件/内存测量，未安装时 Windows 硬件检测使用系统 API。

当前固定 sherpa-onnx **1.13.8**：2.0.1 实测不再处理旧 Piper 包的内置发音前端，升级必须先适配外部 phonemizer。报告绑定运行时版本，UI 推荐还限定 CPU、每模型 2 线程；其他线程数结果保留作研究，不混入默认策略。目录选中的候选同样绑定版本。

严格评测发现 Zipformer 包的 INT8 decoder 会大量漏字；同一批中文录音 CER 从全 INT8 的 79.32% 降为保留 FP32 decoder 的 17.50%。默认加载已改为 INT8 encoder/joiner + FP32 decoder，与官方文件识别示例一致。adapter revision 更新为 2，旧配置的测速、包含它的配对测速和已选候选失效，重新测速选择；权重和原始报告仍保留。英语该包的 WER 仍超过 70%，不能据中文改善宣称英语可用。

ASR 测试输入按 200ms 块送给 Zipformer，然后 flush，记录最后计算与首个 partial 对应的**音频位置**。这是离线计算模拟，不是麦克风真实时钟测量。SenseVoice 测整段运算，结束后再启动识别时，这部分会进入尾延迟。TTS 从已有短句到第一个非空 PCM 回调计时；这不等于扬声器出声，也不证明支持边接收 token 边合成。

STT 对话筛选为结束后计算算术平均 ≤500ms，p95 和慢轮保留展示；TTS 保留首 PCM p95 ≤300ms 的初步推荐预算，有并发记录时 TTS 取较慢值。超过预算的模型不会因“列表里最快”而成为实时候选推荐。这个预算是本项目的可调策略，不是厂商性能声明或一秒承诺。匹配包指纹、adapter 版本、语言、运行时、实际 CPU/GPU、GPU 编号与名称、CPU/架构/平台后才复用测量；更新权重或换机器后重新测。

**完整链路**还包含真实停顿/VAD、ASR final、LLM 首个可说短句、合成和播放排队、RTC、回声处理与打断。下一阶段需要逐段计时，测并发负载、真人口音和长时间稳定性；模型库内置计算测速报告仍标记 `live_chain_evaluated=false`、`accuracy_evaluated=false`，与独立严格语料评测是不同报告。不得把 RTF<1 或单项计算通过写成连续语音通过。

本机结果与剩余验收见[本地语音验收记录](../validation/speech/LOCAL_SPEECH_ACCEPTANCE_2026-10-28.md)。

离屏操作与截图可复现（不调用文本 AI、不读取正常学习库）：

```powershell
.venv/Scripts/python.exe scripts/validate_local_speech_desktop.py
# 已下载模型且已安装本地推理依赖时，实际点击运行 TTS 并保存候选：
.venv/Scripts/python.exe scripts/validate_local_speech_desktop.py --benchmark melo-zhen-onnx
```

截图与报告保存在 `build/local-speech-evaluation/desktop/`；真实本地推理报告与模拟 UI 测试分开记录。音质和真人语音需要另验，截图不作出声证明。


## 计算与加速设置

- STT、TTS 分别设置自动/CPU/NVIDIA CUDA。默认自动；SenseVoice 2024 FP32 已验证明显提速，优先 GPU，INT8 与 Piper 等当前适配使用 CPU。其他显卡后端尚未适配。
- 默认语音显存预算 3072 MiB，另外要求留出 1024 MiB 空闲显存给其他应用；已驻留 GPU 模型的准入估算会相加，不给每个模型重复分配整份预算。SenseVoice FP32 准入估算 1536 MiB。该预算作用于准入和 ORT 内存池，CUDA 上下文、库和驱动还会额外占用，不能承诺进程显存硬上限或 GPU 使用率百分比限流。
- 每 2 秒显示整卡显存和使用率，同时单列语音推理进程的显存；驱动不支持进程统计时显示未知，不用整卡差值冒充进程精确占用。没有推理时不会为监测加载模型。
- 模型默认驻留到空闲 120 秒；可立即释放或手动释放。配置变化请求释放空闲模型，运行中的推理先完成。常驻进程持有模型锁；测速/卸载前先释放。Windows 释放会结束自己的完整进程树，包含虚拟环境启动器的子进程。
- `compute.json` 保存设备、GPU 编号、预算、预留、空闲时长及本地服务开关；`selections.json` 继续按语言/场景/STT 或 TTS 保存模型。二者在语音缓存下，不写入学习数据库或个人 `.env`。设置下一次推理生效，已生成的音频不是新设备推理的测速证据。

GPU 用户需要 NVIDIA 驱动及匹配的推理运行库，通常不需要完整 CUDA Toolkit。准备按钮仅在语音缓存下建立独立 venv，从 PyPI 安装固定的 ORT GPU 1.23.2、CUDA 12.8、cuDNN 9.10 等运行库，不安装驱动、不修改系统 PATH，也不把 Torch 或推理库导入 GUI。下载可较大，按平台通常约 1–2 GiB；失败、取消可重新准备。只有实际矩阵乘法的 profiling 证明使用 CUDA kernel，才写入通过标记；看到显卡或列出 provider 不算通过。驱动变化后可点击重新检查。当前自动准备支持 Python 3.11–3.13 的非冻结桌面版；冻结发行包的 Python/runtime 分发仍待设计。

来源：[ORT CUDA 与预加载运行库官方说明](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)。高级本地验证可用 `SHINAR_CUDA_DLL_DIR` 指向已有匹配 DLL，句柄在子进程中保留；不将具体开发机路径写入应用配置。

本次设置与真实本地进程验证见 [CPU/GPU 设置接入记录](../validation/speech/LOCAL_SPEECH_COMPUTE_SETTINGS_2026-10-29.md)。CLI 复现示例（复用此前固定的公开评测资产与现有运行环境；不代表新下载流程已验证）：

```powershell
.venv/Scripts/python.exe scripts/validate_local_speech_acceleration.py --evaluation-root build/local-speech-evaluation --python build/local-speech-evaluation/strict/followup-2026-10-29/gpu-runtime/Scripts/python.exe --cpu-python build/local-speech-settings-validation/prepared-runtime/runtimes/cpu-v1/Scripts/python.exe --cuda-dll-dir build/local-speech-evaluation/strict/qwen-asr-runtime/Lib/site-packages/torch/lib
.venv/Scripts/python.exe scripts/validate_local_speech_desktop.py --root build/local-speech-settings-validation/ui
```

第二条命令生成模型和计算两页的浅/深主题、360/800/1440 宽截图，不访问正常学习库或真实文本模型。第一条需要先准备匹配的独立 CPU 环境；开发机本次已在 prepared-runtime 下准备完成。它只复用现有 CUDA DLL，不执行 Qwen 模型。
