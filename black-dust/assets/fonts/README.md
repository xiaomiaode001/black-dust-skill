# 字体来源 / Font Sources

这些字体为原始、未经修改的 Google Fonts 文件，均使用各目录内的 **SIL Open Font License 1.1**。字体本身不适用项目的 MIT 或图片 CC BY 4.0 授权。

These are unmodified Google Fonts files, each under the **SIL Open Font License 1.1** shipped in its directory. The font files are excluded from the project's MIT and image CC BY 4.0 grants.

固定来源 / Pinned source: [google/fonts at 809e4d8](https://github.com/google/fonts/tree/809e4d8b8d7e9364a914909bb777679606c178b8/ofl).

| 角色 / Role | 字体 / Font | 授权 / License |
|---|---|---|
| 中文主字 / CJK display | ZCOOL QingKe HuangYou | [OFL](zcoolqingkehuangyou/OFL.txt) |
| 中文副标题 / CJK supporting text | ZCOOL XiaoWei | [OFL](zcoolxiaowei/OFL.txt) |
| 中文手绘字 / CJK handwriting | Ma Shan Zheng | [OFL](mashanzheng/OFL.txt) |
| 窄体英文 / Condensed Latin | Barlow Condensed | [OFL](barlowcondensed/OFL.txt) |
| 英文手绘字 / Latin handwriting | Kalam | [OFL](kalam/OFL.txt) |

默认 `auto` 优先使用本机已有的定稿字体，缺失时按角色使用随包字体。设置 `BLACK_DUST_FONT_PROFILE=portable` 可固定使用随包字体，使不同机器采用相同字形。替代字体有各自的字形，不能声称与定稿系统字体像素一致；排版仍重新计算文字尺寸和拼图保护框，成图记录及缓存键包含实际字体名称和 SHA-256。

The default `auto` profile prefers installed design fonts and falls back by role. Set `BLACK_DUST_FONT_PROFILE=portable` to use the bundled set consistently across machines. Fallback glyphs differ from the approved system-font designs; text bounds and puzzle protection are recomputed, and manifests and cache keys record actual font names and SHA-256 hashes.
