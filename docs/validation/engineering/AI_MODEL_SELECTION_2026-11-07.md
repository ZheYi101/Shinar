# AI 服务模型下拉选择

日期：2026-11-07。范围：Windows 0.1.2 桌面与安装包。用户要求模型从服务目录选择，不再手填模型 ID；保留本地环境配置与已保存服务的重启生效行为。

## 行为与契约

- 先填写基础地址和密钥，点击「读取模型列表」。通过 Bearer 认证执行相对基础地址的 `GET /models`，使用响应 `data[].id`，不发送材料或请求生成。[官方接口](https://developers.openai.com/api/reference/resources/models/methods/list)
- 推理／对话均为常显、不可编辑的完整宽度下拉框；读取前禁用，读取后可通过鼠标或键盘选择。对话可以选择「与推理模型相同」。服务目录不提供能力分类，不按模型名称猜测能力或自动改选。
- 保存前验证模型属于当前服务返回的列表。修改地址或密钥使目录失效；读取期间不能保存，过期回调不能恢复旧服务的目录。
- 刷新按模型 ID 保留选择。原模型从目录消失时保留展示并提示重新选择，不能静默切到同索引的另一模型。空列表、权限失败与不支持接口均在页内反馈并允许重试。
- 旧界面保存项与环境配置仍可启动；更新安装包不要求重新配置已选模型。仅再次通过界面保存时要求读取目录。未提供模型列表接口的服务继续可使用环境配置，QML 不另开手写入口。
- 密钥仍使用 Windows 当前用户 DPAPI；配置仅重启后绑定到 provider，活动学习会话不改变。新增文案进入 Qt 翻译源，未引入依赖或新技术栈。

主要变更为 `desktop/shell/ai_services.py`、`qml/components/AIServiceSettings.qml`、`providers/service_probe.py`、对应测试及包内交互检查。读取目录逻辑沿用长期 asyncio worker；下拉框复用现有 `MComboBox`。

## 验证

普通测试均显式设置 `RUN_REAL_AI_TESTS=0`，仅使用假密钥、本机模拟 HTTP 和独立数据目录；不访问个人学习库，不调用付费模型，不自动重启用户正在运行的软件。

- 配置与模型目录的定向回归：**18 passed**，包括真实 QML 打开弹出列表、键盘选择、保存与下一次 provider 加载、空目录重试、服务编辑后拒绝旧模型、刷新按身份保留，以及 HTTP 认证／路径／去重与无效 ID 过滤。日志：`build/ai-model-select-tests.log`。
- 共享下拉框更新后的桌面回归：**23 passed**，`build/ai-model-select-shared-combo-tests.log`；Ruff 与 `git diff --check` 通过。
- 全量普通回归第一次为 **543 passed、10 skipped、2 failed**（241.67 s），失败均为中键滚动测试：模型页新增状态行后，360px 下实际列表视口仅 160px 高，固定移动 85px 会越过边界并正确触发停止。旧 0.1.1 源码对照两项通过，调试输出确认越界。测试改为按实际视口选择位移，原有死区、滚动、停止及点击断言保留，两项复验 **2 passed**（7.90 s）。本轮没有将两次结果写成一次全量全绿，日志分别为 `build/ai-model-select-full-tests.log`、`build/ai-model-select-baseline-source-scroll.log`、`build/ai-model-select-scroll-geometry.log` 和 `build/ai-model-select-scroll-responsive-check.log`。
- wheel：固定构建快照的 **135 项资源**与隔离安装后的 QML smoke 通过，`build/ai-model-select-snapshot-wheel-check.log`。构建期间存在其他任务的共享 UI／连续语音修改，初次资源校验拒绝了变化中的文件；交付物重建后以其固定快照校验，不把构建后其他任务的源码当作同一包。
- 实际 ZIP 解压到含中文与空格的目录，原生启动器及可见 QML 完成「读取本机 HTTP 模拟目录 → 打开两个不可编辑弹出列表 → 键盘选择 → 加密保存 → 重新加载真实 provider 配置」。验证恰好一个 `GET /v1/models`，无生成请求。明暗主题覆盖 360／600／800／1180／1440px；人工查看 360／1180px 弹出列表截图。报告和截图：`build/windows/api-model-selection-0.1.2-visible-20261107/`。
- 未配置的首次启动分别以 **125%／150%** 缩放执行同一流程，自动进入设置、下拉选择与重载通过；`build/windows/api-model-selection-0.1.2-first-run-20261107/report.json`。
- 独立安装、已安装程序 smoke、卸载返回码均 **0**，正常安装登记不变、外部数据保留、程序残留文件为 0；`build/windows/api12-install/report.json`。首次较长的验收目录触发 Qt 开发资源路径过长，Inno `MoveFile` code 3 并回滚；改用短验收目录通过。超长安装路径兼容与运行时裁剪仍需独立处理，不隐去该失败。

## 交付产物

构建目录 `build/windows/build-prjntvj5`，`BUILD.json` 时间为 `2026-11-07T11:56:27Z`；包是该时刻的工作树快照。后续并行任务的源码修改不自动进入本包。所交付的模型选择逻辑、列表控件与固定包内交互分别已验证。

| `dist/windows/` 文件 | 大小（字节） | SHA256 |
| --- | ---: | --- |
| `LinguaLoop-0.1.2-windows-x64-setup.exe` | 312071641 | `9a88cd17dc778fb4ba98fd6bba990272793618e295b2bf1d14bf18aa5bcfedbd` |
| `LinguaLoop-0.1.2-windows-x64.zip` | 359320812 | `49a77e33133931681945e9fd4a4812561ac422c569551020956b5b7a79778445` |

仍为未签名开发预览包，未执行干净 Windows 镜像矩阵。本次是模型选择改动，没有裁剪 Qt 或移除语音／阅读器功能。远端真实模型、付费质量与真人语音证据均不从这些工程检查推导。

实现与使用方式见 [Windows 分发指南](../../desktop/WINDOWS_DISTRIBUTION.md)，取舍见 Decision 0040。读取模型列表不代表验证了生成权限、余额、音质或响应延迟。
