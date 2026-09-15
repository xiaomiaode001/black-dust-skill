# 实际出图工作流

当用户要求“生成、做一张、转换、优化图片”时，本 Skill 的默认交付是可查看的图像，不是只给提示词。提示词、参数和结构数据属于过程资产。

默认采用 `final_only` 交付：候选底图、排版尝试和失败修订放在临时工作目录，选定后不再长期保存或向用户逐张呈现。只有最终成图进入用户可见交付。精确拼图依赖的连续源图、排字底图、原始裁片、拼回证明与 manifest 仍作为内部审计资产保留，但不主动展示；用户明确要求 A/B、过程复盘或验证材料时例外。

## 1. 确认参考图角色

- `content_reference`：保留人物身份、物体结构、建筑、场景构图或排版位置。
- `style_reference`：只提取木炭画法、灰阶、纸齿、边缘和材料气质，不复制其主体。
- `puzzle_reference`：只提取标准拼块比例、压切深度、洞口和散件的实体关系。
- 被用户明确否定的旧稿只能作为失败记录，不能继续担当风格参考。

参考图有本地路径时先实际查看，再决定保护项。不能只按文件名猜内容。

## 2. 先生成连续底图

使用可用的图像生成/编辑工具。新创作不附带无关参考；保真转换只传入当前任务需要的图像。

一次生成指令按以下顺序表达：

1. 主体、姿态、构图和画面比例；
2. 必须保持不变的身份、结构、透视、主光和引导线；
3. `charcoal_drawing` 或 `charcoal_object`；
4. 当前类别的形—调—笔—纸细节；
5. 画面层级、留白和克制的编辑感；
6. 明确要求连续画面：无拼缝、无洞、无散件、无额外文字；
7. 负面约束：无墨点装饰、无全图龟裂/浮雕、无塑料/PBR、无黑烟替代粉尘。

`charcoal_object` 的品牌材料封面在第 4 项明确写出：低矮长方压制炭条、顺长轴片层/纤维纹、吸光主体与少量棱边石墨光、单端斜向纤维断口、贴地碎片到细粉的尺度递减、统一掠光和短接触影。负面项同时加入：非圆柱、非树枝、非规则砖块、非蜂窝焦炭、非熔岩皮、非黑烟/喷枪尾迹。只有用户明确选择其他炭材形态时才偏离该品牌材料基准。

生成完成后查看原尺寸。若主体、木炭笔触或纸面仍失败，只修一个主变量后再生成；不要用拼图层遮盖底图问题。

### 快速生产约束

一般任务默认 `speed_profile: balanced`，社媒封面默认 `speed_profile: rapid`。风格转换只向生成/编辑工具提交一次已收敛指令：一个内容参考、一个明确媒介分支、一个构图目标，不并发制造多张风格候选。社媒封面先生成一张无字、无拼缝底图，再用确定性排字和拼图合成完成；标题、字号、强调色、木炭划线、缺块位置和散件摆位的修改不得触发底图重生。只有用户明确要求探索多个方向或印刷级高分辨率时才使用 `explore` / `quality`。

开始生成前可先检查已批准底图库。`speed_profile: instant` 只允许两种命中：用户明确选择 `base_id`；或 `brief + aspect + theme_family + composition_key` 的规范化签名完全一致。登记必须带显式 `--user-approved`，解析时会再次核对文件 SHA-256；不做模糊匹配，不缓存过程稿，不跨用户复用私密人物/产品参考。严格命中时省去 `base_generation`，继续运行所有本地合成与审计；未命中立即回退 `rapid`，只生成一次新底图。

```bash
python scripts/approved_base_cache.py --cache-dir output/.approved-base-cache register --base output/approved-base.png --base-id ai-history-wide --brief "AI 十年积累的时间剖面" --aspect 5:2 --theme-family technology-history --composition-key subject-left-title-right --user-approved
python scripts/approved_base_cache.py --cache-dir output/.approved-base-cache resolve --base-id ai-history-wide
```

内置图像生成工具未向 Skill 暴露质量/速度旋钮，因此不能从提示词或本地脚本压缩供应端的单次推理时间。可控的优化是零次调用的严格复用、一次收敛生成、避免文字/拼图修改触发重生，以及本地阶段缓存。不得未经用户明确选择改走需要 API Key 的 CLI/API 低质量草稿模式。

用户明确把速度放在首位时改用 `speed_profile: rapid`：新主题只允许一次生成调用，首轮 Prompt 直接包含木炭硬门槛——2–3 处连贯深黑结构块、沿体面侧锋拖擦、可见擦揉中间调、选择性提亮、保留安静纸面；不得先要浅灰技术铅笔稿再开第二轮“增强木炭”。该轮若主体或媒介仍失败，保存为 `visual_candidate` 并报告失败项，只有用户确认愿意增加时间后才再次调用模型。`balanced` 也不自动扩散候选，只允许在硬门槛失败时做一次单变量定向修正。

把耗时拆成 `base_generation`、`cover_composite`、`puzzle_composite`、`pair_audit` 四段记录。若底图已通过，只重跑发生变化及其下游阶段：改标题从 `cover_composite` 开始；只改缺块从 `puzzle_composite` 开始；纯审计问题只重跑 `pair_audit`。拼图阶段对少量缺口使用逐洞 mask 外接框加安全边距的 bounded patch，只在局部计算纸纤维、腐蚀层与阴影，再合回既有画布；不得为三处小洞重复建立全幅纹理场。不得把重复读图、重复生成同一刀模或保存未选过程稿当作正常成本。

社媒封面有合格连续底图后，优先使用 UTF-8 请求文件与可恢复快线，避免 Windows 命令行损坏中文，也让相同请求直接命中已审计资产：

```powershell
python scripts/render_social_cover.py render.request.json
```

请求文件至少提供 `base`、`output_dir` 和 `cover.title`；`cover` 可同时指定平台、强调词与木炭划线，`subject_protected_boxes` 保存完整主体禁区，`puzzle` 保存网格、3 个缺块、散件摆位与材质。脚本只接收已通过的连续底图，不负责调用生成模型。它按 `base_sha256 + cover 参数` 和 `typeset_sha256 + puzzle 参数` 分段签名：标题不变时跳过排字，拼图参数不变且成品/拼回图/裁片/manifest/audit 的 hash 全部一致时直接返回；任一资产被改动就从对应本地阶段重算。首次拼图在暂存资产上执行一次完整独立审计，晋升到最终目录时用逐文件哈希确认字节未变，避免重复重建相同刀模；缓存只能省去重复计算，不能跳过首次 exact-pair 审计或视觉 QA。

## 3. 再制作精确拼图

用户需要拼图成品时，连续底图通过后运行确定性合成：

```powershell
python scripts/puzzle_compositor.py input.png output.png `
  --manifest output.puzzle.json --pieces-dir output-pieces `
  --assembled-output output.assembled.png `
  --rows 9 --cols 16 --cut-style standard `
  --seam-width 2 `
  --piece-shape-policy mixed --piece-content-policy recognizable `
  --min-piece-detail 10 --material-preset deep-charcoal `
  --missing-count 3 --seed 42
python scripts/audit_pairs.py output.puzzle.json
```

实际任务先看图画出完整语义主体禁区，再选择 3 个缺块格和 3 个目标摆位。禁区包含主体外轮廓、产品/炭棒断口、粉尘与碎屑路径、关键投影、建筑垂直线、地平线及引导水道；洞口与散件的旋转、侧壁和影子都不得进入。散件优先从可读但次要的负空间图案区取样，避免大面积纯黑/纯白块让观看者无法辨认其来源。默认 `recognizable` 策略会筛掉低于最低局部灰阶变化的裁片；若所有可识别候选都在主体内，调整网格或留白，并在明确需要浅纸负空间裁片时改用 `any`，不能为通过内容阈值而破坏主体或擅自减少用户指定的 3 组。

生产版合成器使用单张 owner-label 图保存整板块归属关系：共享拼缝由该图一次计算，只有被选中的缺失块才展开为全画布蒙版。独立审计沿同一确定性刀模从源文件重算 assembled proof 与 exact pair；这是性能实现变化，不是减少拼图密度、简化浮雕或跳过审计。

## 4. 必须交付的结果

实际拼图任务只向用户默认展示 `output.png`。为保证这张最终图可审计，内部至少保留：

- `output.png`：带缺口和散落块的最终成品；
- `output.assembled.png`：所有块复位后的完整拼板，用于直接检查图案连续性；
- `output-pieces/`：未旋转、未镜像的原始裁片；
- `output.puzzle.json`：洞、块、来源、摆位、hash 和材质记录；
- 审计结果，以及尚未由人确认的审美问题。

最终回复只呈现选定的实际图像与必要验证结论；不附过程稿、失败稿、被替代版本或内部审计资产链接，除非用户明确索取。只有在工具不能生成或无法取得可合成的本地无损图时，才降级为 `prompt_only`，并明确说明缺块/散件尚未完成精确配对。

## 5. 批量、八类主体与文字分支

批量生成时仍逐类选择底图画法和拼图材质，不把同一个“黑色喷点”模板套给全部题材。人物、动物、静物/产品、建筑、风景、机械、抽象和社媒封面分别保存结果与失败原因；涉及文字时另做中文、英文回归，先排版校对再切割。单类通过不能代表其他类别通过。
