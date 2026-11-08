# 三个桌面门面状态所有权治理验收

基准 `d72819c`，分支 `codex/desktop-state-ownership`。最终代码为 `899f570`；仅本地提交，未推送。逐字段的原写入方法、最终所有者、任务和资源归属见[迁移清单](DESKTOP_STATE_INVENTORY_2026-11-08.md)，架构选择见 [Decision 0046](../../decisions/TECH_DECISIONS.md#decision-0046)。

## 完成情况

| 门面 | 唯一状态所有者 | 结果 |
| --- | --- | --- |
| 语音库 | CatalogProjection、LibraryOperations、ResourceMonitor；下载保留 SpeechPreparationJobs | 已迁移；后台只接收冻结的目录、模型、语言／场景、计算配置和取消句柄，阶段／完成事件回主线程校验原身份 |
| LearningViewModel | MaterialProjection、SessionEditing、ReviewProjection、LearningOperations | 已迁移；属性 Mixin 只读取／委托，展示仍只经 present_conversation，业务回调使用原任务 ID，历史只读摘要 |
| Workspace | ImportEditor、WorkspaceNavigation、ReadingCoordinator | 已迁移；导入／文档／搜索分别失效，范围与预览不覆盖当前来源，按线程只保存不可变 ReadingPosition |

Qt 属性类型、读写性、通知信号、公开信号签名及槽重载固定在 tests/desktop/fixtures/facade-contracts.json。共享状态写入债务清单已清空；门禁禁止恢复门面可写别名、属性 Mixin 状态写入、完整门面／Qt 进入普通协作者，以及跨门面发送信号（包含别名）。快照嵌套容器只读，QML 值脱离所有者。

Workbench 继续独占会话与持久化写入。Workspace 通过 refresh_learning(ProjectionChange) 请求投影更新；确认清稿仍要求文本和版本匹配，新草稿不阻止有效回复。文档／搜索／导入任务使用既有 AsyncWorker，界面回调不进入后台。Qt 设备、播放、计时器及 ReaderBridge/profile 留主线程，模型服务仍由 ViewModel 清理；5 秒协作取消、15 秒总预算与失败重试不变。

补查修正了两项边界：自选测速 WAV 的 file: URL 在 Qt 主线程转换为本地路径后冻结；关闭后的设置／选用命令被拒绝。线程阅读恢复仅保存坐标和来源快照，不积累整本 ReaderBook、正文或章节。数据库结构、来源坐标、缓存身份、历史快照、QML 资源路径和固定 vendor 未改。

## 最终证据

以下路径相对仓库根目录，统一位于 `build/state-ownership/accepted/`，属于忽略的本地验收产物。

| 验收 | 结果与证据 |
| --- | --- |
| 完整离线 | **689 passed、10 skipped，306.92 秒**；原 679 项全部保留，新增 20 项；10 项原跳过原因逐项一致（真实 AI 1、本地语音 8、RTC 1）。offline-release.txt/xml、test-inventory.json、skips.json |
| 静态门禁 | Ruff、desktop/application F401、差异空白、Qt 契约、所有权、依赖和 vendor 边界通过。205 个自有生产文件、1752 个 Python 函数；最大文件 787 行、最大函数 100 行。size-audit.json |
| 文本／分轮语音／历史 | Windows 可见；明亮 100% 与暗色 150%，360／1180 宽；各 46 张截图，无 QML 执行错误。visible-light/report.json、visible-dark-150/report.json |
| 连续语音 | 14 张截图、4 次 Mock 对话；暂停、打断、保留草稿、失败恢复及停止通过，回调异常和 QML 错误均为 0。visible-continuous-report.json；结尾故障为主动注入的设备失败 |
| 阅读器 | 9 项检查、7 张可见截图；英中日、明暗、窄窗、字体、精确选段、复制、历史和离线 profile。visible-reader/report.json |
| 模型库 | 10 张截图、10 项实际滚轮检查；STT／TTS 页签、并行进度、独立取消及多种宽度通过。visible-model-library/report.json；传输与音频合成，未下载真实模型 |
| 托盘／退出 | tray、dialog、window 三入口各 6 项检查和 4 张截图，覆盖隐藏保活、恢复、策略回读及实际 worker 退出。visible-lifecycle/*-report.json |
| 实际进程结束 | 按 PID 与创建时间复核并排除系统 PID 复用，采集的 225 个宿主／所属子进程全部结束；复查无存活记录或遗留直属子进程，未结束任何用户进程。process-cleanup.json |
| 翻译／资源 | 原 684 个文本与上下文完全保留，编译通过；固定 vendor pin／逐文件哈希通过。translation-contexts.json；资源位置不变 |
| 最终 wheel | 全新目录按 Git 文件清单复制当前精确字节构建；138 项资源匹配、模块清单一致、无旧 OperationsMixin 模块；另逐字节核对 147 个 Python 文件。wheel-check.txt、python-byte-audit.json |
| 实际隔离安装 | uv pip install --offline --no-deps --target installed-final；Python -I 确认来自隔离包，QML 启动、材料／范围／对话／重启恢复，以及 CLI load／确认范围／start／say／finish／summary／quit 通过。installed-probe.txt、installed-cli-report.json |

wheel：`build/state-ownership/accepted/dist-final/shinar-0.1.3-py3-none-any.whl`。SHA-256：`825ee262d537b6458a0fe7de58f0b7c847dc87ec9afa6b7c1abb44380a188155`。

可见检查全程串行。保留了既有 FFmpeg 信息、WebEngine profile 弃用提示与软件图形回退日志；它们在本轮前的可见报告中也存在，不记作 QML 执行错误。profile 接口更新在 Qt／阅读器升级时另行处理，不改变本轮资源策略。隔离安装复用宿主依赖，不等同独立 Windows 分发验收。

## 分阶段交付

| 本地提交 | 内容 |
| --- | --- |
| `0c511e4` | 固定 Qt 契约、679 项用例基线与共享写入债务门禁 |
| `4c34273` | 语音库目录／操作／资源所有者、冻结请求及主线程结果接收 |
| `148af86` | 材料、草稿、复盘、具名业务操作及 refresh_learning |
| `ea8587e` | 导入、导航、阅读所有者及零债务门禁／架构契约 |
| `899f570` | 精简线程恢复记录、冻结测速路径及关闭后命令边界 |
| 最后文档提交 | 本记录、最终验收摘要及文档位置整理 |

分阶段证据位于上一级 build/state-ownership：语音库定向回归、ViewModel 56 项主路径及 24 项相关回归，Workspace 原 14 项与新增所有权回归，补查 26 项阅读／工作区／契约和 17 项请求／不可变性回归均通过；最终表格以固定源码重新运行的证据为准。

本轮未新增产品能力，付费模型调用为 0；使用临时库、INI、合成音频和 Mock，未修改个人配置、学习库或模型缓存。真实 AI、真人语音与新 Windows 安装器未验收，安装器未重建。
