# 本地 STT / TTS 严格评测阶段报告（2026-10-28 至 2026-10-29）

用户要求逐个评估已有模型及候选，中文、英语、日语都测；优先首字/首音频，其次字/s、识别准确率和听感。本轮不改个人 `.env`、不切换正常对话 provider，不使用正常学习库或付费语音服务。

原计划与关闭侧聊后的断点恢复见[阶段验收与恢复记录](./LOCAL_SPEECH_ACCEPTANCE_2026-10-28.md)。本轮客观评测于 10 月 29 日凌晨完成：**34 个模型/语言配置（21 个 STT、13 个 TTS），3506 次正式热态计时、350 次定速原生首字回放、312 次 TTS 双裁判回识**；保留 156 条固定首轮试听样本。模型/语言配置包含量化和前端对照，不是 34 个独立模型家族。

逐模型的适配语言、大小、内存/显存、运行时间与效果附件已另汇总为[资源与效果清单](./LOCAL_SPEECH_MODEL_CATALOG_2026-10-29.md)，包含可离线保存的报告、156 条音频和同源真人识别对照。

2026-10-29 用户已给本批样本定性试听反馈并收敛候选，见[速度筛选与用户试听结论](./LOCAL_SPEECH_SELECTION_2026-10-29.md)；Amy L054 否定词错误已由用户确认。以下客观阶段历史数据保留；用户意见不是多人 MOS，未决工作以最新筛选记录为准，Qwen 不再继续补测。

优先结论：CPU 短句首 PCM 以 Piper 具体声音最快，但 Amy 存在需要复听的否定词样本，不能按速度直接判质量通过；日语 VOICEVOX 是当前低延迟试听候选。原版 SenseVoice 2024 的多语种质量明显优于目录内 2025/WSYue 检查点。Zipformer decoder 选择已修复，英语仍不可据本批结果选为实时默认。Qwen 本机整段 TTS API 的热态首音仍需数秒至数十秒，原生流式路径未验证。**人工听感未评分，完整语音链路未验收。**

## 评测口径

- 模型与运行时：本机 i9-14900HX，CPU 基线每模型 2 线程；GPU 候选另列后端与显存，不混在同一 CPU 排名。记录模型包/资产 SHA256、依赖版本、冷模型加载、首次推理、热态逐条结果、p50/p95/最慢值与内存。冷模型加载不代表清空操作系统文件缓存后的冷启动。
- STT：使用 [Google FLEURS](https://huggingface.co/datasets/google/fleurs) 的公开真人朗读 test 子集，固定 revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`；每语言取压缩包顺序前 50 段 1–30 秒的完整音频，不按模型结果过滤，不截断。中文 535.52 秒，英语 474.96 秒，日语 653.10 秒；男女数分别 33/17、21/29、41/9。它是规模有限且性别不平衡的朗读子集，不是学习者口音或真实麦克风验收，也不是全量 FLEURS 榜单。
- 原始 FLEURS WAV 含 float32；使用 ffmpeg 转为 16kHz/mono/PCM16，不裁切、不变速，分别记录原始字节与转换后哈希。流式下载只读取所需压缩包前段，记录实际转移字节；不声称验证了完整压缩包哈希。语料按 CC-BY-4.0 保留来源和转写，保存在 ignored 评测目录。
- STT 准确率：中日 CER，英语同时给 CER/WER；NFKC + casefold，CER 保留字母/数字，去标点与空白；英文 WER 保留词内 apostrophe、标点作为词界。按全语料参考单位数微平均，空识别计删除，错误率可以超过 100%；不把 `1-CER` 包装成模型准确率。中文同时报告原始 CER 和固定 OpenCC 0.1.7 `t2s` 后的 CER，保留转换后的逐条对照。Whisper 的繁体输出会显著影响原始值。汉字/假名、阿拉伯数字/汉字数字不作语义等价替换；正字法差异须结合逐条结果解释。
- STT 延迟：主要任务每段 3 次热态，首次推理单列；Zipformer decoder 精度对照每段 1 次，不能把 n=50 写成 n=150。离线模型从完整音频已供给后计时；Whisper 记录首个非空 segment 和全部 segment 完成。原生流式模型用全部 50 段另做每 200ms 真实时钟供给，到首个非空文本即停；首字包含原录音静音和模型所需声学上下文。旧全 INT8 Zipformer 仅保留原 3 段定速诊断。partial 可能修改，未出现文本的录音单独计数；不以零填充。Zipformer 的 660ms 合成 flush padding 不是已测 VAD 端点等待。字/s 使用参考字符数/纯计算秒，错误输出也可能很快，必须结合 CER/WER 阅读。
- TTS：每语言 12 条自写文本，涵盖短应答、问题、长句、多句、否定、数字、日期、专名等，各 5 次热态；Cutlet 前端复核为 3 次。相同文本与随机顺序对照，首次推理单列；Qwen 进程随机种子 9321，保留采样导致的音频时长差异。首 PCM 是第一个非空音频回调，首个非零回调另存，不等于设备出声。合成字/s = 规范化文本字符数 / 完整合成耗时；播报字/s = 字符数 / 生成音频时长，两者分开。字符数和语言有关，不据此跨语言排名。
- 听感：输出同句匿名音频与 1–5 分自然度/清晰度/读音评分表，默认留空。削波、音量、前导低能量和 ASR 回识仅是客观辅助，不能替代人工听感；未收到有效评分时不填 MOS 或声称听感通过。此表不是完整的 [ITU-T P.808 主观实验](https://www.itu.int/rec/T-REC-P.808/en)。

本机仍有用户的正常软件与系统后台任务，本轮不停止它们；结果是本机实测，不声称实验室独占负载或跨机器可复现同一毫秒值。完整 RTC、VAD/AEC、麦克风、扬声器和真人打断仍另行验收。

线程数是推理配置策略，不是进程总线程数或 CPU affinity：设置 `OMP_NUM_THREADS=2` / `OPENBLAS_NUM_THREADS=2`，有接口的 sherpa、CTranslate2、ONNX Runtime、VOICEVOX 也显式设为 2；Vosk 没有同等的统一线程参数，其解码按引擎实现执行。GPU 的 Torch CPU 线程显式设为 2，不能据此推定 GPU 算力与 CPU 基线等价。

首字总体分位数将“在该录音窗口内始终没有文本”作为服务失败排在有限观测之后；按全部尝试数取最近秩。分位数落在失败部分时记为缺失，不伪造一个超时时间；成功样本的条件 p95 另外保留。比如 50 段中 3 段不出字，就不能报告有限的总体首字 p95。原始历史报告的条件分布仍保留，不覆盖原数据。

TTS 的合成与播报字速都以**请求文本字数**计算；漏读、重复或错读会使它偏离实际读出字速，需要结合回识和听评，不能单凭快就判断合格。日语专名如「日本橋」存在地域读法差异，未指定语境时不据单一预期读音自动扣分。

本批真人录音实际时长 min / p50 / p95 / max：中文 5.04 / 9.90 / 17.58 / 18.88 秒，英语 4.32 / 9.82 / 14.66 / 19.12 秒，日语 6.96 / 12.06 / 18.60 / 20.76 秒。未覆盖“嗯／yes”等 1–3 秒极短真人回答，也没有用 TTS 回识数据冒充这一类真人准确率。

## 已执行与发现

1. 已准备每语言 50 段真人录音与标准转写，完整性校验通过。
2. 原有四个可下载包及 Piper Lessac 评估包，10 个模型/语言任务均已完成首轮严格 CPU 复测，目录为 `build/local-speech-evaluation/strict/runs/cpu2-20261028-a/`。
3. 原有 2025 SenseVoice 包在本次日语子集上出现高错误率；ONNX metadata 的 `model_author` / `comment` / `url` 指向 ASLP-lab / WSYue-ASR 的粤语微调来源，而不是可以不加区分地外推性能的通用原版。依据：[WSYue 模型卡](https://huggingface.co/ASLP-lab/WSYue-ASR)。已额外固定 [2024 原版 SenseVoice ONNX](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17)，revision `2365baeacb507f821a0c8120fcee3d484dba7a07`，作相同语料对照；不删旧包失败结果，也不在本轮静默替换模型。
4. Vosk 中/英/日独立包、Whisper Small、Kokoro 日语前端的评估资产已下载。VOICEVOX 使用固定 core 0.17.1 / runtime 1.23.2 / VVM 0.17.0；用户已明确同意仅作本地评测并保留 `VOICEVOX:ずんだもん` 署名，style 3 已在 VVM metadata 确认为该角色的 normal streaming_talk。
5. VOICEVOX 官方自动下载器先出现 Windows pager Unicode panic，随后命中 GitHub API 限流；改用同一官方固定 release 的直接资产。Qwen 大文件在 Hugging Face 多次读超时，改从官方 Qwen ModelScope 来源按范围续传，并以固定 Hugging Face revision 的 LFS SHA256 校验权重，哈希不符不得安装。

## CPU 阶段结果

下表是当前固定子集上的微平均错误率；越低越好，不是厂商全量榜单。延迟明细与各类短句结果保存在本地聚合表。

| STT 具体包 / 配置 | 中文 CER | 英语 WER | 日语 CER |
|---|---:|---:|---:|
| SenseVoice 原版 2024 INT8 | 11.38% | 7.94% | 8.75% |
| 现有 SenseVoice 2025 / WSYue | 11.50% | 29.35% | 77.24% |
| Zipformer 全 INT8（旧配置） | 79.32% | 78.88% | 不支持 |
| Zipformer INT8 encoder/joiner + FP32 decoder | 17.50% | 74.21% | 不支持 |
| Zipformer 全 FP32 | 17.16% | 73.93% | 不支持 |
| Vosk Small 各语言独立包 | 22.53% | 25.61% | 27.22% |
| Whisper Small CPU INT8 / beam 1 | 23.40% 原始 / 14.10% t2s | 6.26% | 13.69% |

Zipformer 的 FP32 decoder 选择与[官方文件识别示例](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html)一致。本轮已修复默认工厂，adapter revision 由 1 更新到 2；旧测量、相关配对测量和已存候选不再复用，权重及原始报告保留。英文即使全 FP32 仍很差，不因中文修复而判定通过。

按真实时钟供给、从录音起点到原生首个非空文本的独立 50 段结果如下。它包含原录音静音与声学上下文；不能与“整段音频已给齐之后”的离线耗时直接按数值排名。

| 原生 STT / 语言 | 总体首字 p50 / p95 | 未出文本 / 50 |
|---|---:|---:|
| Vosk Small / zh | 2262 / 4921ms | 0 |
| Vosk Small / en | 1528 / 2628ms | 0 |
| Vosk Small / ja | 2887 / 10469ms | 1 |
| Zipformer FP32 decoder / zh | 2207 / 4608ms | 0 |
| Zipformer FP32 decoder / en | 无有限值 / 无有限值 | 26 |
| Zipformer 全 FP32 / zh | 2209 / 5009ms | 0 |
| Zipformer 全 FP32 / en | 7809ms / 无有限值 | 25 |

比如 Vosk 日语只看成功的 49 段时 p95 为 5651ms，加入 1 段未出字后按 50 次尝试取秩，变为 10469ms；两种口径都保留，正文优先呈现总体值。Zipformer 英语不能用成功片段中较快的条件首字掩盖大量无输出。

| CPU TTS / 语言 | 首 PCM p95，全部 12 文本 | 两条短应答 p95 | 合成字/s |
|---|---:|---:|---:|
| Piper Amy low / en | 347ms | 54ms | 421.4 |
| Piper Lessac medium / en | 522ms | 78ms | 253.6 |
| Piper Huayan medium / zh | 572ms | 104ms | 98.9 |
| VOICEVOX ずんだもん style 3 / ja | 765ms | 507ms | 6.5 |
| Melo / en | 2930ms | 893ms | 25.4 |
| Melo / zh | 1977ms | 944ms | 11.4 |
| Kokoro v1.1-zh / en | 8393ms | 1884ms | 16.3 |
| Kokoro v1.1-zh / zh | 4792ms | 2294ms | 4.2 |
| Kokoro v1.0 INT8 + misaki pyopenjtalk / ja | 51702ms | 11547ms | 1.4 |

表内数值只表示相应完整文本/短应答；先输出一段 PCM 不保证之后无等待。原始报告记录全部回调，聚合另给“零设备开销、收到首块立即播放”的理论缺口，不冒充实际播放实验。日语 Kokoro 的 Cutlet + UniDic-lite 已完成单独复核（12 文本 × 3），短应答首 PCM p95 9314ms、整体 p95 54539ms，仍很慢；不能外推到整个 Kokoro 家族。Cutlet 诊断批次中有约 19 秒针对性离线回归运行重叠，其他模型计时进程按任务串行；保留此负载限制，不把它当无干扰硬件榜单。

Piper Huayan 的公开 MODEL_CARD 标注数据集许可 Unknown，Amy 声音条款也需独立核对；这轮仅作本地技术评估，速度快不意味着已经批准产品再分发。VOICEVOX 依照用户明确接受的本地用途与署名条件测试。未对同一家族所有声音、所有语言或量化版本作穷举。

播放辅助诊断：VOICEVOX 的聚合 RTF 为 0.816，但立即起播理论队列的缺口 p95 为 457ms；Kokoro 中/英分别约 2343/1734ms。原生 PCM 回调样本数与最终波形总数已逐条核对，CPU 批次未发现覆盖差异；这只是回调到达节奏的模拟，不能替代真实设备试听。各 CPU 路径本批次未见达到 `abs(sample)>=0.999` 的削波。没有削波不代表读音或自然度通过。

## GPU 路径与运行环境

Qwen 在 RTX 4060 Laptop 8GB 上使用 Python 3.12.13、Torch 2.9.1+cu128、BF16、SDPA，每次仅加载一个模型；CPU 推理线程仍为 2。ASR 包 0.0.6 / Transformers 4.57.6，TTS 包 0.1.1 / Transformers 4.57.3。CUDA 可用与 BF16 已在实际推理确认；不会因 `nvidia-smi` 检出显卡就推定可运行，也没有静默回退 CPU。

三语兼容性 smoke 已完成但不纳入正式汇总。完整测试使用 ASR `transcribe`（最多 512 token）和 TTS `generate_custom_voice`（最多 2048 token），声音 zh=Vivian、en=Ryan、ja=Ono_Anna；保留返回异常与慢轮次。此次 TTS 的“首 PCM”是整段波形返回时间，ASR 也是完整录音 API；不引用官方原生流式路径的宣传首字替代本机实际结果。未接入 vLLM、未测 ASR/TTS GPU 并发、未完成产品 GPU adapter。

接口边界依据：[Qwen TTS 官方 wrapper](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py)说明 `non_streaming_mode=false` 只是模拟流式文本输入，并不启用真正的流式生成；[Qwen ASR 官方 wrapper](https://github.com/QwenLM/Qwen3-ASR/blob/main/qwen_asr/inference/qwen3_asr.py)的 streaming state 限 vLLM 后端。本轮不引入未经验证的第三方 fork 改写模型内部生成循环。

CPU 隔离环境为 Python 3.13.5，sherpa-onnx 1.13.8、faster-whisper 1.2.1 / CTranslate2 4.8.4、Vosk 0.3.45、kokoro-onnx 0.6.1 / ONNX Runtime 1.31.1、misaki 0.9.4、VOICEVOX core 0.17.1。每份原始报告保存实际安装版本；完整冻结依赖表在 ignored 目录 `strict/cpu-requirements.txt`、`qwen-asr-requirements.txt`、`qwen-tts-requirements.txt`。

Qwen ASR 的正式结果（每语言 50 段、150 次热态；完整录音已供给之后）：

| 语言 | CER / 英语 WER | 首结果 p95 | Torch 分配峰值 |
|---|---:|---:|---:|
| zh | CER 8.43% | 1505ms | 1789MiB |
| en | WER 4.39% | 1523ms | 1789MiB |
| ja | CER 8.99% | 2100ms | 1789MiB |

中文和英语本子集错误率低于本轮 CPU 候选，但原版 SenseVoice 的离线首结果 p95 约 805ms，日语约 931ms，延迟更低；日语两者错误率接近。它们是具体模型/精度/后端组合，不能把 CPU 与 GPU 的耗时差异归结为模型结构本身。Torch 分配峰值不包括系统及其他进程显存，也不能据单模型峰值相加就断言并发一定可用。

Qwen TTS 正式结果（每语言 12 文本 × 5；整段波形返回时间）：

| 语言 / 声音 | 首 PCM p95 | 短应答 p95 | 合成字/s | 播报字/s | RTF | Torch 分配峰值 |
|---|---:|---:|---:|---:|---:|---:|
| zh / Vivian | 28502ms | 5781ms | 1.94 | 3.97 | 2.050 | 2374MiB |
| en / Ryan | 22195ms | 7329ms | 5.30 | 9.74 | 1.838 | 2404MiB |
| ja / Ono_Anna | 26759ms | 5993ms | 2.58 | 4.58 | 1.774 | 2399MiB |

## TTS 回识与重点复听

同一套 156 条合成音频交给原版 SenseVoice 和 Whisper Small，各 156 次；两者在前述真人语料中已单独测过。**回识字符串错误率包含裁判错误和正字法差异，不是 TTS 发音错误率或听感分数。** 全部 12 文本的原始 CER/WER、中文 t2s CER 和最大误差例子在 `report-final/tts-intelligibility.json`。

例如 Qwen 英语的两个裁判都把文本中的 `twenty-eighth, twenty twenty-six` 写成数字串，原始 WER 因此升高。为解释这类现象，额外作**事后探索性诊断**：统一排除预先标注的 `numbers` / `date` 两类，保留其他 10 条，不修改全部 12 条的主成绩。该子集仍有裁判和汉字/假名等偏差，不作为预注册的模型胜负结论。

| TTS / 语言 | 指标（10 条诊断子集） | SenseVoice 裁判 | Whisper 裁判 |
|---|---|---:|---:|
| Piper Amy low / en | WER | 2.21% | 2.21% |
| Piper Lessac medium / en | WER | 2.21% | 1.47% |
| Kokoro v1.1-zh / en | WER | 5.88% | 5.88% |
| Melo / en | WER | 25.74% | 25.00% |
| Qwen / en | WER | 1.47% | 1.47% |
| Piper Huayan medium / zh | t2s CER | 4.82% | 10.96% |
| Kokoro v1.1-zh / zh | t2s CER | 3.07% | 6.14% |
| Melo / zh | t2s CER | 4.82% | 7.89% |
| Qwen / zh | t2s CER | 0.88% | 1.32% |
| Kokoro pyopenjtalk / ja | CER | 11.27% | 12.11% |
| Kokoro Cutlet / ja | CER | 3.38% | 4.23% |
| VOICEVOX:ずんだもん / ja | CER | 3.10% | 5.07% |
| Qwen / ja | CER | 4.51% | 6.20% |

优先复听的匿名样本（仅为风险线索，未宣称已听出错误）：

- **L054 / Amy 英语否定句**：参考 `I didn't say he wasn't responsible`，两个裁判均输出 `I didn't say he was responsible`，丢失的否定会改变意思。Lessac、Kokoro 和 Qwen 的同句均被两个裁判保留该否定；Amy 即使首 PCM 最快，也需先复听确认。
- **L009 / Melo 英语短应答**：参考 `I see.`，两个裁判分别得到 `the` / `See?`。
- **L067 / Melo 英语生僻词**：`unreliable narrator's ambivalence` 在两个裁判中均严重偏离；需核对词典覆盖和实际发音。

日语 pyopenjtalk 与 Cutlet 的回识差异提示前端不能混作同一配置，实际读音仍需复听。当前 Cutlet 的 CPU 首音很慢，VOICEVOX 更适合作为低延迟人工试听对象；不据上述字符串指标宣称其自然度通过。

## 执行文件与重跑

新脚本只用于本地评测，不自动把候选加入产品下载目录或切换对话模型。

```powershell
$env:RUN_REAL_AI_TESTS='0'
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe scripts/prepare_speech_evaluation.py --count 50
.venv/Scripts/python.exe scripts/prepare_speech_candidates.py --families vosk whisper kokoro
.venv/Scripts/python.exe scripts/prepare_speech_candidates.py --families sensevoice --manifest reference-candidates.json
.venv/Scripts/python.exe scripts/prepare_speech_candidates.py --families piper --manifest piper-candidates.json
.venv/Scripts/python.exe scripts/prepare_speech_candidates.py --families zipformer --manifest zipformer-candidates.json
.venv/Scripts/python.exe scripts/prepare_speech_candidates.py --families kokoro_cutlet --manifest kokoro-frontends-candidates.json
.venv/Scripts/python.exe scripts/prepare_speech_candidates.py --families qwen_asr qwen_tts --manifest qwen-candidates.json
.venv/Scripts/python.exe scripts/evaluate_local_speech.py --python build/local-speech-evaluation/strict/runtime/Scripts/python.exe --run-dir build/local-speech-evaluation/strict/runs/example
.venv/Scripts/python.exe scripts/report_speech_evaluation.py --runs build/local-speech-evaluation/strict/runs/example
```

严格评测独立环境位于 `build/local-speech-evaluation/strict/runtime/`；候选分别保存在 `candidate_models/` 和 `*candidates.json`，不进入正常模型目录。Qwen ASR/TTS 使用各自的可选隔离 Python，因为其公开包固定不同的 Transformers 版本。运行依赖和资产不会加入基础桌面安装。

上述推理命令复用已准备环境；重建环境时使用前节的版本与本地冻结清单。CPU Python 为 3.13.5，两个 Qwen Python 为 3.12.13；CUDA Torch wheel 从官方 cu128 索引取得，完整 wheel 与 SHA 保存在 `strict/runtime_assets/`，不可换装普通 CPU wheel 后继续沿用 GPU 报告。外部 `ffmpeg` 须在 PATH 上，用于公开语料格式转换，不执行用户材料中的指令。

VOICEVOX 需执行者明确接受对应条款才使用 `--families voicevox --manifest voicevox-candidates.json --voicevox-license-accepted`；本次用户已同意仅作本地评测并保留署名。已有的失败、smoke、正式 CPU/GPU 批次不要混在一个 `--runs` 导出列表中；重复模型/语言会报错，避免把不同样本数的数据混为一组。

`evaluation_worker.py` 每个新 run 复制到 `source_snapshot/` 后执行，避免评测过程中源码修改影响已启动批次；主任务的较早第一轮保留逐任务源码哈希。`request.json`、`report.json` 和 stdout/stderr 都在独立任务目录；公共语料参考与识别结果可逐条核对。准备与启动失败也保留，不将下载/安装时间混入热态推理。

同一 run 仅在源码快照、硬件、线程与请求相符时复用完成结果；缺少快照的早期结果仍可导出，但不继续往里追加新测量。发现未完成 request 时保留其日志和 `progress-*.json`，改用新 `--run-dir`，不覆盖中断前的观察。TTS 回识同样绑定原报告/音频哈希与裁判集合；变更时用新 `--output`。不要并行启动针对同一目录的两份评测进程。

本次最终聚合可从已有原始结果重建，无需再次推理：

```powershell
$strictRoot=(Join-Path $PWD 'build/local-speech-evaluation/strict')
$speechRunNames=@('cpu2-20261028-a','cpu2-reference','cpu2-candidates','cpu2-additional','cpu2-kokoro-cutlet','gpu-bf16-full')
$speechRunPaths=$speechRunNames | ForEach-Object { Join-Path "$strictRoot/runs" $_ }
$env:PYTHONPATH=(Join-Path $PWD 'src')
& "$strictRoot/runtime/Scripts/python.exe" scripts/report_speech_evaluation.py --runs $speechRunPaths --partial-runs "$strictRoot/runs/partial50-cpu2" --roundtrip "$strictRoot/roundtrip" --canonical-zh --output "$strictRoot/report-final"
```

事后的 10 条非数字诊断另保存在 `tts-nonnumeric-diagnostic.json`，不覆盖主聚合的全部 12 条成绩。

## 完成项与验证

- [x] 原版 SenseVoice、Vosk、Whisper 的同语料对照及异常结果复核。
- [x] 日语 Kokoro / VOICEVOX 的真实首 PCM、吞吐与音频样本。
- [x] 7 个原生 STT 配置/语言的全部 50 段定速首字测试，含缺失样本口径。
- [x] Qwen ASR 环境与本机 GPU 三语完整测试。
- [x] Qwen TTS 三语完整重复测量；官方 Python API 未暴露的流式能力另列未验证。
- [x] TTS 双裁判回识辅助与 156 条最终匿名听评样本。
- [x] 最终聚合表、针对性离线回归及已知限制。

`RUN_REAL_AI_TESTS=0` 下执行相关离线回归，**74 passed / 15.78 秒，Ruff 通过**；provider 用 mock，Qt 为离屏交互，不以此冒充真实识别或设备出声。另以公开中文录音实际运行修正后的产品 Zipformer 工厂，5 次均有文本，报告记录 adapter revision 2；旧配置报告不再被匹配。四个原有模型包重新校验均通过，150 段公开语料哈希和全部请求/结果计数也通过核对。未重跑整仓，不能据此宣称其他并行改动通过。

```powershell
$env:RUN_REAL_AI_TESTS='0'
.venv/Scripts/python.exe -m pytest tests/local_speech tests/test_local_speech_desktop.py tests/providers/test_speech.py -q
```

本机证据均在 ignored `build/local-speech-evaluation/strict/`：

- `report-final/results.md`、`summary.csv`、`summary.json`：34 组首字/首 PCM、字速、错误率、冷模型加载、首次推理和内存；原生首字含失败样本口径。
- `report-final/listening/index.html`：156 条匿名试听与空白评分；`listening-key.json` 为独立映射，音频目录含 `VOICEVOX:ずんだもん` 署名。
- `report-final/asr-error-examples.json`、`canonical-zh-rows.json`：可核对的真人识别错误与中文正字法转换。
- `report-final/tts-intelligibility.json`、`tts-nonnumeric-diagnostic.json`：双裁判全部成绩、最大误差例子及事后诊断；完整请求/转写在 `roundtrip/`。
- `verification.json`、`default-zipformer-probe.json`、`verification/pytest.txt`、`verification/ruff.txt`：计数/哈希核对、真实默认工厂探针与离线验证。

正式批次为 `runs/cpu2-20261028-a`、`cpu2-reference`、`cpu2-candidates`、`cpu2-additional`、`cpu2-kokoro-cutlet`、`gpu-bf16-full`；原生首字另在 `runs/partial50-cpu2`。失败的早期目录、smoke 与旧 decoder 质量失败结果均保留。

人工自然度/清晰度/读音评分另待听评者填写；这项不由自动计时、回识或截图冒充完成。

试听及回识固定使用每条文本的 `repeat=0` 音频，不从五次中挑选听起来最好或最快的一次。匿名页支持按语言和同一句筛选、逐项打分与导出 JSON；评分初始为空，音量使用原始输出且未作响度匹配，不能将个人听评包装成正式 MOS 研究。

音频证据限制：本批计时版 worker 只保留热态 `repeat=0` 的波形，其余轮次保留数值；旧记录中重复的 `preview` 路径指向首轮音频，不能把它当成后续随机生成或冷推理的对应波形，因此不能复听所有慢例。已修正后续 worker，分别保存冷推理和每次热态波形；当前批次保持其原始源码快照与哈希，不回填不存在的音频。

## 未决事项

- 人工自然度、清晰度与读音评分，优先复听否定、短应答、生僻词和专名；当前无 MOS 结论。
- 学习者口音、1–3 秒极短真人回答、麦克风噪声、真实设备出声、VAD/AEC、打断及完整 RTC/LLM/TTS 链路，均不能由本次朗读文件实测代替。
- Qwen 原生流式后端、GPU 双模型并发与产品 adapter；候选声音的产品再分发审核。模型库 GUI 当前的推荐仍按初步计算预算，尚未自动接入本次质量数据。
