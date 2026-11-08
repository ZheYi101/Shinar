# 验收与验证记录

- [对话页预检查与连贯朗读](engineering/VOICE_READINESS_AND_PLAYOUT_2026-11-07.md)：麦克风丢弃式诊断、本地模型预加载、有界预取及真实 RTC 段间提交对照；真人听感仍单列。

- [本地语音设置闭环（实施中）](engineering/LOCAL_SPEECH_SETUP_2026-10-30.md)：分类型环境、VOICEVOX/Melo 声音与真实下载验收。

本目录保存已经形成阶段结果的报告，按验证对象分类。日期和报告中的源码／产物版本决定证据范围；不同报告的测试数量不能当作当前工作区实时状态。失败、慢轮次和未验证事项照实保留。

## 文本与 AI

| 报告 | 已验证内容与限制 |
| --- | --- |
| [语义准备与双模型协作](./text/SEMANTIC_PREPARATION_2026-10-28.md) | 全书基础理解、部分范围安全复用、14 轮实际交流、12 场景三条件结果；100 次请求后停止，事实质量与一秒目标未过，独立真人盲评待做 |
| [完整小说验收](./text/NOVEL_ACCEPTANCE_2026-10-28.md) | 30 段实际准备、整书汇总、3 段共 17 轮实机交流、复盘和恢复；完整回复 1 秒未达，包含早期失败历史 |
| [自由聊天与部分阅读](./text/FREE_CHAT_2026-10-28.md) | 零模型初始索引、六轮实际自由聊天、阅读范围和缓存；语义召回不足，不代表新的基础理解方案已实现 |
| [双模型文本独立验收](./text/TEXT_ACCEPTANCE_2026-10-24.md) | 当时候选的真实 HTTP、后台包消费、性能与本机 RTC 探针限制；不是当前版本的完整语音结论 |

验收契约在 [AI 专项方案](../architecture/ai/PREPARATION_AND_DIALOGUE.md#10-可观测性与质量验收)。三条件实验已形成阶段结果，不能把有限实测或离线修正等同于完整质量验收。

## 语音

- [暂停麦克风并保留语音](./engineering/VOICE_PAUSE_2026-11-06.md)：手动暂停、续说、显式发送／丢弃和取消竞争；真实 RTC 合成输入与真人噪声环境分开记录。

- [下载界面、内置测速与语言选择](./engineering/SPEECH_DOWNLOAD_UX_2026-11-06.md)：并行任务、STT/TTS 列表、内置示例和测速并选用；区分离线、真实本地模型与待完成的真人门禁。

- [先自测再交付语音窗口](./engineering/VOICE_HANDOFF_2026-11-06.md)：真实 QML／STT／TTS／RTC 三轮与独立双向设备检查，保留自然播放结束后的队列超限失败及修正；真人门禁另列。

- [连续语音实施与验收](./engineering/CONTINUOUS_VOICE_2026-10-30.md)：持续 PCM／真实 RTC／VAD、自动提交、取消与 QML；明确区分真实模型、合成声卡与待完成的真人设备证据。

- [Python 基础语音与真实 RTC](./speech/VOICE_PYTHON_INTEGRATION_2026-10-29.md)：确认事务、双角色复用、分句合成、五组真实本地后端和三语 RTC WAV/PCM；未接 QML/持续设备，保留全库 UI 回归失败。
- [本地语音模型库阶段验收](./speech/LOCAL_SPEECH_ACCEPTANCE_2026-10-28.md)：目录、下载、固定包和本机计算验证；不代替真人音质或连续对话。
- [本地模型严格评测](./speech/LOCAL_SPEECH_STRICT_EVALUATION_2026-10-28.md)：34 个模型/语言配置、真人 CER/WER、首字/首 PCM 和双裁判回识；人工听感未评分，完整设备链路未验收。
- [逐模型资源与效果清单](./speech/LOCAL_SPEECH_MODEL_CATALOG_2026-10-29.md)：19 个模型/配置的语言、权重/目录/下载大小、RAM/CUDA 显存与逐语言计时，附离线试听包和识别对照；CPU/GPU 利用率未采集。
- [速度筛选与用户试听结论](./speech/LOCAL_SPEECH_SELECTION_2026-10-29.md)：此前 CPU 四项与后续 GPU / 日语候选、分语言 TTS 取舍、用户确认的 Amy 否定词错误及 VOICEVOX 首 PCM/整句完成澄清。
- [SenseVoice GPU、日语 STT 与独立 Melo 英文补测](./speech/SPEECH_GPU_JAPANESE_MELO_FOLLOWUP_2026-10-29.md)：32 个主配置和一个 GPU 负载对照，2880 次模型热态计时、380 次合成音回识；附 352 条 WAV、真实 CUDA trace、CPU / RAM / 整卡 GPU 资源与全部慢尾。
- [SenseVoice 2025 大小写与格式复核](./speech/SENSEVOICE_2025_FORMAT_AUDIT_2026-10-29.md)：逐条验证大小写早已忽略；双版本各 50 段进一步格式规范化后英语差距仍在。2026-11-06 用户决定将 2025 / WSYue 从产品目录删除，原版 2024 保留；历史测量与取舍记录留存。

运行方法见 [LiveKit](../desktop/LIVEKIT.md)、[分轮语音](../desktop/VOICE.md)和[本地语音](../desktop/LOCAL_SPEECH.md)。静态文档和离线测试不证明国内服务稳定性、设备出声或打断通过。

## 工程

- [桌面结构治理与审查修复](./engineering/DESKTOP_STRUCTURE_GOVERNANCE_2026-11-08.md)：递归门禁、偏好兼容、公开接口、连续通话状态所有者与 Python／测试目录治理，单列离线、可见 Mock 和 wheel 证据。

- [Shinar 完整工程更名](./engineering/SHINAR_RENAME_2026-11-08.md)：目录、包／命令、GitHub 和发行标识迁移，旧数据／配置兼容及离线、可见 Mock、wheel 验证。

- [Shinar 图标与侧栏字标](./engineering/SHINAR_IDENTITY_2026-11-08.md)：巴别塔图形出处、九种 ICO 尺寸、明暗窄窗 Mock 与新 wheel 资源验证。

- [治理迭代](./engineering/GOVERNANCE_2026-11-07.md)：职责拆分、退出、静态门禁及离线／可见 Mock／wheel 证据。

- [Windows 运行时裁剪](./engineering/WINDOWS_RUNTIME_TRIMMING_2026-11-07.md)：0.1.3 保留依赖闭包与完整产品功能，削减 Qt 调试／开发文件并验证旧版升级清理。

- [语音容量与准备进度规范化](./engineering/SPEECH_RESOURCE_DISPLAY_2026-11-07.md)：区分下载／安装余量／文件占用／RAM，单文件进度与完整准备状态，三处设置及独立 QML 检查。

- [API 模型下拉选择](./engineering/AI_MODEL_SELECTION_2026-11-07.md)：0.1.2 从兼容服务读取模型目录、双角色选择、失效与刷新恢复、QML 和更新安装包。

- [Windows 安装包与 AI API 设置](./engineering/WINDOWS_AI_API_PACKAGE_2026-11-07.md)：0.1.1 私有运行时、首次 QML 配置、当前用户密钥加密、125%／150% 缩放、迁移及独立安装／卸载；无付费模型调用。

- [EPUB 阅读器更换](./engineering/READER_INTEGRATION_2026-11-06.md)：固定 foliate-js、源文位置映射、可见 Windows Mock 拖选／复制／发送／历史、三语明暗／窄窗及 wheel 资源；真实用户 EPUB 与完整安装器另验。

- [Windows 图标、分发与对话使用体验](./engineering/WINDOWS_UI_DISTRIBUTION_2026-11-06.md)：440 项离线回归、107 项 wheel 资源、明暗／缩放 QML、ZIP 迁移与独立目录安装／卸载；不替代真人语音和最终人工视觉确认。

- [纸纹与背景装饰](./engineering/UI_ORNAMENTS_2026-10-30.md)：按原融合图修订的布面书、纸笺／胶带／淡印章、深浅主题离屏截图、17 项桌面回归和 86 项 wheel 资源检查。
- [浅色 QML 视觉复核](./engineering/UI_VISUAL_REVIEW_2026-10-29.md)：修订 3 与实际界面的差距、Qt 官方方案、叶控件与页面修正、三组对照图和缩放复查。
- [桌面 UI 实施与国际化入口](./engineering/UI_IMPLEMENTATION_2026-10-29.md)：工作树基线、阶段映射、线程／原文／草稿边界、中文翻译入口、可见 QML 合成音频及缩放检查，真实服务与连续语音分开记录。
- [语音与桌面工作区合并检查](./engineering/WORKSPACE_INTEGRATION_2026-10-29.md)：两批提交边界、353 项普通回归、原文真实 QML 交互和 67 项 wheel 资源检查；保留视觉/真人语音未验收限制。

- [代码审查](./engineering/CODE_AUDIT_2026-10-24.md)：对应候选的缺陷、修复及独立复核。
- [维护性检查](./engineering/MAINTAINABILITY_2026-10-28.md)：门禁、架构检查、实际回归及后续技术债。

## MVP 与早期闭环

- [初版验证](./mvp/INITIAL_VERSION_2026-10-24.md)
- [用户视角试用](./mvp/USER_TRIAL_2026-09-09.md)：CLI 与桌面 smoke，未做桌面手动点击，不作为后续实机验收替代。

## 新报告约定

写清材料及授权范围、模型／配置的公开身份、候选版本、证据类型、失败与未知项。原文、完整实际对话、截图、音频和模型调用元数据留在本地忽略目录；仓库报告只保存必要摘要与定位，不提交密钥、推理链或用户学习资料。
