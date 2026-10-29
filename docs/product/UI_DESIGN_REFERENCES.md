# 输入与页面流程：外部参考

调研日期：2026-10-29。用于 `ui-layout-v1` 修订 3；下列是公开资料与示例观察，LinguaLoop 的应用方式是本项目提案，尚未迁移到 QML。

## 查阅的参考

| 来源 | 确认的信息 | 本轮采用的部分 |
| --- | --- | --- |
| [IBM Carbon：Forms](https://www.carbondesignsystem.com/building-blocks/core/patterns/forms) | 官方区分专用页面、侧面板与对话框；较复杂、较长或分步的输入适用专用页面。也讨论了字段间距、简短可见标签与只在相关时出现的输入 | 导入使用主页面；定位与核对在原文旁完成；不把普通编辑流程装进遮罩小表单 |
| [GOV.UK：Question pages](https://design-system.service.gov.uk/patterns/question-pages/) | 只问必要信息，保留返回路径和此前输入；不要求用户在同一流程重复填写 | 文件／粘贴与范围核对分开，返回保留内容；不增加大号步骤条、大标题和逐题向导 |
| [Readwise Reader：Adding Content](https://docs.readwise.io/reader/docs/faqs/adding-new-content) | 官方说明支持拖入文件，并从已有文件信息提取元数据；也支持上传对话框。其[公开操作示例](https://docs.readwise.io/images/upload-md-file_drag-drop_web.gif)展示正文与侧边资料区 | 文件拖入作为直接入口，已知名称先填入；借鉴正文与旁侧操作分工，不复制它的上传对话框或云端能力 |

上述来源均为官方资料。实际打开了 Carbon 页面和 Reader 的公开动图，核对结构，而非只凭设计风格关键词推测。没有复制其中的图片或产品资源到项目。

用户提供的 Codex 截图继续作为分类、行式布局与导航密度的视觉参考。B 站投稿入口在本次访问中跳转至登录页，未登录，也未核验内部投稿表单；因此不把“该产品从不使用弹窗”写成研究结论。

## 对 LinguaLoop 的取舍

以下是结合用户反馈和来源作出的设计判断，不是外部规范对本项目的要求。

1. **普通填表进入主区。** 导入、已读范围和“更多”不再使用自定义遮罩弹窗。系统文件选择器仍承担本地文件选择；目录与搜索等轻量菜单不承担多步填表。
2. **内容与操作同处一页。** 已读范围成为材料内的一个标签页，正文占主要面积，定位与保存放在旁侧；窄窗口按顺序排列，保持单一页面。
3. **优先直接选择。** 默认在原文点选已读末段，随后明确显示边界；末句和百分比是补充定位方式，只有选中相应方式才出现输入。这个新增入口是待评审的 UI 提案，不能据此宣称当前 QML 已支持。
4. **空间从重复层级中节省。** 输入框保留约 40–44px 高度，字段之间约 20–24px，分组约 28–32px。正文与字段各有可读宽度；不靠把控件、字和间隙一起缩小实现紧凑。
5. **名称不重复，标签不省略。** 页面身份由导航说明；真正输入所需的名称保持简短、可访问。占位文字与长解释不能代替必要标签。
6. **未提交的内容能够返回。** 文件信息、语言、粘贴草稿与待确认范围保留在原型内存，返回与方式切换不清空。取消不提交范围；范围编辑不改变当前聊天的原文指向，也不自动发起准备或聊天。

## 本轮稿件

- 导入主页面：[03](./assets/ui-layout-v1/screens/03-import.png)、[粘贴内容](./assets/ui-layout-v1/screens/26-import-paste.png)、[已选文件](./assets/ui-layout-v1/screens/27-import-file.png)。
- 材料内核对：[04](./assets/ui-layout-v1/screens/04-scope.png)、[末句](./assets/ui-layout-v1/screens/28-scope-sentence.png)、[进度](./assets/ui-layout-v1/screens/29-scope-progress.png)、[窄窗口](./assets/ui-layout-v1/screens/30-scope-narrow.png)。
- 原型导入只演示文件名称和选择状态，不读取文件内容、上传、调用模型或写入应用库。正文与范围示例使用固定的虚构段落，不是真实导入解析结果；文件与粘贴文本的真实解析、唯一匹配、原文版本和位置换算继续由应用实现与测试负责。

完整布局、能力边界与实现映射见 [UI_LAYOUT_DESIGN](./UI_LAYOUT_DESIGN.md)。
