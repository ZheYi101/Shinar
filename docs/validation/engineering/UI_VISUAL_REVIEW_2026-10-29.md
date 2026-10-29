# 浅色 QML 与修订 3 的视觉复核

日期：2026-10-29。基线是 [UI_LAYOUT_DESIGN.md 修订 3](../../product/UI_LAYOUT_DESIGN.md) 的逐页 PNG，应用是 PySide6 6.11.1／QML。用户要求先比较实际视觉效果、修正不足，再整理为一次提交。本记录承接 [UI 实施记录](./UI_IMPLEMENTATION_2026-10-29.md)，不将此前功能通过视作视觉已经完成。

## 初次判断

修正前尚未达到页面稿的完成度。配色、字体资产和页面路由已有基础，但存在六组清晰差距：按钮背景比热区矮、侧栏控件偏居中、设置缺少行分隔和主题预览、新对话表单垂直居中、聊天有两层重复操作栏、原文分区与当前指向缺少层级。仅有截图非空和功能测试通过不足以接受这些差距。

## 调研与实现选择

查阅 [Qt 官方控件定制](https://doc.qt.io/qt-6/qtquickcontrols-customize.html) 与 [Control 的布局／inset 接口](https://doc.qt.io/qt-6/qml-qtquick-controls-control.html)。官方允许显式替换控件的背景、内容、指示器与弹出列表，并使用跨平台样式作为定制基础。

本项目保留 Material 根窗口和原 QML 技术栈，在纸墨叶控件中使用 Qt 自带 Basic 实现，覆盖真实可见表面及交互状态。原因是 Material 的默认上下 inset 把 36px 按钮的背景压到约 24px，浮动输入提示和默认开关形态也不适合当前稿件。没有升级依赖或引入文档站新版本的 StyleKit。决定见 [Decision 0028](../../decisions/TECH_DECISIONS.md#decision-0028)。

## 对比与修正结果

| 维度 | 修正前 | 修正后与原稿的关系 |
| --- | --- | --- |
| 基础控件 | 按钮像小标签，默认浮动提示贴边，开关仍带默认紫灰外观 | 按钮表面覆盖 36px 热区；普通输入提示留在框内；下拉、数字输入、开关统一纸色／深褐／灰绿，保留焦点、禁用和键盘状态 |
| 侧栏 | 入口与设置分类居中，选中背景偏褐，辅助区无清晰分隔 | 文本统一左对齐；灰绿选中与细侧标；材料／线程缩进及底部分隔保持紧凑；208／192／56px 与窄抽屉规则不变 |
| 设置 | 只有孤立标签和默认下拉框，缺少原稿的整行关系 | 提取 `SettingsRow/SettingsValue/PreferenceChoice`，宽屏标签左、值右、细线分隔；窄屏按内容换行；外观使用三张主题缩略图，减少动效仍保持行内开关 |
| 新对话 | 表单浮在页面中部，开场文案重复 | 760px 正文列从顶部排布，名称／范围、可选想法、讨论／roleplay 与开始操作成组；内容超长仍可滚动 |
| 导入 | 空文件状态占满主区，先要求名称；操作位置与稿件不同 | 880px 有界内容列、280px 文件区域、选中文件后收为 100px 信息区；名称在需要时出现；继续在左、语言在右；粘贴和文件输入保留 |
| 聊天 | 标题栏下重复一排对话列表／原文／更多；消息缺少角色层级 | 操作合并进 36px 标题栏；20px 衬线正文与固定 1.6 倍行距，窄屏 18px；角色使用小号 UI 字体，用户纸底与底部输入形成层级 |
| 原文对照 | 两栏同色，原文 17px，指向只是一行文字 | 左栏浅纸分区与细边线；18／20px 原生 TextEdit；目录／搜索在左、关闭在右；当前指向有浅灰绿来源卡；已读范围有真实末尾“已读至此”标记，位置显式转换为 UTF-16 |
| 材料空间与范围 | 进入范围后材料页签消失 | 抽出 `MaterialHeader`，材料空间／范围共用名称、范围和页签；范围取消仍按入口返回，不提交候选位置 |
| 辅助设置 | 计算页承袭大卡片与大控件 | 保留全部能力，去掉计算页大卡片底，统一紧凑下拉、开关、数字控件与有界正文；本地模型库的分组与危险删除确认保留 |

结论：上述与修订 3 有直接关系的视觉差距已修正，浅色页面已达到本轮工程视觉基线，可以作为这次提交的完成状态。这个结论来自逐图检查、实际控件几何和交互验证，不以像素相似度或虚构评分替代审美判断。

## 图组与检查方法

使用独立临时库和 Mock，全部通过正常工作区操作建立三份中／日／英合成材料、多段 active／completed 对话及真实发言产生的复习项。文件由实际 `DropArea` 接收，文字通过 Qt 输入法提交事件进入控件，没有向数据库注入样例历史。模拟 WAV 只覆盖既有分轮控件，不加载或下载语音模型。

本地 ignored `build/ui-visual-review/` 保存：

- `comparison/index.html`：八组设计稿／修正前／修正后对照，涵盖外观、学习、新对话、聊天、原文、导入、材料空间和范围。
- `comparison/overview.png` 与各页面 PNG：保持原图纵横比；修正前截图为 1440×900、原稿及修正后为 1440×960，明确标注尺寸，不拉伸凑成相同画面。
- `final/`：明确 `QT_SCALE_FACTOR=1` 的 91 张常规状态截图，覆盖 360／600／800／1180／1200／1440 逻辑宽度；另保存文件已选与粘贴表单的中间状态。
- `scale-125/`、`scale-150/`：各 76 张可见 Windows QML 截图，覆盖五档宽度；报告记录实际 DPR、窗口按钮几何与 Qt 诊断。
- `iteration-1/`：首次修正后截图；此前不足仍可从 `build/ui-plan-audit/visible-100-final/` 查看。

100% 基线需要显式设置 Qt 缩放因子；系统默认随显示器可能为 150%，本轮曾识别到这一差异并重采，没有把系统默认截图误记为 100%。

## 工程与交互验证

- 相关桌面／语音管理回归 **40 passed，144.54s**。
- 新增两个真实 QML 用例：主题预览的点击和窄窗口几何、可见按钮背景与热区相等、开关实际操作、下拉框键盘提交与设备 `textRole` 模型展示。
- 全量离线回归 **365 passed、10 skipped，196.40s**，显式 `RUN_REAL_AI_TESTS=0`；跳过的是需显式启用的真实语音／RTC／付费 AI。
- Ruff 与 whitespace 检查通过；只整理本次桌面模块／验证脚本和对应测试，没有机械重排整个业务层。
- wheel 的 **75** 项 QML／字体／图标／许可／翻译资源检查及隔离安装 smoke 通过。叶控件仍由已有 Qt 依赖提供，没有新增外部分发资源。
- 更新 Qt 翻译目录后共 **386** 条源文案，新增主题预览、范围标记和控件说明同样保留国际化入口。
- 最终截图的诊断只含 FFmpeg 后端版本信息，没有 QML binding loop、undefined 属性或控件溢出警告。

完整日志为 `full-regression.txt`、`related-tests.txt`、`wheel-check.txt`。新截图验证增加了合成音频播放计时器的取消，避免测试回放到期误将新录音状态改成 idle；这属于验证运输层修正，不改真实音频实现。

## 差异与范围

原稿中虚构的内容、线程标题、时间与数量没有复制进产品数据；截图内容、已读范围和复习项均来自本轮合成输入。显示语言是原稿之后追加的真实设置，因此外观页多一行语言选项。Windows 系统按钮保留可用的 48px 宽度，部分字段比原稿的短英文样例更宽，以容纳中文与未来翻译。

本次完成的是已约定的中文浅色视觉。系统／深色选择与基础兼容保留，深色定稿仍为后续；真人 Windows IME、触屏与个人审美确认仍需实际使用反馈。真实模型质量、连续语音／模拟波形／打断不因视觉完成而记为通过。

## 复现

```powershell
$env:RUN_REAL_AI_TESTS='0'
$env:QT_SCALE_FACTOR='1'
.venv\Scripts\python.exe scripts\validate_ui_workspace.py --visible --review-fixture --height 960 --widths 360,600,800,1180,1200,1440 --output build/ui-visual-review/final
.venv\Scripts\python.exe scripts\compare_ui_screens.py
$env:QT_SCALE_FACTOR='1.25'
.venv\Scripts\python.exe scripts\validate_ui_workspace.py --visible --review-fixture --height 960 --output build/ui-visual-review/scale-125
$env:QT_SCALE_FACTOR='1.5'
.venv\Scripts\python.exe scripts\validate_ui_workspace.py --visible --review-fixture --height 960 --output build/ui-visual-review/scale-150
Remove-Item Env:QT_SCALE_FACTOR
```
