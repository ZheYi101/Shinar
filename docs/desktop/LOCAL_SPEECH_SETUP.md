# 本地语音设置闭环

2026-10-30。当前范围为非冻结 Windows x64 桌面版。独立安装包、其他 VOICEVOX 角色及其他 GPU 平台另做。实际通过项目见[验证记录](../validation/engineering/LOCAL_SPEECH_SETUP_2026-10-30.md)。

## 使用

设置 → 本地语音模型，选择语言和用途。「准备 / 下载 / 继续」准备本模型的环境与权重，显示所需下载、磁盘空间、当前阶段及组件进度，可取消后继续。文件安装、环境验证、测速和选用分别显示；安装不自动替换当前模型。

VOICEVOX 首批仅提供ずんだもん，默认普通风格 3，其他普通风格核对固定 VVM 元数据。条款在页面内展开，确认绑定包指纹；试听和实际回复保留 `VOICEVOX:ずんだもん`。Melo EN 五种口音与 EN_NEWEST 分开，共享 BERT/前端；原 Lessac 选择保留。

切换候选声音后为它测速并点击选用。候选声音与实际已选声音分开，当前轮次使用冻结 profile；连续语音下次开始使用新绑定。显示语言、学习母语和目标语言独立。

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

`--device cpu` 可在计算页选择 CPU；`--voice-index` 检查声音切换；STT 使用 `--language` 和 `--wav` 指定有权使用的录音，验证器通过 FileDialog 的公开文件选择属性与 accepted 信号检验 QML 接线，不宣称覆盖系统文件选择器的手工操作。

普通设置选用模型后的连续链路验证可用 `scripts/validate_continuous_voice.py --speech-cache <cache> --runtime-root <voice-runtime> --cases ja`。真人窗口用 `scripts/validate_continuous_desktop.py --human --speech-cache <cache> --runtime-root <voice-runtime> --case ja`。这两个入口读取普通选择和测速报告，不调用 `register_prepared`；旧 `--profiles` 仍作为明确的开发探针接口兼容。
