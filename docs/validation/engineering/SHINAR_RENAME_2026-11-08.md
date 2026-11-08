# Shinar 完整工程更名验收（2026-11-08）

## 范围与交付

用户要求项目目录、包名与 GitHub 名称一并迁移。正式名称为 Shinar，原典出处和品牌图形分别见[命名记录](../../product/NAMING.md)及[图标说明](../../../src/shinar/desktop/assets/README.md)；技术兼容策略见 [Decision 0044](../../decisions/TECH_DECISIONS.md#decision-0044)。

| 对象 | 当前状态 |
| --- | --- |
| 工作树 | `D:\code\project\Shinar`，包含原 `.git`、源码、忽略的本地文件和构建记录 |
| GitHub | [ZheYi101/Shinar](https://github.com/ZheYi101/Shinar)，原仓库原地更名，ID 仍为 `1346847550`，默认分支仍为 `main` |
| Git remote | `origin` 为 `https://github.com/ZheYi101/Shinar.git`，`ls-remote` 已验证 |
| Python | 分发／导入名 `shinar`；`src/shinar`；旧导入包不再安装 |
| 命令 | `shinar`、`shinar-desktop`，新路径下的 console launcher 均已验证 |
| 应用标识 | 窗口／托盘／组织名 `Shinar`，Windows AppUserModelID `Shinar.Desktop` |
| 翻译及发行源文件 | `shinar_zh_CN.ts`／`.qm`、`Shinar.exe` 启动器配置、`packaging/windows/Shinar.iss` |
| 配置与全新用户库 | `SHINAR_*`，Windows 默认 `%LOCALAPPDATA%\Shinar\shinar.sqlite3` |

当前源码、测试、CI、命令示例、资源路径与运行文档已同步；阅读器内部对象改为 `window.shinarReader`，字体别名为 `ShinarSC`／`ShinarJP`。原典、历史报告、固定第三方文件和旧发行产物保留真实名称与坐标。

## 兼容与数据边界

- `shinar.configuration` 集中回读旧 `LINGUALOOP_*`；显式新变量优先，包括空值。子进程环境先移除敏感凭据，再规范化旧变量。
- 已有旧数据库、相邻 EPUB 原件和模型缓存原位复用；新用户采用 Shinar 目录。已有 AI 配置和打包 `.env` 可以回读，不复制密钥或自动移动个人学习库。
- Qt 偏好逐键优先新值、回读旧值，只向新命名空间写入；测试使用隔离 INI。
- 独立模型进程不依赖宿主 Python 包。固定 Melo 支持包所需的旧私有变量由两个适配器提供，第三方归档和哈希不变。
- 未编辑个人 `.env`；检查确认仓库内个人 `.env` 与 VS Code 设置不含旧根目录绝对路径。迁移后按锁文件重新安装虚拟环境，修复 editable 路径和所有 console launcher；为新根目录增加了精确的 Git `safe.directory` 项。

13 项更名兼容测试覆盖变量优先级、旧库与 EPUB 资产、缓存、AI 配置、Qt 偏好、子进程凭据过滤、独立模型依赖及新分发入口。分发配置测试同时覆盖 CI 中设置 `SHINAR_DATA_DIR` 时的隔离。

## 验证证据

- 完整离线回归：**632 passed，10 skipped，355.33 秒**；`RUN_REAL_AI_TESTS=0`，使用 `build/rename-shinar/test-data` 隔离目录，JUnit 为 `build/rename-shinar/offline-final.xml`。
- Ruff 与差异空白检查通过；维护性、依赖边界、固定 vendor 完整性包含在离线测试中。阅读器内部名称与探针修正后的定向回归另为 **50 passed**，覆盖架构、维护性、EPUB、阅读状态及更名兼容。
- 可见 Windows Mock：浅色 360／1180px 共 46 个画面，覆盖材料导入、文本、分轮语音、复盘和历史。深色 360px 连续语音另有 7 个画面，覆盖暂停／续说、草稿保留、打断、识别失败和麦克风失败；回调错误与 QML 错误均为零。读取实际截图核对字标、图形与宽窄窗口。
- 可见 Windows 阅读器：实际拖选／复制／发送／历史、分栏缩放与搜索通过；中日英三语、明暗和宽窄窗口字体已加载、无横向溢出，私有离线 profile 检查通过。阅读器内部名称同步后重新执行该探针。
- 新 wheel：`build/rename-shinar/dist/shinar-0.1.3-py3-none-any.whl`。隔离安装后的 QML／窗口控件启动通过，138 项资源与源码匹配；wheel 不含旧 `lingualoop/` 包，新分发元数据与翻译资源存在。SHA-256：`1e87143bd5a77bc94f36c4fa63fb0b1d5796af147194850d7944dbfd05f69f7b`。

本地证据集中在 `build/rename-shinar/`：`workspace-visible/report.json`、`continuous-visible/report.json`、`reader-visible-serial/report.json` 及对应 PNG；连续语音的原始报告还保存在 `build/continuous-voice/desktop-4f75c4c36d684393a538f4199e308446/report.json`。相对文档链接检查无缺失，资源中的字体与许可证保留原始文件名。Qt 输出保留图形上下文回退等诊断。

保留的失败：新根目录下阅读器两次检查因原生窗口失去焦点而触发截图保护，没有计为通过。首次失败还暴露了探针在窗口销毁后继续刷新并无法退出的问题；已增加对象有效性检查、完成时退出和详细错误记录。最后单独运行完整探针通过；失败报告、`reader-final.log` 与成功的 `reader-serial.log` 均保留，不将焦点问题归因于业务失败或忽略截图保护。

## 未决与限制

Windows 阻止直接重命名被占用的根目录，因此完整工作树逐项迁入 Shinar；旧 `D:\code\project\LinguaLoop` 仅剩空目录，当前会话仍占用。自动审批拒绝了清理旧生成元数据及空目录的删除命令，工具仅给出 `blocked by policy`；旧生成元数据已改用安全移动归档到构建目录，空目录清理待占用释放。应在 Codex／编辑器中重新打开新项目路径；本轮未修改 Codex 的内部项目数据库。

本地提交位于 `codex/rename-shinar`，不推送代码；GitHub 仓库名称已经更改，远端源代码仍以其现有提交为准。未重建 Windows 安装器，不将源码中的新安装标识视作旧安装的升级／卸载验证。未调用付费模型、下载新语音模型或进行真人语音验收；这些状态继续独立保留。
