# Python 基础语音服务

2026-10-29。此增量提供无 UI 的转写、确认、对话、分句合成和 RTC 输入/输出。2026-10-30 已接入 QML 自动发送的分轮流程，见[桌面指南](./VOICE.md)；持续 PCM、VAD/APM 与插话取消的当前实现见[连续语音指南](./CONTINUOUS_VOICE.md)；真人设备门禁及独立安装包分发仍待完成。本地模型的普通下载入口见[设置指南](./LOCAL_SPEECH_SETUP.md)。实际结果见[基础验收](../validation/speech/VOICE_PYTHON_INTEGRATION_2026-10-29.md)。

## 应用入口

`application.voice_session.VoiceSessionCoordinator` 注入已有 `LearningWorkbench` 和 `core.voice` 的 STT/TTS 端口。协调器不读取 `.env`，不构造 LLM client，不导入 Qt、LiveKit 或推理库。直接传入既有兼容服务也可用。

```python
from shinar.application.voice_session import VoiceSessionCoordinator

async def receive_segment(segment):
    # Attach a real output adapter later; bytes are a PCM16 WAV at its actual rate.
    print(segment.index, segment.sample_rate, len(segment.audio))

voice = VoiceSessionCoordinator(
    workbench,
    stt=local_service.provider("stt"),
    tts=local_service.provider("tts"),
    on_audio=receive_segment,
)
draft = await voice.recognize(recorded_pcm16_wav)
# Nothing was sent to the LLM or added to learning history yet.
result = await voice.submit_confirmed(draft, edited_text=draft.text)
await voice.aclose()
```

- STT 输入要求 16kHz、mono、PCM16 WAV，最多 60 秒/24 MiB；输出草稿只在内存，最多保留 16 条。
- 草稿关联学习会话、目标语言与冻结的来源选区。换会话/语言后的旧草稿被拒绝；用户可在确认时编辑文字。
- `submit_confirmed` 默认以 utterance ID 幂等；`submit_text` 要求显式 `request_id`。同一 key 不允许换内容。重复完成请求返回已有文字，不自动重复朗读。
- 第一版只允许一个业务/语音操作；忙时返回错误，不排队或抢占。普通文字入口也不能在该语音操作内插入另一轮。
- `retry_reply(turn_id)` 重试已有用户消息；`retry_speech(turn_id)` 只重新朗读完整成功助手，不调用 LLM。旧 `send_message(text)` 在失败后重发同一草稿时也复用最后一个待答 turn。
- `on_text_delta` 是轻量同步通知；`on_audio` 是有背压的异步消费者。合成与输出失败不终止可成功完成的文字回答。
- `VoiceTurnResult` 分别给出 `text_status`、`speech_status`、`error_stage/code`、段数与计时。文本生成失败仍能拿到待重试 `turn_id`。取消属于任务取消，向调用方传播 `CancelledError`。
- 协调器默认不拥有外部 Workbench 或 backend；`own_backends=True` 才关闭注入的 backend。应用仍负责 `workbench.aclose()` 和共享 `local_service.close()`。

## 双角色与确认事务

确认后先保存用户，实际回答只通过 Workbench 的对话角色。普通回合不增加前台推理；明确核对原文的既有核验、后台信息缺口准备、来源边界、独立预算和 usage 继续保留。STT、草稿编辑和朗读重试不触发材料准备。

SQLite schema 2 新增 `conversation_turns`，以 `(session_id, request_id)` 唯一约束防重。确认事务写用户消息、事件和 turn；完成事务写完整助手、事件和状态。失败不保存助手半流。原会话 JSON 保持兼容，启动不会重放失败请求。

turn 保存确认前的历史 ID、来源 hash/范围、准备包及本地上下文。当前用户在 prompt 中只出现一次；版本匹配仍按确认前历史判断。后台不能以更短的旧 session 投影覆盖已确认消息。重试不包含后来发言；已被新发言接续的旧失败轮拒绝重试。

生成通过带 attempt 的领取/完成比较防止旧尝试提交。任务租约 180 秒，整个前台尝试（含显式核验）有 150 秒截止；正常失败/关闭立即释放领取。异常进程退出保留确认，未到期的有效租约不会被另一个实例直接抢走，过期后可显式重试。

`InMemoryEventStore` 也实现确认 repository，便于不使用 SQLite 的测试；已有直接 runner 的 event-store 调用仍兼容。

## 分句与音频口径

LLM 可见正文增量进入有界分句缓冲，TTS 在单独任务中顺序合成。支持中日句末、英文缩写/小数、Markdown 链接及代码块投影。没有强切定时器，正常完成才 flush 尾句。未合成文本上限 4096 字符；超限停止语音、保留文字，不无限排队。

合成与音频交付使用独立任务：上一段经过 RTC 或桌面播放背压时，下一段已可合成。`SpeechPlayoutBuffer` 对已完成波形（含正在交付的一段）限制为 3 段／24 MiB；正在构造的一段另受 `SpeechSegment` 的 24 MiB 上限约束。LLM 读取不等待这些队列。第一句立即进入合成，后续仅合并已到达的完整句子，每批目标不超过 240 字符，不等待未来句子，也不截断一个更长的完整句子。停止／插话取消预取任务及未播放波形，沿用输出代际拒绝旧音频。

`trim_speech_padding()` 只检查 PCM16 波形两端最多各 500 ms 的近数字静音，保留前 20 ms／后 80 ms 余量；不压缩内部停顿、不交叉淡化发音，也不改变语速、采样率或原消息。短音和全静音不强切。部分模型没有可安全裁剪的静音时，移除量为零。新增 `tts_compute`、`padding_removed` 计时均为毫秒，分别表示合成总计算和裁去的边界时长。

现有 WAV TTS 是分句合成，不宣称 native token/PCM streaming。VOICEVOX 与独立 Melo 英文 adapter 也按整句波形输出，可能比原实验中的首 PCM callback 更晚向应用交付。

- `first_audio_segment_ready`：第一段 WAV 在应用可用。
- `first_audio_segment_delivered`：第一段异步输出消费者完成，可能包含整段传输时间。
- `first_nonzero_rtc_pcm_ms`：测试从确认提交到对端首个非零 PCM，包含本次冷 TTS 等待；不是扬声器实际出声。
- 冷加载、热态 STT 算术平均、LLM 完成和合成计算分别记录；500 ms 筛选针对 STT 热态计算，不等于整条链路。

## 本地后端和冻结配置

`LocalSpeechService.provider(task).bind(language)` 在一轮开始解析一次目录选择、设备、运行时和报告，返回冻结的 profile。后续分句不重新读取选择，模型使用静态加载 key 复用；支持动态语言的 SenseVoice ORT、VOICEVOX style 与 Melo speaker 不各加载一套权重。不同 runtime Python、设备和权重属于不同实例。

独立模型进程继续接收内存 WAV/文本，主进程不导入 Torch、ORT、sherpa 或 VOICEVOX。STT/TTS 的加载预约共用一把准入锁，按 GPU 估算累加软预算及系统预留；不是 GPU 利用率限流或整体进程显存硬上限。

首批后端：SenseVoice ORT GPU、既有 sherpa SenseVoice/Reazon、Piper/Melo 中文；新增 `voicevox` 和 `melo_english` Python adapter。可选后端通过 `LocalSpeechProfile` 显式注册已准备环境，不自动扩展 GUI 下载目录，也不自动安装 Torch/声音包：

```python
import json
from shinar.local_speech.profiles import LocalSpeechProfile

profile = LocalSpeechProfile(
    task="tts", language="ja", package_id="voicevox-local",
    python=prepared_python,
    model_json=json.dumps({
        "id": "voicevox-local", "task": "tts", "language": "ja",
        "adapter": "voicevox", "provider": "cpu", "style_id": 3,
        "model_file": model_file, "onnxruntime": onnxruntime_dll,
        "license_accepted": True,
    }),
    attribution="VOICEVOX:ずんだもん",
    assets_json=json.dumps(verified_path_to_sha256),
)
local_service.register_prepared(profile)
```

注册验证 Python 存在、语言/任务一致、资产 SHA256 与必要条款。Melo 使用已固定和审阅的 runtime 前端与离线 BERT/G2P/NLTK；这些是运行时代码依赖，不执行模型包的入口脚本。`melo_source`、`frontend_source`、`bert_path` 及权重/config 都必须在 manifest 中验证。STT 显式 profile 还需既有合格速度声明，实际集成测试仍重新计算平均。

本机评测复用已准备环境；不代表全新安装/冻结发行包已经通过。VOICEVOX 署名随测试音频输出，已有接受范围仍是本地评测。

## RTC adapter

`realtime.voice_io` 提供：

- `send_wav` / `RtcWavInput`：限定对端 identity、topic、大小和超时的可靠字节流；完整结束才交付 WAV，断流/超限失败不会当作完整录音。输入本身不自动确认或调用 LLM。
- `RtcSpeechOutput`：可见文本合并发送，逐句 WAV 按真实采样率重采样成 48kHz mono PCM16，按 20ms 送媒体轨。分句独立生成，可在句末 flush；不是每个块重新初始化重采样。
- `start` 先等待对端 active；完整文字才能发送 text done；SDK 队列排空不代表物理设备已经播放。

本机 fixture 使用真实 STUN Binding responder。信令仅 loopback；媒体/STUN 可按用户明确选择绑定一个 OS 所属私网 IP，禁止 wildcard/public bind。先前纯 loopback 的失败保留，不能用私网通过外推纯 loopback 通过。详见 [LiveKit](./LIVEKIT.md)。

## pytest 与复现

普通回归不加载模型、不启动网络 fixture、不调用付费模型：

```powershell
$env:RUN_REAL_AI_TESTS='0'
uv run --locked ruff check src tests scripts
.venv\Scripts\python.exe -m pytest -q tests/application tests/kernel tests/providers tests/local_speech tests/realtime tests/infrastructure tests/test_architecture.py
```

真实集成需要已缓存且校验的 server、实际本地运行时/模型、公开录音和显式配置。没有资源时失败说明前置条件，不偷偷 Mock 或下载。测试配置为 JSON 数组，每项含 `name`、`language`、`wav`、`stt`、`tts`；两个 profile 是上面 `LocalSpeechProfile` 的字段字典，`model_json/assets_json` 为 JSON 字符串。样例名称为 `zh/en/ja/ja_reazon/en_melo`，本机配置留在 ignored `build/voice-python-integration/config.json`，不提交机器路径。

```powershell
$env:RUN_REAL_AI_TESTS='0'
.venv\Scripts\python.exe -m pytest -q tests/integration/test_voice_pipeline.py --run-local-speech --speech-config build/voice-python-integration/config.json
.venv\Scripts\python.exe -m pytest -q tests/integration/test_voice_pipeline.py --run-local-speech --run-realtime --speech-config build/voice-python-integration/config.json
```

底层复现命令为 `scripts/validate_voice_pipeline.py --config <config.json> --case en --output build/voice-python-integration/manual/en.json`，加 `--rtc` 验证真实传输。它使用 Mock 双角色 LLM、真实语音模型及独立测试库，不读 `.env` 或正常学习库。输出只含安全计时/设备/错误阶段，公开测试音频另放同目录。

## 2026-10-30：桌面接线接口增量

- `submit_text`、`submit_confirmed`、`retry_reply` 增加 `speak=True`，关闭时不绑定 TTS；旧调用默认行为不变。
- `submit_confirmed` 增加 `confirmation_kind="manual_transcript"`；桌面结束录音即授权自动提交，使用 `automatic_transcript`。
- 可选 `on_turn_confirmed(ConversationTurn)` 在事务成功后通知；`on_text_completed(SessionStepResult)` 在文本成功持久化后通知，无需等待语音完成。
- `stop_speech(turn_id)` 仅停止合成/音频消费者，保留对话 producer；`VoiceTurnResult.speech_status` 新增 `stopped`。回复结果保留安全 HTTP 401/402/429 错误码，不透传 provider 响应正文。
- `timings_ms` 补充 `text_first_delta`、`provider_ttft_ms` 与 `provider_total_ms`；桌面另记识别、UI 呈现和播放器启动。这些都不是物理扬声器出声计时。
