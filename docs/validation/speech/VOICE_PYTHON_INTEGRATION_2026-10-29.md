# Python 基础语音与真实本机 RTC 验收

日期：2026-10-29。范围：用户批准的基础 Python 增量，不修改 QML。本次使用 Windows / CPython 3.13.5、现有公开录音和已准备本地模型。硬件为 i9-14900HX、约 31.8GiB RAM、RTX 4060 Laptop 8188MiB，模型进程采用 2 CPU 线程策略；其他用户应用未隔离。双角色 LLM 使用 Mock，没有付费模型请求；测试库独立，不读取个人 `.env` 或正常学习库。

## 结果与范围

**已结束 WAV → 转写草稿 → 手动确认 → 持久化用户 → 既有双角色对话入口 → 分句合成 → WAV 或真实 RTC PCM 输出** 已贯通。真实 RTC 使用两个官方 SDK 参与者、本机 SFU 和真实 STUN responder。成功路径为一个本机所属私网 IPv4，信令仅 loopback；无公共 STUN/TURN、wildcard 监听或防火墙修改。

| 验证 | 结果 |
| --- | --- |
| Python 专项离线回归 | **278 passed，28.38s**；应用、kernel、provider、本地语音、RTC、SQLite、架构及原准备/对话验收 |
| 最终真实集成 | **9 passed，179.27s**；五组本地后端、三语 RTC 完整链路、双向 PCM/文本及退出重入 |
| Ruff | `src tests scripts` 通过 |
| 包含 UI 的全库回归快照 | **14 failed, 308 passed, 10 skipped, 13 errors，52.87s** |

全库失败/错误集中于当前工作区另有改动的 QML 界面和旧 UI 测试契约，例如缺少 `startDiscussionButton`、旧滚动和主题对象。此任务未改 QML、未放宽 UI 断言，不能宣称全库通过；该快照也不证明每项失败的引入来源。日志分别位于 ignored `build/voice-python-integration/{python-regression,final-real-integration,full-regression}.txt`。共享工作区同期存在其他修改，数量是当次运行快照。

## 后续合并校验

UI 任务完成测试迁移后，2026-10-29 合并工作区普通回归为 **353 passed, 10 skipped**，此前表中的 UI 失败保留为早期快照。完整范围和 wheel 检查见[合并检查](../engineering/WORKSPACE_INTEGRATION_2026-10-29.md)。这不改变语音冷启动或真人设备的未验收状态。

## 实现与测试约束

`VoiceSessionCoordinator` 只注入 Workbench、STT/TTS 端口和消费者，不依赖 Qt、RTC 或特定模型 SDK。识别不发模型对话、不写用户历史；文字和确认转写共用入口。同一 Workbench 的识别、回复和语音输出串行，忙时拒绝。关闭取消自有任务，backend 所有权显式指定。

SQLite schema 2 新增 `conversation_turns`：确认用户/事件/turn 原子提交，`request_id` 去重，完整助手/事件/完成状态再原子提交。失败保留用户，不写助手半流；重试回复复用原用户，朗读重试不调 LLM。覆盖迁移、回滚、旧快照防覆盖、attempt 比较、重启恢复；重启不自动调用模型。150 秒前台截止早于 180 秒持久租约。

语音沿用原双角色编排：对话角色产出实际正文，推理角色继续处理材料、背景和记忆。确认前历史、来源边界及准备包冻结，当前发言只进 prompt 一次；显式核验、后台版本判断、独立预算和 usage 保留。测试含 `reasoning_content`，只有可见正文进入 TTS。

LLM 读取与 TTS 分离，delta 不等待合成。按完整句末/换行切分，处理缩写和小数，正常结束 flush 尾句；未合成文字有界。TTS/输出失败保留成功文字，LLM 失败停止后续合成。输出为实际采样率的 PCM16 WAV；RTC 在边界转为 48kHz mono。录音只在可靠字节流完整结束后交给 STT，不猜测跨通道录音结束顺序。

本地配置按轮绑定，按静态实例 key 复用，动态语言/音色不重复加载。进程保持 RAM/显存软预算和空闲释放。首批贯通 SenseVoice、Reazon、Piper、中文 Melo，新增 VOICEVOX 与可选独立 Melo 英文 Python adapter。额外后端需显式准备、资产校验和许可声明；不等于 GUI 下载目录或全新安装包已支持。

## 本地模型实测

识别主路径为 SenseVoice 2024 FP32 CUDA，日语另测 Reazon CPU。五组均是真实录音与合成；每项两句输出，模型进程退出检查通过。单位 ms：

| 配置 | STT 冷加载 / 首次计算 | STT 热态三次均值 | TTS 设备 / 最后一句计算 | 确认到首段 WAV 可用，含冷 TTS |
| --- | ---: | ---: | --- | ---: |
| 中文 SenseVoice + Melo ONNX | 2681.07 / 204.59 | **44.11** | CPU / 419.07 | 3243.05 |
| 英文 SenseVoice + Piper Lessac medium | 3445.36 / 194.60 | **43.58** | CPU / 37.90 | 1259.34 |
| 日文 SenseVoice + VOICEVOX ずんだもん 0.17.1 | 2574.48 / 202.76 | **43.18** | CPU / 925.92 | 1528.63 |
| 日文 Reazon + VOICEVOX | 1294.06 / 227.51 | **207.02** | CPU / 955.39 | 1540.40 |
| 英文 SenseVoice + Melo EN-Newest | 3556.68 / 196.40 | **43.64** | CUDA / 102.37 | 11585.25 |

本轮热态平均为同一公开录音的三次计算，是接入回归门禁，不替代[此前严格评测](./SPEECH_GPU_JAPANESE_MELO_FOLLOWUP_2026-10-29.md)的多语料准确率、资源和尾延迟评估。这里 STT 为离线 final，没有 native partial；≤500ms 指热态计算平均，不是从开始说话到首字。冷加载和首次计算单独保留。

TTS 最后一句计时来自完整 WAV 返回。VOICEVOX adapter 暂未暴露原生首 PCM callback，不能直接与旧实验首 PCM 比较。Melo 英文的冷前端/BERT/权重加载明显慢，热态快不能掩盖首次等待；自动预热尚未实现。

## 真实 RTC 实测

| 完整链路 | STT 热态均值 ms | 确认到首个对端非零 PCM ms | 接收帧数 | WAV / 对端正文一致 / 清理 |
| --- | ---: | ---: | ---: | --- |
| 中文 SenseVoice CUDA + Melo CPU | 41.07 | 2669.76 | 140 | 通过 |
| 英文 SenseVoice CUDA + Lessac CPU | 42.99 | 962.74 | 98 | 通过 |
| 日文 SenseVoice CUDA + VOICEVOX CPU | 41.59 | 1581.04 | 183 | 通过 |

该首 PCM 从确认提交计时，包含冷 TTS 等待，未计入此前录音上传/STT，也不是扬声器实际出声。**当前整体冷链路没有通过一秒目标**：英文此次 962.74ms，但中文/日语及此前英文慢轮次仍超过一秒。三项均核对可靠流 WAV 字节、真实 STT、Mock 对话仅一次、顺序分句、对端完整正文与非零 PCM。

独立探针最终 UTC 为 `2026-10-29T10:58:32.234152+00:00`：client/worker/重入连接为 404.751 / 23.111 / 21.341ms；反向实收 51 帧、全部非零。文本顺序/完成、旧代际拒绝、取消后新轮次、显式退出重入、进程/socket 清理全部通过。此处取消是已有传输协议验证，不代表自然语音插话已实现。

### 定位与修复

此前“尚未观察到 native 创建”的外层超时结论不完整。后续历史诊断实际到达信令、SDP、候选收集，然后 ICE 超时；信令成功不能证明媒体连通。本轮改用真正的本机 STUN Binding responder，不再把 SFU RTC UDP mux 当 STUN，并给 server/SDK 显式端点，避免空列表继承默认公共 STUN。

严格 loopback 路径未通过后，使用用户已批准的一个 OS 所属私网地址。socket 审计确认 HTTP 仅 `127.0.0.1:17880`，SFU UDP 为选定私网地址 `17882`，独占 STUN 同地址 `17883`。纯 loopback 历史失败保留，私网成功不能外推纯 loopback 可用。

另修复两个生命周期问题：发送前等待指定对端 active，避免早期轮次标识丢失后被音频门拒绝；退出重入创建新 native Room，按 Room 身份隔离旧回调。没有放松旧事件拒绝规则。成功连接及实收媒体/数据构成连通证据；最终成功运行未开启完整 native trace，选中候选对明细未采集，不补造 ICE 内部阶段耗时。

所有模型 PID 和 RTC server 清理均检查通过。八组真实模型链路还在实际驻留 worker 中传入坏 WAV 与空合成文本，均拒绝并检查该 worker PID 已退出；后续不产生额外 LLM 调用。离线测试另用真实 Python 父/子进程验证硬超时清理，覆盖 Windows venv 启动器，不只检查 Python task 数。

## 复现与附件

```powershell
$env:RUN_REAL_AI_TESTS='0'
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m pytest -q tests/application tests/kernel tests/providers tests/local_speech tests/realtime tests/infrastructure tests/test_architecture.py tests/test_novel_preparation.py tests/test_prepared_dialogue.py tests/test_prepared_dialogue_acceptance.py
.venv\Scripts\python.exe -m pytest -q tests/integration/test_voice_pipeline.py --run-local-speech --run-realtime --speech-config build/voice-python-integration/config.json
```

普通 pytest 默认跳过重模型/监听。显式集成缺资源时失败说明前置条件，不换 Mock 冒充通过。配置格式及准备方式见 [Python 指南](../../desktop/VOICE_PYTHON.md)，本机绝对路径与 hash 清单留在 ignored 配置。

本地可复核产物（ignored，不随源码提交）：

- `build/voice-python-integration/local/{zh,en,ja,ja_reazon,en_melo}.json`：设备、冷/热计算、文字/语音状态、分句数与清理。
- `build/voice-python-integration/rtc/{zh,en,ja}.json`：WAV 一致、首个非零 PCM、正文一致、帧数与清理。
- 对应目录的 `<case>/segment-0.wav`、`segment-1.wav`：公开测试正文合成音；VOICEVOX 同目录 `ATTRIBUTION.txt` 保留 **VOICEVOX:ずんだもん**。这是本地评测授权，不代表产品再分发许可。
- `build/voice-python-integration/source-sha256.json`：本轮收尾时 Python 源文件与测试的 SHA256 快照。
- `build/livekit-probe/pytest-python-integration.json`：固定 server/SDK 身份、绑定审计、双向帧、取消/重入与进程/socket 检查。

## 未完成项

未实现或验证持续麦克风、端点/VAD、AEC、自然插话、自动重连、设备播放恢复、真人三语交互或冻结安装包。未新增人工听感/准确率评分。CPU/GPU 实际执行与实例复用已测，长时间压力、中文 Melo GPU 优化、Kotoba、自动预热及声音再分发仍需独立推进。QML 接线与当前 UI 回归失败留后续界面任务处理。
