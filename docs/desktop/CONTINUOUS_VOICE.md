# 连续语音

2026-10-30：已接入持续 PCM、真实本机 LiveKit、Silero VAD、自动提交与插话取消。**真人耳机、扬声器回声和自然插话验收尚未完成；代码、Mock 和合成声卡结果不能替代这些验收。** 本轮付费模型调用预算为 0。

## 启用

```powershell
uv sync --dev --extra desktop
uv run --extra desktop lingualoop-desktop
```

设置 → 音频设备 →「准备连续语音组件」显式准备独立 RTC/APM 解释器、依赖、Silero ONNX／MIT 许可证与固定 SFU；下载与磁盘需求以页面清单为准。缓存位于数据库旁的 `voice-runtime/`，不写入学习数据库；开始语音只校验已有资产，不下载。STT/TTS 模型沿用原设置，不自动安装模型或修改驱动。

开始语音先绑定会话目标语言、按现有资源策略准备当前模型对并连接，再开麦。默认停顿 650 ms，可设为 1000 ms；没有原生 partial 时只显示监听状态。有效识别自动提交，不经过转写确认。

点击开始或恢复监听时检查 `QMicrophonePermission`；未决定时请求授权，拒绝时保留文字入口，取消语音后的迟到授权不能再开启采集。Windows 桌面应用还受系统「允许桌面应用访问麦克风」开关控制，Qt 返回允许并不证明硬件可以打开；权限或采集失败时提供「打开系统麦克风设置」。参见 [Qt 权限流程](https://doc.qt.io/qt-6.11/permissions.html)及 [Windows 麦克风设置](https://support.microsoft.com/en-us/windows/privacy/turn-on-app-permissions-for-your-microphone-in-windows)。

冷启动分别显示加载识别模型、加载朗读模型和连接语音；这些阶段尚未开麦。采集传输中断、长度上限、选中设备变化、播放设备失败、待播队列超限及合成失败使用不同提示。音频不完整时暂停并丢弃未提交句段，不把丢帧当自然停顿。新增或切换无关设备不暂停当前选中设备。

| 操作 | 行为 |
| --- | --- |
| 静音麦克风 | 停设备采集和自动确认，丢弃未提交半句；已提交消息保留，AI 可继续回复 |
| 发送文字 | 先静音；草稿始终可编辑，提交后仅清除同一份草稿 |
| 停止朗读 | 清播放队列和后续合成，文字继续生成 |
| 停止回复／自然插话 | 清设备和 RTC 缓冲，取消旧生成；用户消息保留，助手半流不保存 |
| 停止语音 | 停采集、朗读与未完成回复，关闭连接，学习对话保持打开 |
| 重试朗读 | 仅合成已有完整回复，不调用 LLM |

连续语音期间锁定业务线程切换、新建与复盘，允许浏览材料、原文、设置和编辑草稿。缺少 TTS 仍可识别并发送，分轮录音作为独立入口保留。

## 架构与数据

- Qt 主线程通过 `QAudioSource`／`QAudioSink` 的 `QIODevice` 接口搬运有界音频。设备 ID 固定，移除设备后不自动改为默认扬声器。
- 独立 `AudioSessionWorker` 拥有两个 RTC peer、APM、VAD 与状态重采样器。GUI 不加载 ORT、Torch 或 CUDA，CPU ORT 只在音频进程加载。
- 麦克风：Qt → AEC → Desktop peer → SFU → Engine peer → VAD → 既有 STT／Workbench；回复反向经过 RTC → Qt。正式链路失败不使用内存传输替代。
- 内部 48 kHz／mono／PCM16／10 ms；VAD 16 kHz／512 样本及独立循环状态。声卡和 TTS 的实际采样率经有状态转换。
- AEC 参考来自写入设备的真实帧；应用输出增益为 1，依据队列估计采集／播放延迟。软件提交与延迟估计不能冒充可听证据。[APM 官方接口](https://docs.livekit.io/reference/python/livekit/rtc/apm.html)
- 软件待播 PCM 上限 3 秒、RTC 队列 100 ms、Qt 请求缓冲 60 ms，实际值由设备决定。插话调用 `reset()` 清设备缓冲。[Qt 官方接口](https://doc.qt.io/qt-6.11/qaudiosink.html#reset)
- 输入最多 60 秒／24 MiB；已结束待识别句段不累积后续静音。续说提高同一句段的版本，等待旧识别清理，只有最新版本能认领提交。
- 事件携带语音会话身份；输入另带麦克风代际，输出带回复代际。静音恢复、断线或停止后的旧事件不能提交或播放。
- 首次句段结束时冻结原文快照，续说和重试沿用。音频、未提交转写及失败半流只在内存暂存。
- 取消与完整回复提交按事务顺序决定。取消先完成则拒绝晚保存；文字先保存则只标记声音中断。取消及播放状态通过既有 JSON 兼容保存。
- 一次开启意图最多重建一次连接，之后需手动恢复监听；设备变化暂停并重建设备／AEC。重启不自动开麦或重发。

SFU 信令只绑定 loopback，媒体使用一个本机所属 RFC1918 地址和显式 STUN responder，不开放 wildcard、公网或修改防火墙。端口占用失败，只清理本应用创建的进程树。详见 [LiveKit 指南](LIVEKIT.md)。

## 验证命令

```powershell
$env:RUN_REAL_AI_TESTS='0'
# 已准备并校验的本地 profiles，格式沿用 Python 语音验证工具。
.venv\Scripts\python.exe scripts/validate_continuous_voice.py --profiles <profiles.json>
# 可见 QML、合成声卡／RTC，不属于真人设备证据。
.venv\Scripts\python.exe scripts/validate_continuous_desktop.py --visible
# 真实本地服务和声卡，独立库／设置；启动后尚未开麦。
.venv\Scripts\python.exe scripts/validate_continuous_desktop.py --human --profiles <profiles.json> --case ja
# 可见 QML、真实 RTC/播放设备、合成静音采集；物理麦克风始终不开启。
.venv\Scripts\python.exe scripts/validate_continuous_playback.py --runtime-root <已准备的 voice-runtime>
# 可加 --speech-cache <普通设置缓存>，改用已选用的日语本地 TTS 播放三段测试句。
# 先自测，再留出真人窗口：三轮真实识别/合成/RTC + 真实耳机麦克风双向检查。
.venv\Scripts\python.exe scripts/validate_voice_handoff.py --speech-cache <普通设置缓存> --runtime-root <已准备的 voice-runtime>
```

脚本使用已准备的 `build/continuous-voice/runtime`，不下载模型、不读取 `.env`、不请求付费服务。真人模式需实际选择设备、点击开始、发声和试听；计数不自动宣告真人验收通过。UI 导入、范围确认和开聊通过真实 QML 完成，不注入数据库历史。

验收窗口的对话服务是 Mock：每轮播报递增编号，并轮换不同测试句；它不理解或评价用户发言。界面同时显示 Mock 提示，真实 STT／TTS 和 RTC 仍按所选配置运行。编号用于辨认重复提交与重播，不用来证明对话模型质量；Python 回调异常单独记录，正常段间的 Idle／Underrun 不作为播放故障。

输出位于忽略的 `build/continuous-voice/`。profiles 含本机路径，只留本机。真人确认文本保存在独立测试库，原始音频不落盘；报告仅含状态、计数、耗时和安全错误类型。公开截图仅用合成材料。最新证据见 [本轮记录](../validation/engineering/CONTINUOUS_VOICE_2026-10-30.md)。

PCM 入队只在播放状态改变时通知界面。组件检查有独立通知，运行环境与安装计划由设置 worker 生成快照；推理状态不能触发隐藏设置页的磁盘检查。桌面最多保留 32 条内存故障摘要，含错误码、阶段、采集待发字节和时间，不含录音、转写或服务异常正文。

`validate_voice_handoff.py` 当前验证普通设置中已选用的日语模型，不安装模型、不改个人配置。先用合成 PCM 作为输入，在可见 QML 中点一次开始语音并完成三轮真实 STT/TTS/RTC、真实输出和草稿保留，检查停止及重试朗读不增加对话请求。随后短暂开启实际麦克风并同时播放测试句，只统计采集块、字节数及峰值；该阶段不转写、不保存录音，不当作真人/AEC 通过。所有自测通过后创建新的测试线程，恢复真实采集桥，麦克风保持关闭，标题改为「可以复测」；失败不进入真人就绪状态。`self-test.json` 与后续真人记录分开，后者记录自动化模型调用基线。
