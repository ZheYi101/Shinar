# 本地语音 CPU/GPU 设置接入记录（2026-10-29）

用户本轮要求：对已验证显著提速的模型优先推荐 GPU，硬件不适合才考虑 CPU；让用户选择计算设备，并独立展示 GPU 占用。新英文试听得到“听感上来说都不错”的定性反馈；没有据此补造 MOS，也没有撤回 Amy L054 已确认的具体错误。

## 本次改动

- 设置分为“语音模型”和“计算与加速”两个子页。模型按语言分别选择 STT/TTS；计算按任务选择自动、CPU 或 NVIDIA CUDA，支持多显卡编号。实际会话按会话语言路由，不使用模型列表当前筛选语言。
- 首批本地分轮接入：SenseVoice 2024 FP32 GPU、2024/2025 INT8 CPU、ReazonSpeech CPU、现有 Zipformer 与 sherpa TTS，包括新目录中的 Piper Lessac。自动对 2024 FP32 优先 GPU；轻量或 INT8 适配没有已验证 GPU 收益时用 CPU。严格评测淘汰的 Kokoro/Qwen 与 2025 日语不作为新对话推荐。
- CPU/GPU 报告分别匹配模型指纹、adapter、运行时、GPU 编号/名称和本机硬件。STT 平均结束后计算超过 500 ms 不推荐、不能选作对话模型；切换设备后没有有效报告时要求重新测速。该值不含录音端点等待。
- 默认显存准入预算 3072 MiB、为其他应用留 1024 MiB，累计已加载 GPU 模型的估算。预算配置 ORT arena，并非整个进程显存硬上限；界面不承诺固定 GPU 使用率上限。
- 模型常驻复用，默认空闲 120 秒释放，可立即释放或手动释放。进程持有模型锁；Windows 使用完整子进程树释放，防止虚拟环境启动器遗留模型。GPU 显存和使用率按 2 秒采样，整卡与进程读数分开，驱动不支持时显示未知。
- 运行环境由软件在语音缓存建立独立 venv，固定 ORT GPU 1.23.2 / CUDA 12.8 / cuDNN 9.10。需要 NVIDIA 驱动，通常不需完整 CUDA Toolkit；真实 CUDA MatMul profiling 通过后才写就绪标记。支持 Python 3.11–3.13 非冻结桌面版。

主要实现：`src/lingualoop/local_speech/compute.py`、`runtime.py`、`runtime_probe.py`、`sensevoice.py`、`service.py`、`inference_worker.py`、`resources.py`、`processes.py`，以及 `desktop/speech_library.py`、`desktop/viewmodel.py`、设置 QML。运行策略与范围见 [Decision 0025](../../decisions/TECH_DECISIONS.md#decision-0025)。

## 验证结果

`build/local-speech-settings-validation/runtime-report.json` 保存数值与设备证据。这里是已有公开评测资产的开发接入检查，每个模型单条录音/内置文本、3 次热态，不能替代 [完整语料严格评测](./SPEECH_GPU_JAPANESE_MELO_FOLLOWUP_2026-10-29.md)。

- GPU 环境实际 MatMul：CUDA kernel 1 个，确认未静默落到 CPU。GPU 已有运行环境复用先前固定版本；CPU 则实际完成全新管理环境下载与探针，ORT 1.23.2、sherpa wrapper/core 1.13.8。
- 实际服务路径 SenseVoice 2024 FP32：首次加载 **1985 ms**，首次计算 **186.8 ms**；同一常驻模型下一次计算 **53.8 ms**。冷启动总等待不能写成 54 ms，首次使用尚无会话前自动预热。
- ReazonSpeech CPU 与 Piper Lessac CPU 均在新管理 CPU 环境中完成实际模型测速；Lessac 另通过实际分轮服务返回可解码 WAV。样本见 [Piper 本地服务样本](../../../build/local-speech-settings-validation/piper-lessac-live-route.wav)。此处未做人耳打分。
- 共同驻留时 2 个语音进程（GPU STT + CPU TTS）。整卡显存加载前 **2270 MiB**、驻留 **3410 MiB**、手动释放后 **2269 MiB**；释放后的语音进程数为 0。整卡约增加 1.1 GiB 仅供参考，这台 Windows WDDM 的进程显存为不可读取，不能把差值写成精确进程占用；GPU 使用率同理仅为整卡瞬时采样。
- 立即释放模式也验证通过：下一次合成结束即无驻留子进程。当前没有残留本次模型 worker；原有试听附件预览服务保留。
- QML 实际点击与键盘切换验证语言、设备、保存、页面导航及释放；浅/深主题与 360/800/1440 宽共 12 张截图。CPU/GPU 计算路径与 GUI Mock 交互证据分开，不宣称真人麦克风或扬声器出声验收。
- 相关离线回归 **82 passed**（后增设备隔离断言单独复验）；Ruff 全仓通过；wheel 的 **42 个 QML/图标/许可资源**及临时安装后的 QML 加载通过。
- 首次全库回归为 314 passed / 1 skipped / 2 failed：一个新进程树清理测试误拦截 taskkill，已修正并通过；另一个材料后台准备测试出现 5 秒等待超时，在后续相关回归中通过。保留这次失败记录，不把重试写成首次全绿。

[模型页截图](../../../build/local-speech-settings-validation/ui/desktop/model-library-dark-1440.png) · [计算页窄窗口截图](../../../build/local-speech-settings-validation/ui/desktop/speech-compute-light-360.png)。复现命令见 [本地语音指南](../../desktop/LOCAL_SPEECH.md)。未修改个人 `.env`、正常学习数据库或用户正在运行的应用；未触发付费 AI。

## 未完成项

- **GPU 环境全新下载未完成验证**：本机 PyPI 的 ORT GPU 大文件停滞，已停止自己的下载进程；未把残缺环境标记就绪。准备/取消流程及版本锁定已经实现，当前 GPU 功能验证复用既有固定环境与 DLL。CPU 的全新准备与两种实际 CPU 模型运行已通过。
- 独立 Melo 英文（Torch/BERT）、Kotoba 与 VOICEVOX 已评测，但产品后端、运行环境与声音许可 UI 尚待适配；当前产品不显示成已可选用。轻量中英 Melo ONNX 与独立英文模型分别记录。
- 会话前自动预热、冻结安装包的运行时分发、其他显卡平台、后台高 GPU 负载下体验，以及真人端点到出声、连续播放、打断与 LiveKit 连续链路仍需后续验收。
