# SenseVoice GPU、日语 STT 与 Melo 独立英文补测（2026-10-29）

状态：全部完成。32 个主实验配置，STT 2100 次、TTS 720 次热态；另补 60 次 EN-Newest GPU 背景负载复测。两个 ASR 裁判回识 180 条合成音共 360 次，默认英语否定句追加 20 次回识。793 条新生成 cold / warm WAV 的格式、时长和 SHA256 全部复核。原始进度保存在 `build/local-speech-evaluation/strict/followup-2026-10-29/plan.json` 和各 run 的 `status.json`。本记录承接[此前选型](./LOCAL_SPEECH_SELECTION_2026-10-29.md)，旧测试与用户试听意见继续保留。

## 当前结论

- SenseVoice 2024 **FP32 GPU** 是本轮速度最好的配置，中 / 英 / 日平均首字分别为 **52.5 / 54.6 / 58.1ms**；对应中文 CER 11.44%、英语 WER 8.13%、日语 CER 8.63%。同适配器 FP32 CPU 平均 520.8 / 505.3 / 713.9ms，严格按门槛淘汰这三个 CPU 配置。
- SenseVoice 两个 INT8 版本的 GPU 配置均通过平均 500ms 的速度线，但未优于本次同运行时 CPU 对照。2025 的英语 WER 29.81%、日语 CER 77.20%，英语继续作为受限备选，日语因识别质量不作可用候选；中文仍可保留。2024 / 2025 是具体 checkpoint 的区分，不将“新年份”当作质量保证。
- 日语新增 **ReazonSpeech k2 v2 INT8 CPU** 和 **Kotoba Whisper v2 FP16 GPU**，都通过速度线：前者平均 322.8ms、CER 9.11%，后者平均 345.6ms、CER 6.80%。允许按语言和设备分别选择，不要求一个模型覆盖所有语言。
- Melo 独立英文 EN 五种口音及 `EN_NEWEST` / v3 的 CPU / GPU 均已测完：主实验 GPU 平均首 PCM 123.9–176.6ms、CPU 2589.99–3643.95ms。美式原波形前导较长，GPU 理论首声平均约 666ms；EN-Newest 的额外 GPU 复测平均 434ms、最慢 3.61s。两轮对应音频完全相同而耗时变化，说明必须保留共享硬件环境和慢尾，不只取快值。新音色听感仍待用户试听，Lessac 继续作为英语优先候选。

## 测量口径

本机 Windows AMD64、i9-14900HX（32 逻辑核）、约 31.8GiB RAM、RTX 4060 Laptop GPU（8188MiB）。每个评测进程 2 CPU 线程，模型推理串行执行，没有让不同模型同时抢占资源；其他用户应用继续运行，因此资源数字代表本机当时环境。

STT 沿用此前固定的每语言 50 段 Google FLEURS 公开真人录音，固定 revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`，完整 16kHz 单声道 PCM16，不裁去静音。中文 535.52s、英语 474.96s、日语 653.10s。输入和模型 SHA256 在计时前校验。SenseVoice GPU 与新增日语模型各 3 次热态重复；同适配器 CPU 对照各 1 次，样本量在表中注明。冷模型加载与第一次推理另测，不进入热态均值；没有清空系统文件缓存，因此“冷”指新进程 / 新模型实例。

**STT 首字从完整录音给齐开始计时**。SenseVoice、Reazon 返回整段识别；Kotoba 计首个非空 segment，完整转录另计。没有把录音本身、VAD、端点等待、RTC、播放或 GUI 算入；这些都是离线计算候选，不能据此承诺真人说完后 500ms 内必定显示。全量均值包含全部尝试，有缺失就不能用“只算成功”的均值通过。p95 用最近秩法，不以中位数替代用户要求的平均值。

准确率只用每条录音的 repeat 0，50 条重复计时不会扩大准确率语料。中文 / 日语报字符错误率 CER，英语报词错误率 WER，均越低越好。主评分忽略大小写、标点和空白，保留真实错词、漏词与多词；不使用 LLM 润色识别输出。英语数字的辅助格式复核仍见[此前记录](./SENSEVOICE_2025_FORMAT_AUDIT_2026-10-29.md)，不以格式复核替代主 WER。

TTS 采用相同的 12 条英语文本，每个声音 / 设备 5 次热态重复，冷推理另留。完整文本、否定词、数字、日期、人名及长句全部保留。Melo 官方 Python 算法返回整条波形，因此本次首 PCM 等于整条合成计算时间；没有借用旧 sherpa 分块回调的首音值。每一次 cold / warm 都保存独立 WAV 与 SHA256，附件取 repeat 0，原始响度保留，不做峰值归一化。

## SenseVoice：真实 GPU 执行与精度差别

本轮使用 ONNX Runtime GPU 1.23.2、kaldi-native-fbank 1.22.3，按模型 metadata 实现相同的 fbank、LFR、CMVN 和 CTC 解码；语言固定、ITN 关闭，前处理计入计时。它与此前 sherpa CPU 路径属于**不同适配器 / 运行时配置**，因此增加同适配器 CPU 对照，不拿旧 CPU 数字直接计算 GPU 加速比。有限精度可能改变 INT8 的 argmax 与少量识别文本，CPU / GPU 的逐条差异另列。

CUDA provider 列表之外，每个 SenseVoice GPU 语言配置都单独执行一次 ORT kernel profiling，保留完整 trace 和摘要；正式计时关闭 profiling，避免追踪开销混入。INT8 日语证明中 2024 / 2025 分别有 281 / 279 个 `MatMulInteger` 节点在 CPU、140 个 `MatMul` 在 CUDA，还产生大量跨设备拷贝；这些结果明确称为 CPU / GPU 混合执行。2024 FP32 的 421 个 `MatMul` 在 CUDA，CPU 仍负责部分形状处理与前端，不声称整个程序全部运行在 GPU。节点计数与累加时间不当作 GPU 利用率。

2024 FP32 原始 ONNX 约 894.2MiB，INT8 约 228.2MiB；2025 目录未发布对应 FP32 ONNX，本轮仅测试其实际 INT8 图，没有把反量化权重冒充原始 FP32。

| 模型 / 语言 | 设备 | 平均 / p95 / 最慢 ms | CER / WER | 冷加载 / 首次首字 ms | 热态 n | 速度筛选 |
| --- | --- | --- | --- | --- | --- | --- |
| kotoba-whisper-v2-float16-cuda / ja | cuda | 345.6 / 435.9 / 485.1 | 6.80% | 4188 / 552 | 150 | 通过 |
| reazonspeech-k2-v2-int8-cpu / ja | cpu | 322.8 / 545.7 / 982.5 | 9.11% | 2029 / 334 | 150 | 通过 |
| sensevoice-2024-fp32-ort-cpu / en | cpu | 505.3 / 842.5 / 933.8 | 8.13% | 1789 / 504 | 50 | 淘汰 |
| sensevoice-2024-fp32-ort-cpu / ja | cpu | 713.9 / 1109.5 / 1259.6 | 8.63% | 2140 / 890 | 50 | 淘汰 |
| sensevoice-2024-fp32-ort-cpu / zh | cpu | 520.8 / 873.3 / 1010.1 | 11.44% | 2212 / 322 | 50 | 淘汰 |
| sensevoice-2024-fp32-ort-cuda / en | cuda | 54.6 / 73.8 / 88.2 | 8.13% | 2215 / 228 | 150 | 通过 |
| sensevoice-2024-fp32-ort-cuda / ja | cuda | 58.1 / 75.9 / 90.7 | 8.63% | 2346 / 262 | 150 | 通过 |
| sensevoice-2024-fp32-ort-cuda / zh | cuda | 52.5 / 62.7 / 66.1 | 11.44% | 2108 / 187 | 150 | 通过 |
| sensevoice-2024-int8-ort-cpu / en | cpu | 207.7 / 344.8 / 410.9 | 8.79% | 1211 / 223 | 50 | 通过 |
| sensevoice-2024-int8-ort-cpu / ja | cpu | 295.6 / 461.0 / 505.4 | 8.63% | 1351 / 369 | 50 | 通过 |
| sensevoice-2024-int8-ort-cpu / zh | cpu | 240.5 / 396.1 / 428.5 | 11.21% | 1177 / 131 | 50 | 通过 |
| sensevoice-2024-int8-ort-cuda / en | cuda | 262.6 / 400.2 / 570.8 | 7.94% | 1830 / 380 | 150 | 通过 |
| sensevoice-2024-int8-ort-cuda / ja | cuda | 295.7 / 399.0 / 440.5 | 8.79% | 1808 / 466 | 150 | 通过 |
| sensevoice-2024-int8-ort-cuda / zh | cuda | 273.2 / 390.1 / 463.0 | 11.27% | 3224 / 407 | 150 | 通过 |
| sensevoice-2025-int8-ort-cpu / en | cpu | 212.5 / 332.9 / 458.4 | 28.88% | 1508 / 407 | 50 | 通过 |
| sensevoice-2025-int8-ort-cpu / ja | cpu | 300.3 / 447.9 / 598.4 | 77.12% | 1261 / 322 | 50 | 通过 |
| sensevoice-2025-int8-ort-cpu / zh | cpu | 229.8 / 389.7 / 442.5 | 11.50% | 1198 / 133 | 50 | 通过 |
| sensevoice-2025-int8-ort-cuda / en | cuda | 240.7 / 339.2 / 410.9 | 29.81% | 2173 / 529 | 150 | 通过 |
| sensevoice-2025-int8-ort-cuda / ja | cuda | 299.1 / 405.1 / 553.9 | 77.20% | 1816 / 504 | 150 | 通过 |
| sensevoice-2025-int8-ort-cuda / zh | cuda | 277.4 / 409.4 / 450.1 | 11.50% | 2185 / 362 | 150 | 通过 |

本轮新 ORT CPU 的 2024 INT8 三语对照均过线，中 / 英 / 日为 240.5 / 207.7 / 295.6ms，日语 CER 8.63%、进程 RAM 451MiB；它与旧 sherpa CPU 后端不同，可保留为 CPU 实验候选，不能覆盖旧日语 599.3ms 的失败配置。对照只做 50×1，重复稳定性证据弱于 50×3 的主实验。

同精度配对的完整 CPU / GPU 均值、50 条中输出变化数及其输入 ID 在附件 `paired-controls.json`。CPU 对照仅 50×1，GPU 为 50×3，报告不隐去这一重复次数差异。

## 日语新候选

| 配置 | 平均首字 / p95 / 最慢 | CER | 实际加载权重 | 进程峰值 RAM | 新进程加载 / 首次首字 |
| --- | --- | --- | --- | --- | --- |
| ReazonSpeech k2 v2 INT8 CPU | 322.8 / 545.7 / 982.5ms | 9.11% | 约 161.3MiB | 575MiB | 2029 / 334ms |
| Kotoba Whisper v2 FP16 GPU | 345.6 / 435.9 / 485.1ms | 6.80% | 约 1442.8MiB | 1822MiB | 4188 / 552ms |
| SenseVoice 2024 FP32 GPU | 58.1 / 75.9 / 90.7ms | 8.63% | 约 894.2MiB | 1339MiB | 见完整表与原始报告 |

以上每项 50 条×3 次，共 150 次热态，均无缺失首字。Reazon 适合 CPU / 较低内存方案；Kotoba 在本批日语朗读上更准，付出更大的权重、进程内存和 GPU 占用；SenseVoice 2024 FP32 GPU 优先满足低计算延迟。平均过线仍保留 p95 和最慢值，例如 Reazon 的 p95 已超过 500ms，不能表述为“所有请求都在 500ms 内”。

Reazon 为 159.34M 参数、日语专用离线 RNN-T，实际配置为 INT8 encoder / joiner + FP32 decoder、greedy search；官方说明支持约 30s 以下片段，本批日语最长约 20.76s。Kotoba 为日语专用 faster-whisper / CTranslate2 FP16，beam 1、不启用 VAD、不继承前文；报告保留设备为 CUDA 与实际 `float16` 的证据。来源与许可：[Reazon 官方模型卡](https://huggingface.co/reazon-research/reazonspeech-k2-v2)、[Reazon 官方发布说明](https://research.reazon.jp/blog/2024-08-01-ReazonSpeech.html)、[Kotoba 官方模型卡](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0-faster)。

这些是同一公开朗读集的候选筛选，尚未覆盖学习者口音、短应答、噪声麦克风和实际端点。固定输入的原始录音、标准文本与逐模型输出会一起附上，不能只挑最好的一句。

## Melo 独立英文

官方 `MeloTTS-English` checkpoint 的美式 `EN-US`、英式 `EN-BR`、印度 `EN_INDIA`、澳洲 `EN-AU`、默认 `EN-Default` 全部测试 CPU 与 GPU；另测 `MeloTTS-English-v3` 的 `EN-Newest`。不同版本和声音分别列出。独立 EN 声学权重约 198.2MiB，共享 BERT 权重约 420.0MiB；多声音共享声学 checkpoint，不乘以声音数量。

固定 Melo 官方源码 revision `209145371cff8fc3bd60d7be902ea69cbdb7965a`，使用官方结构与原始 checkpoint。为避免英文初始化时顺带下载日语 / 中文前端，评测只抽出官方英文前端，保留原 G2P、规范化、BERT 第 -3 层、blank 插入和 50ms 片段间静音；只修改本地 BERT 路径及与无关日语模块耦合的 import，差异与源文件 SHA256 有清单。Torch 2.9.1+cu128 / Transformers 4.57.3，GPU 声学模型与 BERT 均验证在 `cuda:0`，同步后计时。没有改权重、关 BERT、调速或改写测试句来制造好结果。

| 声音 / 设备 | 平均首 PCM / p95 ms | 短句平均 ms | 理论首声平均 / p95 ms | 新进程加载 / 首次首 PCM ms | 字 / 计算秒 · 播报字 / 秒 | 进程 RAM MiB · CPU均值 |
| --- | --- | --- | --- | --- | --- | --- |
| EN-AU / cpu | 2914.3 / 5667.6 | 1230.7 | 3009.6 / 5755.8 | 35188 / 4773 | 21.8 · 12.3 | 2615 · 37% |
| EN-AU / cuda | 140.1 / 231.5 | 110.1 | 236.6 / 328.6 | 10973 / 1620 | 453.3 · 12.3 | 2257 · 24% |
| EN-BR / cpu | 3644.0 / 7873.7 | 836.9 | 3793.5 / 8051.7 | 11185 / 1154 | 17.4 · 13.8 | 2464 · 40% |
| EN-BR / cuda | 123.9 / 206.4 | 102.9 | 276.9 / 332.1 | 15185 / 1626 | 512.3 · 13.8 | 2258 · 30% |
| EN-Default / cpu | 2612.0 / 5472.8 | 608.0 | 2682.9 / 5537.8 | 9196 / 843 | 24.3 · 14.7 | 2441 · 30% |
| EN-Default / cuda | 124.1 / 210.5 | 98.8 | 196.2 / 274.4 | 10796 / 541 | 511.9 · 14.7 | 2257 · 21% |
| EN-US / cpu | 3404.8 / 7526.9 | 1123.9 | 3893.0 / 7994.3 | 13053 / 1753 | 18.6 · 12.0 | 2572 · 25% |
| EN-US / cuda | 176.6 / 288.3 | 128.0 | 665.6 / 779.3 | 12295 / 626 | 359.5 · 12.0 | 2244 · 9% |
| EN_INDIA / cpu | 3106.8 / 6663.2 | 1062.4 | 3470.8 / 6836.9 | 12351 / 1540 | 20.4 · 12.9 | 2472 · 17% |
| EN_INDIA / cuda | 126.4 / 203.8 | 114.1 | 479.1 / 604.1 | 11640 / 1626 | 502.2 · 13.0 | 2237 · 24% |
| EN-Newest / cpu | 2590.0 / 6043.9 | 724.2 | 2725.0 / 6151.6 | 11174 / 1006 | 24.5 · 14.6 | 2456 · 34% |
| EN-Newest / cuda | 176.4 / 290.5 | 118.5 | 314.5 / 440.9 | 14512 / 2412 | 359.9 · 14.6 | 2171 · 17% |

首 PCM 不能直接当作听到第一词。本批独立 EN 美式 GPU 原波形平均约 489ms 低于 -50dBFS 的前导，177ms 返回整条音频后，立即播放到第一个超过该阈值的样点，理论平均约 666ms。英式 / 澳洲 / 默认声音该估算约 277 / 237 / 196ms。它是固定能量阈值的波形估算，不等于语义上的第一个单词，也没有包含设备和队列；没有裁掉静音后冒充原始速度。

首次建环境后的美式 smoke 新进程加载为 CPU 92.0s、GPU 62.3s，正式进程复用文件 / 编译缓存后明显缩短；这两次初始结果保留在附件 `initial-smoke-summary.json`，不隐藏最初成本，也不混进热态均值。



EN-Newest GPU 主实验整卡显存基线约 7020MiB，平均 / p95 / 最慢为 176.4 / 290.5 / 471.9ms。额外相同输入的 60 次复测为 **434.3 / 872.9 / 3605.1ms**，显存从约 2094MiB 升到 8097MiB（整卡总量 8188MiB）。60 组对应 WAV 的 SHA256 全部相同；两个结果都保留，不用复测替换主表，也不把差异单独归因于显存。实际背景 GPU 任务未隔离，模型之间的数值不是完全隔离硬件排名；常驻 / 并发和长期稳定性仍需产品路径验收。完整双轮资源与音频另附 `gpu-background-recheck.json`。

原版 `EN-Default` GPU 的否定句 repeat 0 被两个裁判识为 `was irresponsible` / `was unresponsible`，而原文是 `wasn't responsible`；这是词形偏离，**不能直接断定语义反转或 TTS 确实读错**。追加检查五次留存录音：GPU 其余 4 次、CPU 全部 5 次都被两裁判逐词回识一致。附件保留十条原始 WAV 及输出，单独提供试听；在用户听清前不把这个默认声音推荐为新的英语默认。

两个裁判对完整 12 条文本的主 WER 如下，不能当发音错误率或听感分数：

| 英语合成样本 | SenseVoice 2024 FP32 | Whisper Small INT8 |
| --- | --- | --- |
| 既有 Lessac | 2.44% | 9.76% |
| 既有 Amy | 1.83% | 9.76% |
| 既有 Melo 中英包 | 22.56% | 30.49% |
| 独立 Melo 美式 GPU | 7.93% | 12.80% |
| 独立 Melo 英式 GPU | 10.37% | 10.37% |
| 独立 Melo 默认 GPU | 10.37% | 10.37% |
| Melo EN-Newest GPU | 9.15% | 9.15% |

Amy 的低总 WER 仍包含已由用户确认的否定词语义错误，说明总分不能替代逐句检查。新独立 Melo 的回识优于旧中英包，但这不足以宣布口音或自然度已通过。全 15 组合成来源、两个裁判的逐条与汇总 CSV 都在附件，包含全部 CPU / GPU 声音；去数字 / 日期的十文本探索值单列，不替代 12 条主结果。


听感不自动给分；两个 ASR 裁判的回识用于发现疑似漏词、重复与数字问题，包含裁判自身错误，不能作为发音准确率或 MOS。独立英文与旧 Melo 中英包、Lessac、Amy 的同句 WAV 并列，否定词样本单独可选。旧 Amy 的 L054 用户已确认语义反转，仍保留该历史意见；新回识不能推翻人耳确认。来源：[Melo 官方仓库](https://github.com/myshell-ai/MeloTTS)、[独立英语 EN](https://huggingface.co/myshell-ai/MeloTTS-English)、[EN_NEWEST / v3](https://huggingface.co/myshell-ai/MeloTTS-English-v3)。

## 资源、环境与复现

进程 RAM 使用 Windows `peak_wset`，含 Python、推理引擎、前端和模型，不能从下载大小推算。CPU 均值来自推理区间进程 CPU time / wall time，包含计分及 WAV 写入，**100% = 一个逻辑核**，并非整台 32 核机器占满。每 100ms 另采样 RSS / CPU / NVML。

GPU 显存与利用率为整卡，含桌面和其他应用；表内提供进程启动前采样基线与峰值，差值也不能保证全归因于模型。Melo 的 Torch allocated / reserved 峰值单列，仅为本进程张量 / 缓存，不包含全部驱动上下文。SenseVoice 用真实 CUDA kernel trace 证明算子放置，不能拿 NVML 整卡利用率代替。所有逐次资源采样和完整 ORT trace 保存在原 run 目录，附件同时包含原件与摘要。

GPU STT 隔离环境：Python 3.12.13、ORT GPU 1.23.2、sherpa-onnx 1.13.8+cuda12.cudnn9、faster-whisper 1.2.1、CTranslate2 4.8.4。faster-whisper 依赖曾安装同名 CPU `onnxruntime`，已在正式测试前移除并恢复 GPU wheel；CPU-only 不可冒充 GPU。CUDA DLL 复用已安装 Torch 的 `lib` 目录，只用 DLL，不加载或重测 Qwen。参考：[sherpa 官方 GPU 安装](https://k2-fsa.github.io/sherpa/onnx/python/install.html)、[ORT CUDA provider 官方文档](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)。

当前机器可在项目根目录复用已完成的原 run；脚本会校验请求与冻结源码，源码变化时要求新 run 名称，避免改写旧证据。执行顺序必须串行：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe build/local-speech-evaluation/strict/followup-2026-10-29/run_suite.py build/local-speech-evaluation/strict/followup-2026-10-29/asr-jobs.json --run asr-full
.venv/Scripts/python.exe build/local-speech-evaluation/strict/followup-2026-10-29/run_remaining.py
.venv/Scripts/python.exe build/local-speech-evaluation/strict/followup-2026-10-29/report_followup.py
```

命令复用校验通过的已完成推理，不强制重跑。权重固定 revision、原始 URL、大小与 SHA256 在 asset manifest / request 中；ZIP 不包含权重和运行时，移机须安装对应环境并调整绝对路径。不会读取正常学习数据库、修改个人 `.env`、切换应用模型或重启用户应用。

## 附件与剩余验收

- [离线报告与试听 HTML](../../../build/local-speech-evaluation/strict/followup-2026-10-29/attachment/index.html)：按文本比较六种独立英语声音与三个历史参考，选择中 / 英 / 日任意公开录音查看逐模型输出；默认否定句追加诊断可展开。
- [完整 ZIP](../../../build/local-speech-evaluation/strict/followup-2026-10-29/speech-gpu-ja-melo-2026-10-29.zip)：约 95.8MiB，解压后打开 index.html；不包含模型权重或运行时。
- [完整指标 CSV](../../../build/local-speech-evaluation/strict/followup-2026-10-29/attachment/metrics.csv)、[逐条 STT CSV](../../../build/local-speech-evaluation/strict/followup-2026-10-29/attachment/stt-records.csv)、[双裁判回识汇总](../../../build/local-speech-evaluation/strict/followup-2026-10-29/attachment/tts-roundtrip-summary.csv)。

附件包含 150 条公开真人输入 WAV、180 条主试听 WAV、12 条 GPU 复测 WAV、10 条默认否定句诊断 WAV，共 352 个音频文件。主试听取每配置 repeat 0；诊断明确包含 repeat 1–4，不伪称所有重复都已进入主试听。原目录保留并复核全部 793 条新 WAV，两个 ASR 裁判主回识共 360 条，追加否定句回识 20 条。每个正式报告的请求 / 样本对、冻结源码 SHA、真实 CUDA trace、全量资源采样和 ZIP 内每个文件 SHA256 均校验通过；没有进行人工 MOS 或真实麦克风 / RTC 验收。生成脚本通过 Ruff；浏览器实际切换语言、设备和文本，验证 20 个当前音频元素均可解码、无媒体或控制台错误，属于附件 UI 验证，不是实机出声或人耳听评。

公开输入为 Google FLEURS / CC BY 4.0；固定 revision、原始与转换后哈希随请求保留。模型源码 / 英文前端及 MIT 许可、固定 checkpoint / BERT 来源、复现脚本随附件保存。ZIP 使用明确文件清单打包，不递归收进用户以后在该目录解压的副本。


保留原有[模型资源与试听包](./LOCAL_SPEECH_MODEL_CATALOG_2026-10-29.md)；本补测是新配置证据，不覆盖旧文件。产品仍需实际语言切换、常驻预热、端点到可见文本、播放设备首音与连续性、STT / TTS 共同驻留与并发、真人学习者录音验收。尚未将这些评测 adapter 接入对话 provider，不把本次结果写成连续语音已交付。
