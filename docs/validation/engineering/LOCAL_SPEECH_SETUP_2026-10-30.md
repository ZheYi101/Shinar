# 本地语音设置闭环实施记录

更新（2026-11-06）：用户明确要求整理提交，本次提交保存当前语音实现；下文历史提交门禁不再阻止该提交，真人设备验收和未通过项仍保留，最新证据见[交付自测记录](VOICE_HANDOFF_2026-11-06.md)。

日期：2026-10-30。状态：实施与验证中；未通过项目不计为交付。最终 commit 仍受原连续语音真人设备门禁约束。付费模型调用为 0。

实施前已有连续语音、纸纹、原文和装饰修改，快照在忽略的 `build/speech-settings-closure/baseline.patch` 与文件哈希清单中。

## 当前证据

- 相关离线基线 80 passed（64.21 s）。模型目录更新后，两条“VOICEVOX 不可下载”的旧断言按新范围修正。
- 模型及 QML 第二轮 90 passed（37.52 s）；环境和声音专项 17 passed（26.67 s）；相关回归 104 passed（97.25 s）。增加共享环境锁、磁盘失败和资源损坏检查后，最新相关回归 118 passed（209.70 s），含架构检查。最终全量待更新。
- 首轮全量为 411 passed / 10 skipped / 1 failed：Mock 会话启动等待在并行安装时超时；单独重跑 1 passed（14.67 s）。测试等待改为处理事件后释放 GIL。最终全量显式 `RUN_REAL_AI_TESTS=0`，415 passed / 10 skipped（527.33 s）。
- 独立空缓存 `fresh-core` 的 VOICEVOX CPU 完成 Python、引导工具、词典、专用 ORT 和 wheel 下载，通过 Synthesizer 初始化探针。这不是模型合成、可见 GUI 或人耳验收。资源身份增强后需重新准备就绪记录。
- 首次下载 TLS EOF，随后重试成功；公共下载增加有界重试和 Range 复用，不降低字节数/SHA256 验证。GitHub 元数据 API 限流后用公开 git ref 固定 NLTK 提交，不使用私人 token。
- 首次可见验证器的 QTest 等待使后台解包缓慢；停止本次独立验证进程，改为处理 UI 事件后释放 GIL，继续原独立缓存。该次未记为完成。
- 核查发现公用验证函数导入时设置了离屏模式。此前 VOICEVOX 的环境、权重、五次真实合成测速和选用属于离屏 QML 证据，不能计为可见验收。已将模式设置移入原脚本 main，并让新验证器拒绝 offscreen，报告记录实际 Qt platform。
- 用户释放内存后实测可用 7.07 GiB；VOICEVOX 单测准入约 3.5 GiB、Melo 约 5 GiB（均含系统余量）。安装与测速准入分开，低内存仍可准备下载。
- Melo 独立 CUDA 环境首次实际前端探针发现 SoundFile 通用 wheel 不含 Windows DLL；改为固定 SoundFile 0.13.1 Windows wheel，并补齐匹配的 Torchaudio。随后 Torch 2.9.1+cu128 实际 cuda:0 计算和英文前端导入探针通过。此项是无 GUI 的独立环境证据。
- 新空目录经原生 Windows QML 的音频设置完成 RTC/APM、Silero、SFU 准备（512352 ms）；报告 `qt_platform=windows`、不开麦、0 个 QML 错误。该环境解释器随后驱动真实本机 RTC 双 peer：合成 PCM 经 RTC 收到 181 个播放块，识别分支收到输入窗口，进程正常退出 0。这不是实际识别、真人听感或 AEC 门禁。
- wheel 中间构建通过 96 项资源与隔离 QML smoke。检查器增加逐字节身份核对，能拒绝 QML 更新后的旧 wheel；最终需重新构建检查。
- 原生 Windows QML 的 ONNX CPU / CUDA 从本次独立缓存准备成功，分别约 180115 / 1087555 ms；CUDA 通过实际计算探针，无开发 DLL 路径。VOICEVOX 在新原生窗口空目录准备环境后，模型下载连接中断；续传重试完成下载、五次真实合成测速和选用，0 个 QML 错误。Melo 可见 CPU 模型文件准备成功，但并行窗口时 RAM 准入阻止测速；不算合成通过。
- QML 文件选择对象命名更新后已重新构建 wheel；96 项资源身份核对及隔离安装 QML smoke 通过。最终 diff 检查没有空白错误。新增声音/组件文案已进入 Qt 翻译源；后续若有源修改再更新记录。
- 后续全量离线 416 passed / 10 skipped（343.78 s）；音频首轮修复后 422 passed / 10 skipped（298.46 s）。计算页快照修复后，全量显式 `RUN_REAL_AI_TESTS=0`：**423 passed / 10 skipped（170.15 s）**。Ruff 通过，翻译源 504 项；wheel 的 96 项资源与隔离 QML smoke 通过。
- 原生 Windows QML 中，Melo EN／EN_NEWEST 的 CPU 下载、五次热态测速、选用通过；CUDA 首次 2.7 GB Torch 下载在末尾 TLS 失败，重试复用下载后完成独立环境实际探针，两种模型五次测速并选用通过。GPU 运行环境准备约 349386 ms，两个模型完整测速操作约 54676 / 28879 ms；这些是操作耗时，不是模型单句速度。初次 CPU 环境离屏记录仍不改写成可见冷安装通过。
- 正常设置的 Reazon CPU + VOICEVOX CPU 与真实 RTC、Mock 对话完成三轮合成输入，未使用 register_prepared。SenseVoice FP32 GPU 经普通 QML 下载、实际测速并选用；2025 INT8 的中／英文 CPU 长语料测试未过平均 500 ms 准入，保留失败，不缩短语料或绕过门禁。
- 用户真人报告监听暂停和朗读未完成后，真实 VOICEVOX + RTC + 可见 QML／Qt 播放设备复现 `input_gap` / `output_overflow`。修正音频帧通知和隐藏计算页重复磁盘检查后，同样三段朗读排空、无故障，最大 GUI 间隔由 4673.9 ms 降至 26.3 ms。物理麦克风未开，输入为合成静音；真人耳机／扬声器仍待复测。详见[连续语音记录](CONTINUOUS_VOICE_2026-10-30.md)。
- 修复版最终 wheel 与当前源码逐字节比对 186 个包内文件，无差异；SHA256 `cf526156c011e8a485fee7c2d3500850286f37aeb2546e59f67da26d8c0ad100`。独立真人窗口已重新打开并保持未开麦，仍无真人通过声明，未执行 commit。

## 待完成门禁

| 项目 | 状态 |
| --- | --- |
| QML 从空目录准备 CPU/CUDA/VOICEVOX/Melo | 已取得原生 Windows 成功记录；初次 Melo CPU 环境离屏单列，不复制就绪记录或借用开发 DLL |
| 普通入口测速、声音选用、三语与重启 | 待完成 |
| 不同环境配对与共享资源 | 已接线，真实运行待完成 |
| 五档宽度、125%/150%、长文 | 语音修复版 70 个状态视图通过；设置模型页已有五档记录，完整设置交互仍继续核对 |
| Ruff、翻译、全量离线、wheel 隔离安装 | 音频修复后通过；423 passed / 10 skipped，资源 96 项 |
| 真人耳机/扬声器、回声、插话和设备恢复 | 沿用原连续语音待完成门禁 |

命令及接口见[设置指南](../../desktop/LOCAL_SPEECH_SETUP.md)。日志、模型、原始音频和机器路径仅留本机忽略目录。
