# 本地语音设置闭环

2026-10-30。当前范围为非冻结 Windows x64 桌面版。独立安装包、其他 VOICEVOX 角色及其他 GPU 平台另做。实际通过项目见[验证记录](../validation/engineering/LOCAL_SPEECH_SETUP_2026-10-30.md)。

## 使用

设置 → 本地语音模型，选择语言和用途。「准备 / 下载 / 继续」准备本模型的环境与权重，显示所需下载、磁盘空间、当前阶段及组件进度，可取消后继续。文件安装、环境验证、测速和选用分别显示；安装不自动替换当前模型。

VOICEVOX 首批仅提供ずんだもん，默认普通风格 3，其他普通风格核对固定 VVM 元数据。条款在页面内展开，确认绑定包指纹；试听和实际回复保留 `VOICEVOX:ずんだもん`。Melo EN 五种口音与 EN_NEWEST 分开，共享 BERT/前端；原 Lessac 选择保留。

切换候选声音后为它测速并点击选用。候选声音与实际已选声音分开，当前轮次使用冻结 profile；连续语音下次开始使用新绑定。显示语言、学习母语和目标语言独立。

## 容量与内存显示口径（2026-11-07）

模型库、计算与加速、音频设备的准备区域统一使用以下名称：

| 名称 | 含义 |
| --- | --- |
| 模型下载文件 | 模型清单中下载资产的总字节数；含词表等，压缩包按压缩大小计，不等于安装后大小或 RAM |
| 预计下载 | 当前安装计划中尚无完整下载缓存的资产，含缺少的共享运行环境；估算不扣除断点文件已传字节，损坏缓存重新校验时可能增加下载 |
| 安装需可用空间 | 含下载、解包／安装临时副本及安全余量的保守磁盘准入估算；不是最终占用，不是内存需求 |
| 本地语音文件共 | 后台统计当前缓存根目录的文件逻辑大小，按已安装资源、下载与安装缓存、其他分类；硬链接只计一次，共享链接优先归入已安装资源，不跟随链接到外部目录，不等同于 NTFS 扇区分配量 |
| 模型安装文件／模型下载缓存 | 详情中的单模型文件大小；不重复分摊共享运行环境。缓存含保留的断点文件，安装文件按已有清单统计 |
| 运行内存（RAM）实测 | 来自本机匹配的测速报告，包含该报告的模型进程／引擎；不是全应用内存或未来上限，缺失时明确显示尚无实测，不能显示为 0 |
| 测速内存预留预算／显存准入估算 | 现有资源准入策略的估算，不冒充 RAM／VRAM 实测值或硬上限 |

容量在达到 1024 MiB 后以 GiB 展示，单模型原始清单与详情继续保留 MiB。模型库总占用属于本地语音缓存；音频设备页另统计数据库旁 `voice-runtime/`，两处均不包括软件安装目录、学习库和材料。状态是刷新时快照，任务完成／取消后重新统计，不在音频帧回调里遍历磁盘。

准备进度显示阶段、当前组件文件及该文件已传／总量，百分比只属于当前文件。文件达到 100% 后仍可能需要校验、安装和计算验证；只有完整准备流程结束才显示准备完成。连续语音使用同一阶段文案，明确区分运行库、Silero VAD 和 LiveKit，不把单个 wheel 下载完成当成整套组件就绪。

## 环境与兼容

- 计算与加速区分 ONNX CPU/CUDA、VOICEVOX CPU、Melo CPU/CUDA。VOICEVOX 本轮不开放 GPU；手动 GPU 失败不静默回退。Melo CPU 较慢，不能据可运行承诺完整回复一秒。
- 固定 Python 3.12.13、uv 0.11.14，只在语音缓存创建环境，不修改系统 Python、PATH 或注册表。Melo 为 Torch/Torchaudio 2.9.1、Transformers 4.57.3、SoundFile 0.13.1 Windows wheel；ORT 为 1.23.2，CUDA 运行库独立准备，不安装驱动。
- 包内 `runtime_resources/manifest.json` 固定地址、大小和 SHA256。先下载校验，再离线安装 wheels；推理期间不安装或下载。英文前端、少数纯 Python wheel 的源码及许可随资源分发。
- 修复在新候选目录执行，实际计算通过后原子切换就绪指针；失败保留原环境和有效下载。ONNX GPU 使用 CUDA MatMul profiling；Melo 使用实际设备上的张量计算，不以检测到显卡代替验证。
- 测速、试听、分轮和连续语音共用 profile。新声音报告绑定声音、前端、环境与设备；旧模型兼容记录保留。不同解释器的配对由独立常驻进程实测。
- 连续语音准备包含 RTC/APM Python 依赖、Silero 和 SFU，音频进程使用已准备解释器。桌面“已准备”要求环境探针及资产哈希通过，不能仅凭开发环境中可以 import SDK。准备不开麦。

## 验证命令

可见 QML 的真实下载使用独立学习库和缓存，不调用付费模型、不开麦：

```powershell
$env:RUN_REAL_AI_TESTS='0'
$env:PYTHONUTF8='1'
$env:QT_QPA_PLATFORM='windows'
.venv\Scripts\python.exe scripts/validate_speech_setup.py --runtimes cpu --packages voicevox-japanese
.venv\Scripts\python.exe scripts/validate_speech_setup.py --runtimes cuda,melo-cuda --packages melo-english-en,melo-english-v3
.venv\Scripts\python.exe scripts/validate_speech_setup.py --packages= --continuous
```

默认创建忽略的 `build/speech-settings-closure/qml-<id>`；`--root` 继续同一次验收。CLI 准备、可见 QML、合成音频和真人设备分别记录，不修改个人配置或正常学习库。

`--device cpu` 可在计算页选择 CPU；`--voice-index` 检查声音切换；STT 默认按 `--language` 使用随包示例，不要求准备录音。可选 `--wav` 改为自有录音，此时验证器通过 FileDialog 的公开文件选择属性与 accepted 信号检验接线，不宣称覆盖系统文件选择器的手工操作。

普通设置选用模型后的连续链路验证可用 `scripts/validate_continuous_voice.py --speech-cache <cache> --runtime-root <voice-runtime> --cases ja`。真人窗口用 `scripts/validate_continuous_desktop.py --human --speech-cache <cache> --runtime-root <voice-runtime> --case ja`。这两个入口读取普通选择和测速报告，不调用 `register_prepared`；旧 `--profiles` 仍作为明确的开发探针接口兼容。


## 并行下载与语言选择（2026-11-06）

模型页按「语音识别 STT」和「语音合成 TTS」分栏切换。列表默认保留模型、设备、文件／环境／测速／选用状态；声音、资源说明和许可证在「详情与声音」展开。语言和用途筛选固定在列表上方，滚轮只滚动模型列表。

模型列表支持中键自动滚动：点一下滚轮中键后，上下移动鼠标控制方向与速度，再点中键或按 Esc 退出；也可按住中键拖动，松开即停止。切换分类、离开列表或窗口失去焦点时停止，普通滚轮与模型按钮仍可直接使用。

可以连续为多个 STT、TTS 模型添加任务，最多同时处理 3 项，其余等待。每项显示模型、语言、阶段、当前组件文件、文件已下载／总字节及传输速度，分别取消、继续或重试。共享文件按 SHA256 互斥并复用，运行环境按类型等待；不重复下载共享文件，不同时改写同一个环境。百分比属于当前文件，不作为整个模型和环境的总体进度。完成后仍需测速并选用，下载不会自动替换当前模型。

已选模型按「会话语言＋用途＋STT/TTS」保存。英语会话不能直接使用日语 Reazon／VOICEVOX 的选择。聊天的缺模型、缺环境和缺测速提示会指向具体语言与任务，并可打开相应语言的设置；当前会话语言不随设置页筛选改变。缺少 TTS 时连续语音仍可识别、发送和生成文字，并明确显示未启用朗读。

普通操作仍使用原 `busy` 汇总状态；QML 的 `operationBusy` 仅代表刷新／测速等串行操作，不能拿它阻止独立下载。`downloadJobs` 是稳定的列表模型，提供 `cancel(job_id)`、`retry(job_id)`、`clearFinished()`；进度只更新对应任务，不重建候选模型行。关闭程序会取消任务，保留可校验的已下载部分；重启后通过「下载模型／准备环境」继续，不自动启动下载。

布局与交互验证入口：

```powershell
$env:RUN_REAL_AI_TESTS='0'
.venv\Scripts\python.exe scripts/validate_speech_download_ui.py --visible --output build/speech-download-ui
```

这个入口使用独立库、合成下载进度和 Mock 服务，不代表重新下载真实模型或真人语音通过。最新证据见[下载与错误提示验收](../validation/engineering/SPEECH_DOWNLOAD_UX_2026-11-06.md)。

## 内置测速与选用（2026-11-06）

普通测速和配对测速默认使用包内的中文／英语／日语 FLEURS 公开示例，不联网取音频、不录麦克风，也不要求寻找本地 WAV。示例固定版本、SHA256、16 kHz 单声道 PCM16，来源、原句、转换及 CC BY 4.0 署名随包保存在 `benchmark_samples/`。其他语言尚未附示例，明确提示后可在「详情与声音 → 使用自己的录音测速」使用有权使用的录音。

首次点击「测速并选用」，实际测速成功且符合对应用途的准入要求才保存选择；取消、失败或识别速度未达标均不替换原选择。已有报告的模型可「选用」或「重新测速」；后者只更新报告。下载完成只说明文件已安装，不代表已选用。顶部同时显示当前语言／用途的 STT 和 TTS，材料转录、朗读的选择不会冒充实时对话选择。

模型页筛选不改变当前学习会话语言。比如英语会话需要保存 `en:conversation:stt`／`tts`，日语选择不用于英语。显示语言、学习母语、目标语言和测速素材均独立。内置示例用于速度及基本非空检查，不能代表个人麦克风准确率、完整语音延迟或真人听感验收。

2026-11-06：按用户决定，SenseVoice Small INT8（2025 / WSYue，`sensevoice-int8-20250909`）已从产品目录删除，所有语言和用途都不再列出、下载或选用，不保留手动备选。原版 SenseVoice 2024 INT8 CPU／FP32 GPU 保留。若旧设置仍指向已删除模型，会提示选择失效，需要重新选用现有模型。历史评测与已有缓存文件保留，不改写学习记录；[格式与质量复核](../validation/speech/SENSEVOICE_2025_FORMAT_AUDIT_2026-10-29.md)仅作为淘汰依据。

同日按用户试听结论，MeloTTS 中英 ONNX（`melo-zhen-onnx`）仅保留中文，不再出现在英语的对话或朗读列表，旧英语选择也不能用于合成。中文的已安装文件、测速与选用记录继续有效；英语可重新选用 Lessac 等现有声音。独立 Melo English EN／EN_NEWEST 是其他模型，此次不调整。
