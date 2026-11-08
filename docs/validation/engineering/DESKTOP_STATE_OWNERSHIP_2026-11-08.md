# 三个桌面门面状态所有权治理

基准为 `d72819c`，分支 `codex/desktop-state-ownership`，仅本地提交。原始用例收集为 679 项，Qt 属性类型、读写性、通知信号和公开信号／槽重载固定在 `tests/desktop/fixtures/facade-contracts.json`。原始状态写入清单及收集记录位于忽略的 `build/state-ownership/`。

逐字段的原写入方法、最终所有者和资源／任务责任见[迁移清单](DESKTOP_STATE_INVENTORY_2026-11-08.md)。

## 迁移清单

| 门面 | 原共享状态 | 目标所有者 | 状态 |
| --- | --- | --- | --- |
| 语音库 | 模型行、硬件、容量、运行环境、语言与场景 | CatalogProjection | 已迁移 |
| 语音库 | 忙闲、进度、错误、安装／测速请求 | LibraryOperations；下载仍由 SpeechPreparationJobs 管理 | 已迁移 |
| 语音库 | 资源扫描身份、启停、扫描线程 | ResourceMonitor | 已迁移 |
| LearningViewModel | 材料／话题筛选、准备轮询 | MaterialProjection | 已迁移 |
| LearningViewModel | 草稿、版本、会话草稿、展示代际 | SessionEditing | 已迁移 |
| LearningViewModel | 反馈与复习 DTO、操作回调与重试 | ReviewProjection、LearningOperations | 已迁移 |
| Workspace | 导入编辑、文件预览、导入代际 | ImportEditor | 已迁移 |
| Workspace | 路由、侧栏、展开、编辑位置 | WorkspaceNavigation | 已迁移 |
| Workspace | 当前阅读、范围编辑、历史预览、搜索与文档身份 | ReadingCoordinator | 已迁移 |

语音库线程只持有 LibraryRequest（路径、序列化模型、语言／场景、计算配置）和自己的取消句柄，不持有 Qt 门面。LibraryEvent 保留原任务身份，Qt queued signal 回主线程校验后更新唯一所有者。阶段／完成／资源扫描均走具名事件。后台完成不等于当前请求有效，取消／重试／停用监测／关闭后旧事件不生效。快照嵌套容器冻结，QML 返回脱离所有者的列表与字典。

Qt 播放器、设备和计时器仍在语音库门面。模型服务沿用 ViewModel 的关闭链，语音库只等待自身操作线程、扫描线程及既有下载队列实际结束。刷新合并为一次待执行请求，测速结果仍归原语言／场景，未改变安装原子发布与 ready 指针规则。

## 分阶段证据

- 基线提交 `0c511e4`：Qt 契约、共享写入债务门禁；11 项相关检查通过。
- 语音库：原相关回归 32 项通过，修正一个原来绕过目录所有者的试听夹具后，定向回归另 18 项通过；覆盖真实 QML 下载／测速／选用、并行队列取消重试、资源显示及快照／晚到结果／实际线程退出。Ruff 与 desktop/application F401 通过。测试与脚本补丁迁至实际工作模块，删除 OperationsMixin。

最终离线、可见 Windows Mock、翻译／vendor、wheel 与隔离安装证据将在全部迁移后补齐。真实 AI、真人语音及 Windows 安装器未验收。

- ViewModel 阶段：对话展示、文本／分轮语音与桌面主路径 56 项通过；操作身份、草稿／复盘不可变快照、原治理回归及工作区兼容共 24 项通过。sessionHistory 仅使用摘要，不再触发整库正文读取。workspace 通过 refresh_learning(ProjectionChange) 请求投影更新。

- Workspace 阶段：原阅读器／工作区 14 项、原治理／共享场景／Qt 契约 20 项、架构与体积边界 29 项通过；新增 5 项覆盖导入标题版本、输入冻结、独立身份、不可变嵌套容器以及范围／预览／线程恢复。共享写入债务降为零；旧状态字段别名、协作者 Qt／完整门面依赖均加入门禁。

首轮完整离线为 687 passed、10 skipped（293.74 秒），原跳过原因不变；补查后的 Qt 契约／展示／阅读所有权 41 项通过。后续发行验收使用最终源码重新执行完整离线。

补查收尾：每线程恢复改用不可变 ReadingPosition，仅保存坐标、开关和序列化来源快照，不保留整本显示书籍／原文／章节。自选测速 WAV 的 file: URL 在 Qt 主线程转换为本地路径后冻结，工作线程不再接触 QUrl；关闭后拒绝安装配置与选用命令。增加相应回归，阅读／工作区／契约 26 项、库请求与不可变性等 17 项通过；收紧后的库／契约另 11 项及体积 8 项通过。最终发行证据将重新采集至 build/state-ownership/accepted/，不以早期 wheel 代替最终产物。
