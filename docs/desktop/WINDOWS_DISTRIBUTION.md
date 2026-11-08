# Windows 桌面分发

面向 Windows 10 1809 及以上、Windows 11 x64。发行文件包含应用私有的 Python
3.12.13、PySide6 6.11.1 和锁定依赖，无需预装 Python 或 uv。启动器使用系统自带的
.NET Framework 4.x。当前为开发预览包，打包的是构建时工作树快照，包含尚未提交的变更。

## 使用

- **安装版**：运行 `Shinar-0.1.3-windows-x64-setup.exe`，默认安装到
  `%LOCALAPPDATA%\Programs\Shinar`。不请求管理员权限，创建开始菜单入口；桌面快捷方式可选。
- **免安装版**：完整解压 ZIP，再双击 `Shinar\Shinar.exe`。保留整个目录，不能只移动 EXE。
- 两种方式均从正常应用数据目录读取材料与历史，默认是
  `%LOCALAPPDATA%\Shinar\shinar.sqlite3`；免安装指无需安装，学习数据仍保存在用户目录。
- 安装与升级不自动关闭正在运行的应用。更新前自行退出对应的旧版 Shinar；卸载保留学习库、
  偏好、模型缓存和个人配置。免安装版与安装版默认共享同一用户的数据和设置。
- 关闭窗口默认询问后台运行或退出，可记住选择并在「设置 → 外观」修改。后台时由系统托盘
  图标／菜单恢复；托盘及窗口更多菜单均可彻底退出。后台保留当前任务与语音；托盘不可用时关闭直接退出。

首次启动未配置 AI 时进入「设置 → 模型与服务」。填写兼容 OpenAI 的 API 基础地址、
API Key，点击「读取模型列表」，再从两个下拉列表选择推理模型和对话模型，点击「保存配置」，
从系统托盘或窗口更多菜单退出后重新打开应用。对话可选择「与推理模型相同」。模型不需要手写 ID，未读取列表或所选模型
不在当前服务列表中时不可保存；刷新后保留仍有效的选择，不自动改用另一模型。修改地址或密钥后
必须重新读取列表，旧服务的列表不能用于新连接。

此操作通过 Bearer 认证读取 `GET /models`（相对基础地址），不发送学习材料、不请求生成。
空列表、认证失败或接口不支持均在页内反馈，可修正后重试。读取成功不代表生成权限、额度或模型
质量通过；没有列表接口的服务仍可沿用已有 `.env` 兼容配置，桌面不提供手填模型入口。

界面配置保存到应用数据目录的 `ai-services.json`，密钥使用 Windows 当前用户 DPAPI 加密，
不写入 QSettings 或安装目录；不要把该文件当作跨机器的密钥备份。保存仅影响重新启动后的
新服务绑定，当前对话继续使用启动时配置。未保存界面配置时，继续读取本地环境；
可以将 `.env.example` 复制为 `%LOCALAPPDATA%\Shinar\.env`，或用
`SHINAR_CONFIG_FILE` 指定文件。已有进程环境变量优先于该 `.env`；显式保存的界面
连接信息优先于二者。「恢复使用环境配置」移除界面配置，重启后重新读取环境，不改写 `.env`。
发行包不携带开发者配置、密钥、学习库或调用日志。

本地 STT/TTS 模型、CUDA 组件、LiveKit server 和 VAD 资产不随包预装，仍在设置中显式准备。
RTC/ONNX 的 Python 依赖已包含，独立语音环境保留原有安装机制；打包通过不代表真人语音验收完成。

应用图标用于 EXE、任务栏、快捷方式和卸载入口。当前预览 EXE 未进行代码签名，
Windows 可能显示“未知发布者”；校验随包的 `SHA256SUMS.txt` 可检查下载完整性。

## 本地构建

在 Windows x64 仓库根目录运行，先安装 uv 和桌面开发依赖。所有构建依赖进入独立的
`build/windows/`，不会同步或修改共享 `.venv`，也不安装到系统 Python。

```powershell
# 可选：从官方固定版本下载并核验 Inno，使用 portable 模式放入 ignored build/。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_windows_tools.ps1

# 同时生成 ZIP 和安装器；不传 --iscc 则只生成 ZIP。
.venv\Scripts\python.exe scripts/build_windows.py --iscc build/windows-tools/inno-6.7.4/ISCC.exe

# 隔离解压到含中文和空格的新目录，检查窗口资源、原生启动器及运行时。
.venv\Scripts\python.exe scripts/check_windows_distribution.py dist/windows/Shinar-0.1.3-windows-x64.zip --output build/windows/relocation-check --visible

# 新的隔离目录中安装、离屏启动和卸载，验证保留外部数据及清理卸载登记。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_windows_installer.ps1 -Installer dist/windows/Shinar-0.1.3-windows-x64-setup.exe -OutputDirectory build/windows/installer-check

# 另验从旧完整运行时升级：使用短测试路径，避免旧包中的 Qt 开发文件超过 Win32 路径限制。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_windows_installer.ps1 -Installer dist/windows/Shinar-0.1.3-windows-x64-setup.exe -BaselineInstaller dist/windows/Shinar-0.1.2-windows-x64-setup.exe -OutputDirectory build/windows/upgrade-check
```

产物位于 `dist/windows/`，包括 ZIP、安装 EXE 和 SHA256 校验文件；单次工作目录包含
`payload.json` 文件清单。`BUILD.json` 记录 Python 来源与 hash、wheel 和锁文件 hash、构建时间。
每次都从白名单源文件创建新的构建快照，避免旧 `build/lib` 或个人文件混入。

从 0.1.3 起默认使用 `windows-slim-v1` 运行时布局。构建脚本从产品 Python import、实际加载的
PySide 绑定及 `qmlimportscanner` 结果确定入口，递归保留普通／延迟 PE 导入的 DLL 依赖。
保留 WebEngine 进程、发布资源、软件图形回退、多媒体、原生托盘、输入法和中英日字体；Qt 的
`.debug` 资源、开发工具、头文件、未用模块和其他语言的 Qt 翻译不再分发。Qt locale 保留
en-US／zh-CN／zh-TW／ja，显示语言入口与原文语言设置不变。Python 保留 `venv`、`ensurepip`
和独立模型进程机制；不冻结 EXE、不将依赖转嫁给用户，也不删减学习资料或语音模型缓存。

完整裁剪清单保存于构建目录 `pruning.json`，包内 `RUNTIME_LAYOUT.json` 记录保留／退役文件。
安装成功复制新文件后才执行受限清理：只删除清单内的旧运行时文件，拒绝绝对路径、越界路径和
当前保留项，不递归清空运行时或访问用户数据目录。升级前需真正退出旧程序。ZIP 用户应解压到
新目录；覆盖旧目录会留下旧版额外文件。安装器使用 LZMA2 normal 压缩，ZIP 仍提供直接解压。

Python 和 Inno 下载地址、SHA256 固定于 `packaging/windows/toolchain.json`；
应用依赖由 `uv.lock` 导出，使用 hash 校验且只安装 wheel。
Python 的许可证、各依赖 `*.dist-info/licenses`、字体 OFL 和 QML 资源随程序保留。
项目整体开源许可证尚未选定，预览包不改变该状态。

## 验证边界

使用 `RUN_REAL_AI_TESTS=0`，在独立数据目录离屏运行 wheel 和分发包检查；不访问真实学习库、
不抢占正在验收的窗口、不录音、不下载模型、不发起真实模型调用。
安装器在独立目录执行安装／卸载检查，跳过快捷方式以免影响正常安装；正常安装路径和
开始菜单入口由 Inno 配置提供。真实设备、真实服务、升级时文件占用和干净系统验证另列。
内部检查使用 `/VALIDATE=1` 安装参数，登记到独立的 `Shinar.Desktop.Validation` 卸载项，
不覆盖正常安装的登记或快捷方式；此参数不改变学习库路径，启动检查仍须显式使用 Mock。

构建机制依据 [Python 私有运行时说明](https://docs.python.org/3.12/using/windows.html)、
[Inno 用户安装模式](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm) 和
[Inno portable 开关](https://jrsoftware.org/ishelp/topic_technotes.htm)。

密钥保护依据 [Windows CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)，未启用机器范围或交互式密码提示。实际账户访问、丢失 Windows 用户凭据和异机迁移不由安装器恢复密钥。
