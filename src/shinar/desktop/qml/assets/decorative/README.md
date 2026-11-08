# 纸墨装饰资产

2026-10-30 按已定的暖纸与墨迹融合参考图制作；参考为
`docs/product/assets/visual-style/warm-paper-ink-reference-v1.png`。
用户明确要求结合原本的视觉效果，先前自行绘制的大枝叶、展开书与对称花饰已撤掉。

- `paper-fibers.svg`：256 × 256 无底色细纤维平铺。
- `cloth-book.png`：以融合图右下方的灰绿布面书、小枝叶和褐色织物书签为图片参考，使用内置 imagegen 生成的独立透明插画；1536 × 1024，有真实 alpha。完整提示词在 `generation.json`。
- `botanical-stamp.svg`：参考原图纸条上的双圈、淡赭色植物印章，原创路径；不含文字或机构标识。
- `paper-slip.svg`：浅奶油纸笺，带轻微不规则边缘，原创路径。
- `paper-tape.svg`：参考原图的半透明米色短胶带，原创路径。

布面书 SHA-256：`1fc993396c17f5acfd04b67acf0dd720ce71d6432569632fe07fe477712dc5c2`。
SVG 由 coding agent 直接绘制；没有下载第三方图片。应用运行时没有外部字体、脚本或网络依赖。

这些资产属于本仓库原创内容，沿用项目整体授权状态；项目尚未确定开源许可证。
上级 `assets/LICENSE` 的 Apache 2.0 许可用于原有 Material 图标，不应套用于本组资产。
应用通过独立 QML 装饰层控制透明度、位置和主题；装饰没有点击、键盘或可访问语义。
