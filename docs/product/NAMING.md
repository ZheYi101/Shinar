# 项目命名：Shinar

决定日期：2026-11-08。状态：**用户已确认，正式项目名称为 Shinar。** 原名为 LinguaLoop；此前的[命名探索备忘](./NAMING_EXPLORATION_2026-10-28.md)保留为历史记录。

## 原典出处

Shinar 是《圣经·创世记》11:2 中的地名，中文《和合本》译为“示拿”。《创世记》11:1–9 讲述巴别塔故事：原本使用共同语言的人们在示拿地的一片平原定居、建城造塔，随后语言被变乱，人群分散；11:9 记述那座城名叫巴别（Babel）。

名称采用的是故事发生地的英文拼写 **Shinar**。它在这段经文中指地域；“语言”“理解”“练习”均不是此处地名的字面释义。

参考原文：

- [中文《和合本》：《创世记》第十一章](https://zh.wikisource.org/wiki/%E8%81%96%E7%B6%93_%28%E5%92%8C%E5%90%88%E6%9C%AC%29/%E5%89%B5%E4%B8%96%E8%A8%98#第十一章)：重点为 11:2，叙事范围为 11:1–9。
- [英文 NIV：Genesis 11:1–9](https://www.biblegateway.com/passage/?search=Genesis%2011%3A1-9&version=NIV)：11:2 使用 Shinar，11:9 使用 Babel，可对照两个名称所指。

## 项目寓意

我们借用共同生活、语言分隔与相互理解的意象：让用户已经看过、听过、读过的内容成为共同语境，在交流中练习使用正在学习的语言。

这是项目对典故的当代品牌解读，与原典中的地名事实分别说明。产品定位继续是“沉浸提供语境，Shinar 帮你练输出”，材料与自由讨论服务于目标语言的实际使用；语音对话是核心体验。具体范围见[项目主旨](./PROJECT_BRIEF.md)。

正式品牌名只使用 **Shinar**。“示拿”用于说明原典的中文译名，不另立中文品牌名。

品牌图形以巴别塔的层叠圆塔、上升回廊和拱洞建立出处联想，塔基结合对话气泡。经文出处与绘画视觉参考分别标注在[图标说明](../../src/shinar/desktop/assets/README.md)，图标轮廓属于本项目的现代几何设计。

## 本次更名范围

本次确认正式名称，并更新 README、产品定位及文档导航中的当前名称；随后更新图标及侧栏 Shinar 字标。历史验收、技术决策中的 LinguaLoop 保留其当时语境。

最初只确认文档与图形；随后用户明确要求从项目目录、包名到 GitHub 仓库完整迁移。当前范围以下节为准。

## 完整工程迁移

| 对象 | 当前名称 |
| --- | --- |
| 项目目录与 GitHub 仓库 | `Shinar`／`ZheYi101/Shinar` |
| Python 分发与导入包 | `shinar`／`src/shinar` |
| 命令 | `shinar`、`shinar-desktop` |
| 环境变量 | `SHINAR_*` |
| 窗口、托盘、QSettings 与 Windows 应用标识 | `Shinar`／`Shinar.Desktop` |
| Windows 启动器与安装器源码 | `Shinar.exe`／`packaging/windows/Shinar.iss` |
| 全新用户库默认路径（Windows） | `%LOCALAPPDATA%\Shinar\shinar.sqlite3` |

兼容规则集中在 `shinar.configuration` 和 `shinar.desktop.shell.settings`：显式 `SHINAR_*` 优先于旧 `LINGUALOOP_*`；全新用户使用 Shinar 路径，已有旧库优先原地复用原数据库文件和相邻 EPUB 资产。配置、旧模型缓存和偏好分别回读，写入新偏好命名空间，不在本次工程迁移中修改个人 `.env`、移动学习库或复制密钥。

独立模型工作进程只接收普通数据和规范化后的环境变量，不依赖主包安装；固定 Melo 支持包仍需要其旧私有环境变量，由适配边界兼容提供。历史报告、归档、外部参考和旧构建产物保留当时名称与实际坐标；更名不改写其验证事实。新发行包使用新名称，旧版安装器的卸载项和快捷方式属于旧发行，不作为本次已升级的证据。

目录迁移、GitHub 回读、兼容测试、可见 Mock 和 wheel 结果见[完整工程更名验收](../validation/engineering/SHINAR_RENAME_2026-11-08.md)。
