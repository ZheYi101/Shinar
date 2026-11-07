# 逐模型语言、大小、资源与效果报告（2026-10-29）

2026-11-06 更新：用户已明确淘汰 SenseVoice 2025 / WSYue 分支，当前产品目录不再保留任何语言或用途的此模型。下文的数值、音频和旧取舍仅作历史证据；原版 2024 保留。

**此前 CPU 批次选型**：STT 按热态首字算术平均 ≤500ms 留下 SenseVoice 原版 2024 和 2025/WSYue 的中、英四项，当时日语暂缺。TTS 中文保留 Melo、英语优先 Lessac、Amy 因已确认否定词错误仅备选、日语暂留 VOICEVOX；Kokoro 和 Qwen 退出本轮候选。允许按语言选择不同模型。以下历史数值与音频保留。

随后实际重跑的 [SenseVoice GPU、日语 STT 与 Melo 独立英文补测](./SPEECH_GPU_JAPANESE_MELO_FOLLOWUP_2026-10-29.md)另列新运行时、精度、CPU/GPU 资源百分比及试听附件：2024 FP32 GPU 三语 52–58ms，新增日语 ReazonSpeech CPU / Kotoba GPU 通过速度线。本页仍归档原批次，不把新配置数值混写进下面的旧表。

本表使用 2026-10-28 至 29 日已完成的本机实测，新增工作只盘点磁盘并整理附件，没有重跑模型。19 个具体模型/配置（含共享权重的精度/前端对照），34 个模型/语言配置；STT 21 配置、TTS 13 配置。正式热态 3506 次，原生首字定速回放 350 次，TTS 双裁判回识 312 次。

硬件：i9-14900HX，32 逻辑 CPU、约 31.8 GiB RAM；RTX 4060 Laptop，8188 MiB 显存。CPU 模型采用 2 推理线程策略（Vosk 按引擎实现）；Qwen 单模型 CUDA BF16 / SDPA，Torch CPU 线程为 2。未测试 GPU 并发，也未采集 CPU/GPU 利用率百分比、功耗或 CPU 时间；不能把 2 线程换算成占用率。CPU 路径没有 CUDA allocator 数据，“—”表示未使用/未测，不是显卡总占用为零。

CPU 环境 Python 3.13.5，sherpa-onnx 1.13.8、faster-whisper 1.2.1 / CTranslate2 4.8.4、Vosk 0.3.45、kokoro-onnx 0.6.1 / ONNX Runtime 1.31.1、misaki 0.9.4、VOICEVOX core 0.17.1。Qwen 为独立 Python 3.12.13 / Torch 2.9.1+cu128 环境，ASR 0.0.6 / Transformers 4.57.6，TTS 0.1.1 / Transformers 4.57.3；完整冻结依赖随附件 environment-*.txt 保存。

大小均为 MiB（2²⁰ 字节），逐文件实际盘点。使用权重包含该配置实际读取的权重和 voices 容器，Vosk 则为全部部署组件。原样目录含包内词典、其他版本和附带资产，剔除本地安装回执/下载回执；不含独立 Python、CUDA、推理库、外置词典和下载缓存。下载资产是已记录包/文件总字节，VOICEVOX 该列不含另行安装的 core wheel/词典；不能把三列相加当最小安装量。三个 Zipformer 配置共享一个目录，两个 Kokoro 日语前端也共享一个目录。

RAM 为原报告 peak_process_rss_bytes 的跨语言范围，不是只含权重的大小，也不是最低内存需求；较早报告缺少 memory_kind，按原样保留 unspecified，不升级为已确认的峰值采样口径。model-metrics.csv 保留每语言数值与该字段。CUDA allocated/reserved 是 PyTorch allocator 峰值，不是整张显卡占用或总显存需求，两个独立峰值也未必同时发生。

STT 每语言 50 段 FLEURS 真人朗读（中文约 536s、英语 475s、日语 653s），通常 3 次热态，Zipformer 精度对照为 1 次。错误率中日用 CER、英语用 WER，越低越好，不以 1−错误率冒充准确率；不是全量榜单或学习者口音验收。离线首字在完整录音给齐后计时；原生首字是 200ms 定速回放从音频起点计时，包含静音/声学上下文。两类不能直接排名；总体分位数落入未出字部分记为“—”，成功样本条件值另存 CSV。旧 Zipformer 原生首字只有 3 段诊断，其余原生配置为 50 段。完整计算 p95 是整段计算，不是流式录音结束后的尾延迟。

TTS 每语言 12 文本 × 5 次，Cutlet 为 ×3。首 PCM 指音频回调，不是扬声器出声；Qwen 当前 API 等整段波形返回，原生流式优化未验证。短应答仅两条，和包含长句的总体 p95 分开。合成字/s 是请求文本字数/计算秒，播报字/s 是请求文本字数/生成音频秒，漏读/重复会影响意义；不能跨语言直接排名。RTF = 总计算秒/总音频秒，小于 1 表示平均算得比音频播放快，但不能保证分块起播后不中断。加载与首次推理各为一个新进程样本，首次测试句可能不同，不是冷启动分布，未清空 OS 缓存。

原客观实验没有人工听感评分；2026-10-29 用户已给本批样本定性试听反馈，并确认 Amy L054 错误，最新筛选另列，仍无多人 MOS。TTS 回识错误含裁判错误、数字书写和日语汉字/假名差异，不能当真人听感或直接宣称发音错误率；完整 12 文本为主结果，去数字/日期的 10 文本文件为事后探索，不替换主结果。156 条 WAV 都是正式热态 repeat 0，后续重复的计时没有各自独立波形；没有伪称保留全部 756 次声音。保留原始响度，试听时请用相同设备和音量。

TTS 表已将“加载 / 首次推理”改为“加载 / 首次整句完成”，并增列“首次首 PCM”，防止把完整合成耗时当首音。VOICEVOX 该次加载 1332ms，加载后首次首 PCM 为 346ms、整句完成 1703ms，模型已加载时无需每句话重新加载。

## 模型语言与资源

| 具体模型 / 配置 | 适配语言 | 使用权重 MiB | 原样目录 MiB | 下载资产 MiB | 进程 RAM MiB | CUDA allocated MiB | CUDA reserved MiB | CPU / GPU 路径 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SenseVoice 原版 2024 INT8 | 中/英/日；家族另有韩/粤，未测 | 228.2 | 228.5 | 228.5 | 398–421 | — | — | CPU 2 推理线程；GPU 未测 |
| SenseVoice 2025 / WSYue INT8 | 中/英/日接口；韩/粤未测 | 226.1 | 226.4 | 226.4 | 397–420 | — | — | CPU 2 推理线程；GPU 未测 |
| Zipformer 旧全 INT8 | 中/英 | 47.4 | 474.1 | 437.0 | 135–136 | — | — | CPU 2 推理线程；GPU 未测 |
| Zipformer INT8 + FP32 decoder | 中/英 | 57.3 | 474.1 | 437.0 | 151 | — | — | CPU 2 推理线程；GPU 未测 |
| Zipformer 全 FP32 | 中/英 | 109.9 | 474.1 | 437.0 | 204–205 | — | — | CPU 2 推理线程；GPU 未测 |
| Vosk Small CN 0.22 | 中文独立包 | 65.1 | 65.1 | 41.9 | 257 | — | — | CPU；Vosk 引擎线程策略；GPU 未测 |
| Vosk Small EN-US 0.15 | 英语独立包 | 67.6 | 67.6 | 39.3 | 221 | — | — | CPU；Vosk 引擎线程策略；GPU 未测 |
| Vosk Small JA 0.22 | 日语独立包 | 94.3 | 94.3 | 47.4 | 357 | — | — | CPU；Vosk 引擎线程策略；GPU 未测 |
| Whisper Small / faster-whisper | 中/英/日；官方 99 语，其他未测 | 461.1 | 463.7 | 463.7 | 693–694 | — | — | CPU 2 推理线程；GPU 未测 |
| Qwen3-ASR 0.6B | 中/英/日；官方 30 语 + 22 方言，其他未测 | 1789.2 | 1793.4 | 1793.4 | 2760 | 1789 | 1842–1844 | CUDA BF16 / SDPA；CPU 2 线程，CPU 推理未测 |
| Kokoro v1.1 中英 INT8 | 本次 ONNX 前端仅中/英 | 160.2 | 205.3 | 140.2 | 542–735 | — | — | CPU 2 推理线程；GPU 未测 |
| Melo 中英 ONNX | 本次具体包中/英 | 162.5 | 182.4 | 159.3 | 451–526 | — | — | CPU 2 推理线程；GPU 未测 |
| Piper Lessac medium | 英语声音包 | 60.2 | 77.4 | 64.1 | 370 | — | — | CPU 2 推理线程；GPU 未测 |
| Piper Amy low | 英语声音包 | 60.2 | 77.3 | 64.0 | 348 | — | — | CPU 2 推理线程；GPU 未测 |
| Piper Huayan medium | 中文声音包 | 60.3 | 77.4 | 64.1 | 666 | — | — | CPU 2 推理线程；GPU 未测 |
| Kokoro v1.0 日语 / pyopenjtalk | 日语前端，jf_alpha | 135.7 | 135.7 | 135.7 | 1000 | — | — | CPU 2 推理线程；GPU 未测 |
| Kokoro v1.0 日语 / Cutlet | 日语前端，jf_alpha | 135.7 | 135.7 | 135.7 | 1011 | — | — | CPU 2 推理线程；GPU 未测 |
| VOICEVOX ずんだもん 0.17.1 | 日语，style 3 normal | 56.6 | 84.4 | 61.8 | 394 | — | — | CPU 2 推理线程；GPU 未测 |
| Qwen3-TTS 0.6B CustomVoice | 中/英/日；官方另韩/德/法/俄/葡/西/意，未测 | 2378.4 | 2382.6 | 2382.6 | 2532–2533 | 2374–2404 | 2782–2918 | CUDA BF16 / SDPA；CPU 2 线程，CPU 推理未测 |

附属词典（不含 Python/推理运行库）：

| 组件 | 磁盘大小 | 位置口径 |
| --- | --- | --- |
| Open JTalk 字典（VOICEVOX / pyopenjtalk） | 102.3 MiB | 环境共享，不在 Kokoro/VOICEVOX 模型目录中 |
| UniDic-lite（Cutlet） | 248.4 MiB | 环境共享，不在 Kokoro/VOICEVOX 模型目录中 |

## STT 运行时间与识别效果

| 模型 | 语言 | 加载 / 首次推理 ms | 热态首字 p50 / p95 ms | 首字口径 | 全部计算 p95 ms | 参考字/计算秒 | RTF | CER / WER | 未出 partial |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SenseVoice 原版 2024 INT8 | 中文 | 1350 / 339 | 452 / 805 | 完整录音已给齐 | 805 | 74.0 | 0.045 | CER 11.38% | 不适用 |
| SenseVoice 原版 2024 INT8 | 英语 | 1136 / 449 | 432 / 805 | 完整录音已给齐 | 805 | 221.8 | 0.048 | WER 7.94% | 不适用 |
| SenseVoice 原版 2024 INT8 | 日语 | 935 / 626 | 567 / 931 | 完整录音已给齐 | 931 | 87.8 | 0.046 | CER 8.75% | 不适用 |
| SenseVoice 2025 / WSYue INT8 | 中文 | 898 / 269 | 400 / 730 | 完整录音已给齐 | 730 | 82.6 | 0.041 | CER 11.50% | 不适用 |
| SenseVoice 2025 / WSYue INT8 | 英语 | 1298 / 431 | 402 / 636 | 完整录音已给齐 | 636 | 259.7 | 0.042 | WER 29.35% | 不适用 |
| SenseVoice 2025 / WSYue INT8 | 日语 | 970 / 949 | 683 / 1267 | 完整录音已给齐 | 1267 | 73.2 | 0.056 | CER 77.24% | 不适用 |
| Zipformer 旧全 INT8 | 中文 | 848 / 171 | 2408 / 3408 | 定速音频起点 | 490 | 122.4 | 0.027 | CER 79.32% | 0/3 |
| Zipformer 旧全 INT8 | 英语 | 675 / 214 | 3410 / — | 定速音频起点 | 484 | 415.1 | 0.029 | WER 78.88% | 1/3 |
| Zipformer INT8 + FP32 decoder | 中文 | 763 / 127 | 2207 / 4608 | 定速音频起点 | 358 | 151.2 | 0.021 | CER 17.50% | 0/50 |
| Zipformer INT8 + FP32 decoder | 英语 | 677 / 216 | — / — | 定速音频起点 | 340 | 472.9 | 0.023 | WER 74.21% | 26/50 |
| Zipformer 全 FP32 | 中文 | 683 / 196 | 2209 / 5009 | 定速音频起点 | 571 | 98.1 | 0.033 | CER 17.16% | 0/50 |
| Zipformer 全 FP32 | 英语 | 690 / 331 | 7809 / — | 定速音频起点 | 513 | 325.9 | 0.033 | WER 73.93% | 25/50 |
| Vosk Small CN 0.22 | 中文 | 1118 / 1683 | 2262 / 4921 | 定速音频起点 | 3061 | 17.5 | 0.191 | CER 22.53% | 0/50 |
| Vosk Small EN-US 0.15 | 英语 | 2061 / 1439 | 1528 / 2628 | 定速音频起点 | 1774 | 77.5 | 0.134 | WER 25.61% | 0/50 |
| Vosk Small JA 0.22 | 日语 | 643 / 4700 | 2887 / 10469 | 定速音频起点 | 6758 | 11.5 | 0.321 | CER 27.22% | 1/50 |
| Whisper Small / faster-whisper | 中文 | 2249 / 2282 | 2135 / 2752 | 完整录音已给齐 | 2753 | 15.5 | 0.204 | CER 23.40%；t2s 14.10% | 不适用 |
| Whisper Small / faster-whisper | 英语 | 2227 / 2297 | 2054 / 2939 | 完整录音已给齐 | 2940 | 53.1 | 0.231 | WER 6.26% | 不适用 |
| Whisper Small / faster-whisper | 日语 | 1268 / 2390 | 2155 / 2935 | 完整录音已给齐 | 2935 | 21.6 | 0.172 | CER 13.69% | 不适用 |
| Qwen3-ASR 0.6B | 中文 | 12079 / 1056 | 796 / 1505 | 完整录音已给齐 | 1505 | 38.5 | 0.084 | CER 8.43% | 不适用 |
| Qwen3-ASR 0.6B | 英语 | 10518 / 1658 | 974 / 1523 | 完整录音已给齐 | 1523 | 104.8 | 0.105 | WER 4.39% | 不适用 |
| Qwen3-ASR 0.6B | 日语 | 10263 / 1808 | 1336 / 2100 | 完整录音已给齐 | 2100 | 36.4 | 0.104 | CER 8.99% | 不适用 |

## TTS 运行时间

| 模型 | 语言 | 加载 / 首次整句完成 ms | 首次首 PCM ms | 热态首 PCM p50 / p95 ms | 短应答 p95 ms | 完整合成 p95 ms | 合成字/s | 播报字/s | RTF |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Kokoro v1.1 中英 INT8 | 中文 | 1605 / 2257 | 2257 | 2294 / 4792 | 2294 | 13542 | 4.2 | 4.5 | 1.075 |
| Kokoro v1.1 中英 INT8 | 英语 | 1497 / 1525 | 1524 | 2875 / 8393 | 1884 | 8395 | 16.3 | 16.5 | 1.017 |
| Melo 中英 ONNX | 中文 | 2367 / 455 | 454 | 848 / 1977 | 944 | 4944 | 11.4 | 5.4 | 0.477 |
| Melo 中英 ONNX | 英语 | 2973 / 516 | 515 | 1496 / 2930 | 893 | 5284 | 25.4 | 12.8 | 0.506 |
| Piper Lessac medium | 英语 | 953 / 105 | 105 | 183 / 522 | 78 | 524 | 253.6 | 15.8 | 0.062 |
| Piper Amy low | 英语 | 981 / 106 | 106 | 119 / 347 | 54 | 348 | 421.4 | 13.3 | 0.032 |
| Piper Huayan medium | 中文 | 857 / 99 | 99 | 170 / 572 | 104 | 574 | 98.9 | 5.2 | 0.053 |
| Kokoro v1.0 日语 / pyopenjtalk | 日语 | 1965 / 9444 | 9443 | 22807 / 51702 | 11547 | 51704 | 1.4 | 5.3 | 3.823 |
| Kokoro v1.0 日语 / Cutlet | 日语 | 1848 / 7403 | 7402 | 21252 / 54539 | 9314 | 54540 | 1.5 | 5.6 | 3.816 |
| VOICEVOX ずんだもん 0.17.1 | 日语 | 1332 / 1703 | 346 | 382 / 765 | 507 | 11934 | 6.5 | 5.3 | 0.816 |
| Qwen3-TTS 0.6B CustomVoice | 中文 | 12458 / 5222 | 5222 | 10178 / 28502 | 5781 | 28503 | 1.9 | 4.0 | 2.050 |
| Qwen3-TTS 0.6B CustomVoice | 英语 | 9028 / 5322 | 5322 | 11168 / 22195 | 7329 | 22195 | 5.3 | 9.7 | 1.838 |
| Qwen3-TTS 0.6B CustomVoice | 日语 | 8872 / 7009 | 7009 | 11781 / 26759 | 5993 | 26759 | 2.6 | 4.6 | 1.774 |

## TTS 双裁判辅助结果（全部 12 文本）

数字和日期仅有书写差异也会产生错误；中文成对列出原始 / OpenCC t2s 后 CER，避免把繁简差异当成发音错误。

| TTS | 语言 | 指标 | SenseVoice 原版裁判 | Whisper Small 裁判 |
| --- | --- | --- | --- | --- |
| Kokoro v1.1 中英 INT8 | 中文 | CER 原始 / t2s | 2.58% / 2.58% | 19.19% / 11.44% |
| Kokoro v1.1 中英 INT8 | 英语 | WER | 13.41% | 12.80% |
| Melo 中英 ONNX | 中文 | CER 原始 / t2s | 4.80% / 4.80% | 32.10% / 15.13% |
| Melo 中英 ONNX | 英语 | WER | 22.56% | 30.49% |
| Piper Lessac medium | 英语 | WER | 2.44% | 9.76% |
| Piper Amy low | 英语 | WER | 1.83% | 9.76% |
| Piper Huayan medium | 中文 | CER 原始 / t2s | 5.17% / 5.17% | 23.62% / 16.97% |
| Kokoro v1.0 日语 / pyopenjtalk | 日语 | CER | 13.63% | 16.06% |
| Kokoro v1.0 日语 / Cutlet | 日语 | CER | 5.84% | 9.73% |
| VOICEVOX ずんだもん 0.17.1 | 日语 | CER | 7.06% | 10.46% |
| Qwen3-TTS 0.6B CustomVoice | 中文 | CER 原始 / t2s | 0.74% / 0.74% | 27.31% / 7.01% |
| Qwen3-TTS 0.6B CustomVoice | 英语 | WER | 9.15% | 9.15% |
| Qwen3-TTS 0.6B CustomVoice | 日语 | CER | 8.52% | 9.98% |

## 每个配置适合怎样使用

- **SenseVoice 原版 2024 INT8**：本批三语均可作为 CPU 候选；不提供原生 partial。
- **SenseVoice 2025 / WSYue INT8**：中文继续保留；英语 WER 29.35% 已忽略大小写，数字等格式规范化后 28.53%，保留可选备份、不设英语默认。日语 CER 77.24%。
- **Zipformer 旧全 INT8**：旧 decoder 配置导致严重质量问题；保留对照，不选用。
- **Zipformer INT8 + FP32 decoder**：中文修复至 CER 17.50%；英语 WER 74.21%，实时回放 26/50 段未在录音结束前出字。
- **Zipformer 全 FP32**：中文略优于混合精度且更慢；英语仍差，25/50 段未在录音结束前出字。
- **Vosk Small CN 0.22**：低内存、原生 partial；中文 CER 22.53%，首字包含音频上下文。
- **Vosk Small EN-US 0.15**：原生 partial；本批首字较快，WER 25.61%，质量弱于 Whisper/SenseVoice 原版。
- **Vosk Small JA 0.22**：CER 27.22%；50 段中 1 段录音结束前没有 partial。
- **Whisper Small / faster-whisper**：CPU INT8 / beam 1；英文 WER 6.26%。中文繁简转换后 CER 14.10%，原始 23.40%。
- **Qwen3-ASR 0.6B**：用户因速度排除 Qwen 系列，本轮不继续原生流式补测；历史 GPU 整段 API 结果保留。
- **Kokoro v1.1 中英 INT8**：用户因质感排除当前已测 Kokoro 配置；保留客观数据与原音，此包不能直接承担日语。
- **Melo 中英 ONNX**：用户认可中文，保留中文候选；英语中国口音明显，当前单 speaker 包退出英语候选。
- **Piper Lessac medium**：用户认可质感和首字速度，列为英语优先候选；短应答首 PCM p95 78ms。
- **Piper Amy low**：用户认可质感和速度，并亲耳确认 L054 wasn't → was 错误；修复并复测前仅作备选，不设默认。
- **Piper Huayan medium**：短应答首 PCM p95 104ms；需人工试听。MODEL_CARD 的 Dataset License 为 Unknown，本地评估不代表可随产品分发。
- **Kokoro v1.0 日语 / pyopenjtalk**：用户排除当前已测 Kokoro 配置。短应答 p95 11.55s；不能外推成整个家族性能。
- **Kokoro v1.0 日语 / Cutlet**：用户排除当前已测 Kokoro 配置。短应答 p95 9.31s；计时有约 19s 离线回归负载重叠，数据保留。
- **VOICEVOX ずんだもん 0.17.1**：用户认为音质可以、速度勉强可接受，暂留日语候选。首 PCM 热态平均 447ms、短应答平均 317ms；1703ms 是首次整句完成，首次首 PCM 为 346ms。VOICEVOX:ずんだもん。
- **Qwen3-TTS 0.6B CustomVoice**：用户因速度排除 Qwen 系列，不继续本轮原生流式/并发补测；历史 BF16 / SDPA 整段 API 结果保留。zh Vivian / en Ryan / ja Ono_Anna。

## 其他语言的声明范围

SenseVoice 原版家族：普通话、英语、日语、韩语、粤语；本次韩语/粤语未测。各 Vosk / Piper 声音包是逐语言安装，Kokoro 中英包和日语前端按实际部署分别列出，不把家族其他语种直接算进当前包。完整逐模型语言代码保存在附件 language-support.json。

Qwen3-ASR 官方 30 语代码：`zh / en / yue / ar / de / fr / es / pt / id / it / ko / ru / th / vi / ja / tr / hi / ms / nl / sv / da / fi / pl / cs / fil / fa / el / hu / mk / ro`；另列的 22 中文方言没有在本机验证。Qwen3-TTS 官方 10 语代码：`zh / en / ja / ko / de / fr / ru / pt / es / it`。除中/英/日外均未验证。

<details><summary>Whisper Small 本次固定 tokenizer 的 99 语代码（仅中/英/日有实测）</summary>

`en / zh / de / es / ru / ko / fr / ja / pt / tr / pl / ca / nl / ar / sv / it / id / hi / fi / vi / he / uk / el / ms / cs / ro / da / hu / ta / no / th / ur / hr / bg / lt / la / mi / ml / cy / sk / te / fa / lv / bn / sr / az / sl / kn / et / mk / br / eu / is / hy / ne / mn / bs / kk / sq / sw / gl / mr / pa / si / km / sn / yo / so / af / oc / ka / be / tg / sd / gu / am / yi / lo / uz / fo / ht / ps / tk / nn / mt / sa / lb / my / bo / tl / mg / as / tt / haw / ln / ha / ba / jw / su`

</details>


## 附件与来源

[SenseVoice 官方语言范围](https://github.com/QwenAudio/SenseVoice)为中、英、日、韩、粤；2025 WSYue 检查点不能据家族标签推定多语质量。[Whisper Small 转换模型卡](https://huggingface.co/Systran/faster-whisper-small)标注 99 语、磁盘 FP16，当前实测加载为 CPU INT8。[Qwen3-ASR 模型卡](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)列 30 种语言、22 种中文方言；[Qwen3-TTS 具体模型卡](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)列 10 语。这里仅中、英、日有本机结果，其他语言不作适配通过承诺。官方范围于 2026-10-29 核对。

STT 原音来自 [Google FLEURS](https://huggingface.co/datasets/google/fleurs)，revision 70bb2e84b976b7e960aa89f1c648e09c59f894dd，CC-BY-4.0；16kHz mono PCM16 转换，原始/转换 SHA 在原语料 manifest，附件原音再验证 SHA。VOICEVOX 音频署名 **VOICEVOX:ずんだもん**，按用户已接受条件仅作本地评测并保留署名。Piper 逐声音再分发许可尚未批准。本附件不含模型权重，也不构成产品分发许可结论。


最新[筛选与用户试听结论](./LOCAL_SPEECH_SELECTION_2026-10-29.md)。


本机附件：[可离线打开的报告与试听](../../../build/local-speech-evaluation/strict/model-catalog-2026-10-29/index.html)、[完整 ZIP](../../../build/local-speech-evaluation/strict/model-catalog-2026-10-29.zip)、[逐配置 CSV](../../../build/local-speech-evaluation/strict/model-catalog-2026-10-29/model-metrics.csv)。原始依据与实验限制见[严格评测阶段报告](./LOCAL_SPEECH_STRICT_EVALUATION_2026-10-28.md)。附件与音频保存在 ignored build 目录，不进入 Git；导出的 ZIP 可整体保存，解压后打开 index.html。


[SenseVoice 2025 大小写与格式复核](./SENSEVOICE_2025_FORMAT_AUDIT_2026-10-29.md)：全大写未被计错；格式规范化后英语差距仍在，保留中文和可选英语备份。
