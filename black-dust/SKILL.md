---
name: black-dust
description: Generate or transform images in the Black Dust / 墨尘 visual system, including refined charcoal drawing, physical charcoal-object scenes, exact full-surface jigsaws, and social covers. Use for this named image style; do not use for unrelated generic charcoal art or ordinary puzzle graphics.
---

# Black Dust / 墨尘

把人物、动物、物体、建筑、风景、抽象创意或社媒主题转化为同一套 Black Dust 视觉语言。首先保留原参考的木炭绘制艺术性：形体明暗、随形笔触、擦揉与提亮。实体木炭崩解是独立材料分支，不是每幅画的必选效果。需要拼图时再组合完整拼面、精确配对和可读排版。

## 开始前

1. 识别交付类型：实际图像/参考图转换、视觉 brief、生成 Prompt、社媒封面或 QA。用户说“生成、做图、转换、优化图片”时默认交付实际图像，不得只停在 Prompt；只有用户明确要提示词/方案时才输出纯文本。
2. 将输入图明确标注为 `content_reference`、`style_reference` 或 `puzzle_reference`；一张图可以承担多个角色，但必须分别说明。
3. 推断 `image_type`。不确定且会改变主体保护策略时才提问。
4. 除非用户覆盖，使用这些默认值：
   - `preserve_composition: true`
   - `allow_subject_missing_piece: false`
   - `accent_mode: monochrome`；社媒封面为 `orange`
   - `typography_mode: composite`
   - `medium_mode: charcoal_drawing`；明确表现实物炭棒/炭雕时用 `charcoal_object`
   - `disintegration: off`；参考或用户明确要求实物断裂/尘化时单独开启，不能从品牌名推断
   - `puzzle_mode: full_surface`
   - `material_preset` 必须显式选择；按类别基线与底图明度从 `deep-charcoal`、`graphite-matte`、`ivory-board` 中选，不使用一套全局材质覆盖所有类别。
   - `cut_geometry: standard-v5`；相邻块必须从同一条共享边生成，圆头通过宽颈和连续切线自然回到基线，禁止细小收口、尖钩或“掐脖子”轮廓。八类主体与两类文字分支的 `knob_ratio` 基线见 `references/puzzle-system.md`，不能用独立描边伪造相邻吻合。
   - `piece_shape_policy: mixed`；默认取出的每块至少同时具有凸头和凹槽，使散件一眼可识别为成熟标准拼图。只有用户明确接受自然随机刀模时才用 `any`。
   - `piece_content_policy: recognizable`；默认散件必须带有可辨认的木炭纹理、明暗过渡或局部图案，避免纯黑、纯白和近乎无纹理的块造成“颜色对不上”的观感。主体安全优先于裁片内容可识别：当负空间只有安静纸纹时，可在用户明确要求负空间取块的前提下改用 `any`，但必须保留 exact-pair 与 assembled proof，不能为了满足 `recognizable` 转而从主体取块。
   - `missing_count: 3` 作为一般主体和社媒封面的首轮审美测试起点。三组必须指 3 个洞口与 3 个同源散件；仍以主体保护为硬门槛，通过重排负空间解决冲突，不能擅自减为 1–2 组，也不以继续加量作为完成度。
   - `speed_profile: balanced`；社媒封面默认覆盖为 `rapid`。两档都只生成一次连续底图；底图通过后冻结像素，排字、强调色、标题划线、拼缝、缺块和散件调整全部走本地确定性合成。只有非社媒任务的主体、构图或木炭媒介未通过硬门槛时，`balanced` 才允许一次单变量定向修正；社媒 `rapid` 不静默追加生成。不得为改字、换缺块位置或调拼图质感重新生成底图。
   - `delivery_visibility: final_only`：默认只向用户呈现最终选定效果，不展示或长期保存未选中的过程稿。精确拼图所需的源底图、排字底图、原始裁片、拼回证明和 manifest 属于内部审计资产，不是展示稿。
   - 用户要求先校准原画时，当前阶段为 `base_art`，覆盖为 `puzzle_mode: off`、`missing_count: 0`，不自动进入拼图或排字。用户后续明确要求先做拼图样张时，切换为 `puzzle_study`；分别记录 `base_status` 与 `puzzle_status`，不把切换阶段当作原画获批。
5. 阅读与任务有关的参考文件，不要一次加载全部：
   - 所有任务先读 [references/visual-system.md](references/visual-system.md)。
   - 生成、优化底图或判定“木炭感不足”时读 [references/charcoal-drawing.md](references/charcoal-drawing.md)。
   - 当前阶段涉及拼图、缺块或拼图成图时读 [references/puzzle-system.md](references/puzzle-system.md)；纯底图修订暂不加载。
   - 按主体类型读 [references/subject-modes.md](references/subject-modes.md) 的对应小节。
   - 涉及中文、英文、Logo 或品牌排版时读 [references/typography-system.md](references/typography-system.md)；涉及平台/封面时再读 [references/social-cover-system.md](references/social-cover-system.md)，需要尺寸时读 [references/platform-presets.yaml](references/platform-presets.yaml)。
   - 需要理解本项目参考图谱系时读 [references/reference-index.md](references/reference-index.md)。
   - 实际输出、跨类别验证或修图时读 [references/validation-rubric.md](references/validation-rubric.md)。
   - 用户要求实际生成、转换或批量出图时读 [references/generation-workflow.md](references/generation-workflow.md)。

## 执行路线

字体可移植性：排字脚本优先使用本机定稿字体，缺失时回退到 [assets/fonts/](assets/fonts/README.md) 中随包的 OFL 字体。替代字形需要重新检查排版与保护区，不能声称与品牌定稿像素一致；manifest 与缓存键记录实际字体哈希。不要假设 Windows 字体路径存在。

### Brief / Prompt

输出模块化结果，而不是一条无法编辑的长 Prompt：

1. 任务理解与参考角色；
2. 内容保护项；
3. Black Dust 视觉指令；
4. 拼图面与缺块计划；
5. 平台/文字计划（如适用）；
6. Negative constraints；
7. 面向当前目标模型的最终 Prompt；
8. QA 清单与当前模式不能保证的事项。

根据模型能力调整措辞与参数，但保持视觉规则不变。只有确认模型和版本时才添加厂商专属参数；否则输出模型无关的核心 Prompt，并把参数槽位单列。

### 实际图像或参考图转换

使用混合流程：

1. 按 [references/generation-workflow.md](references/generation-workflow.md) 调用可用的图像生成/编辑工具，先产出**无拼缝、无缺口、无散落块**的连续 Black Dust 底图；内容参考才要求身份保真，风格参考不要求复制原主体。先选媒介分支，再检查形体、灰面、笔触和纸齿，不能靠撒粉通过。旧测试稿若已充满假浮雕纹理，不把它当风格锚点；用原始风格参考重建，说明这不是像素保真编辑。
2. 中文与品牌字默认用确定性排版加入连续底图，然后逐字校对并冻结为无拼缝连续底图；文字分支依 [references/typography-system.md](references/typography-system.md) 锁定字形、标点、字腔、字距与层级。字体或工具不可用时交付无字版，或把生成文字明确标为实验稿；一次正确不等于模型能稳定排对。
   - 社媒与文章封面优先运行 `scripts/cover_compositor.py`。`brand` 模式固定“墨尘 / SKILL / 把灵感，拼成画面”的品牌关系：竖版三层分离，横版允许“墨尘 + SKILL”锁定成组但实际字面不得重叠，副标题独立成行。`article` 默认由主题驱动标题和主体、品牌退为 kicker；品牌/材料/Skill 主题文章改用 `--layout brand-lockup`，按同一横版品牌字组排版。文字采用“可校对字形骨架 + 从当前底图采样的纸齿 + 按角色分配的炭压与短擦”：主字重压但保留微细露纸，英文中压，副标题轻压且清楚；不交付苍白 distressed print、纯色印刷贴字，也不以长直划痕假装手绘。标题优先落在负空间；低对比场景只做羽化擦淡，文字始终位于场景之上，缺口与散件共同避让文字框。保存 `.cover.json`，把其中 `puzzle_protected_boxes_normalized` 传给拼图阶段。
   - **品牌文字收口**：品牌封面只使用准确字组“墨尘 / SKILL / 把灵感，拼成画面”；副标题只把“拼”设为 Signal Orange，并只在“拼成画面”下保留一条中段重、两端自然收力的木炭划线。禁止双横线、多个副标题橙色重点、平直矢量线、纯色印刷贴字、统一破边和随机墨点。文章封面不照抄品牌副标题：从文章标题中选择至多一个真正有语义价值的橙色重点和至多一条短语划线。所有字与划线均在切图前进入连续底图和保护框，并通过逐字、目标比例及真实缩略图检查。
   - **5:2 定稿基准**：[assets/social-cover-5x2.png](assets/social-cover-5x2.png) 是用户已批准的品牌材料横版标准。后续同类封面以其左上品牌字组、下半部低矮长方炭棒、向右递减粉尘、三组负空间配对、暖象牙纸板和克制掠光作为组合基准；它是风格/排版/拼图参考，不是带洞成品可直接再切的连续底图。
3. 审美通过后再切拼图；用户明确提前要求拼图样张时，按 `puzzle_study` 制作并保留底图未确认状态。固定本次使用的连续底图和排版，之后更换底图或排字须重新切块与校验。整张画布就是同一张先印刷、再压切的拼面，主体与留白都在同一套刀模内；不是平面画作四周添加几个拼图道具。全图适配屏幕时必须先读出完整标准拼板，即使暂时忽略缺口与散件也成立；之后才评价缺块配对和非对称构图。
4. 使用 `scripts/puzzle_compositor.py`，默认选 `--cut-style standard` 并记录 `standard-v5` 几何：标准圆头、宽而清楚的颈部、圆滑凹槽和相邻块共享同一边界；v5 将颈部半宽控制在圆头半径约 50–58%，用连续切线从平直刀线过渡到圆弧，消除 v4 在适屏视图中的细小夹口，同时收敛节点漂移，不把“设计上的不规则”误做成自由波浪刀线。生产基线以共享边一侧约 2px 的压切暗槽定位，再在同一左上光源下建立双向纸边肩部和更宽的近、中、远三段自然衰减，使整板在适屏视图仍可辨认；亮肩与暗肩都从各自位置的原画明度相对增减，禁止固定灰线、白线或全图统一色值。深木炭区域的原笔触必须穿过拼块顶面连续保留，物理变化只留在窄缝带。保护区只减弱、不抹除拼缝，保留同一材质常规强度约 75–90%，让人物、产品和文字仍明确属于整板。
5. 为当前底图显式选择 `--material-preset`，再看图确定保护框、缺块格和逐块目标位置。保护框覆盖完整语义主体：主体外轮廓、断口、粉尘/碎屑运动路径、关键投影与引导线，以及全部文字；不能只框眼睛、产品中心或建筑塔尖。除非显式启用 `allow_subject_missing_piece: true`，洞口和散件的完整占用范围（包括旋转后的角点、侧壁与影子）都不得进入这些区域。默认同时使用 `--piece-shape-policy mixed` 与 `--piece-content-policy recognizable`；若可识别候选只能来自主体，先减少缺块数，必要时对负空间切换 `any`，绝不牺牲主体保护。用 `--missing-cell` 与同顺序的 `--piece-placement` 分别规划“哪里缺”和“放哪里”，以负空间中的小簇、孤立回应和边缘节奏形成非对称布局，默认自动摆位只是候选。散件顶面保持缺口原位置的原始裁片像素，仅在极窄面缘加入基于源像素的方向性压切斜面；`ivory-board` 在 1980×792 社媒横版使用约 4px 暖色薄切壁，随输出尺寸等比缩放，`deep-charcoal` / `graphite-matte` 通常使用 5–6px。洞口必须呈凹陷极性：浅色纸板以 `#D0BCAE` 作为凹底起点，上/左形成暖色遮蔽，下/右只有克制窄唇；禁止固定黑/白整圈、平灰洞底、暗色光晕或贴纸影。纸板底与侧壁使用连续的粗细双尺度纸纤维，不能用盐胡椒噪点、墨点或随机喷溅冒充纸纹。保存 `--pieces-dir` 的未旋转原始块素材、manifest 和 `--assembled-output` 拼回校验图；不能在合成后再交给生成模型改材质并继续声称像素精确。
6. 运行 `python scripts/audit_pairs.py output.puzzle.json` 读取实际文件复核，再进行全图、100% 局部和缩略图视觉 QA。校验器不替代审美判断。

### 生成时间控制

- **即时复用档**：只有用户显式指定 `base_id`，或 `brief + aspect + theme_family + composition_key` 四项完全匹配，且底图已被标记为 `user_approved` 时，才可设 `speed_profile: instant` 并跳过图像模型。使用 `python scripts/approved_base_cache.py` 登记和解析底图；命中后仍执行确定性排字、拼图与完整配对审计。禁止相似度猜测、跨用户复用私密参考、把 `visual_candidate` 写入缓存，或因缓存未命中而硬套旧构图；未命中自动回退 `rapid` 的一次生成。
- **快速档**：用户明确优先速度时设 `speed_profile: rapid`。每个新主题最多调用一次图像生成/编辑工具；该次请求必须一次写全主体、构图和首轮木炭验收条件：至少 2–3 处连贯的深木炭结构块、沿形侧锋铺面、擦揉中间调、少量橡皮提亮与安静露纸。禁止先生成浅灰铅笔稿，再以第二次模型调用补黑；第一次未通过主体或木炭硬门槛时标记为 `visual_candidate`，说明失败项并由用户决定是否追加一次生成，不静默重试。
- **风格转换**：把用户图像作为唯一 `content_reference`，在一次编辑请求里同时锁定构图、主体结构与 Black Dust 媒介约束；不先生成多张气氛稿。原图已满足主体结构时，禁止用“重新想象主体”扩大随机性。
- **社媒封面**：默认 `rapid`，一次生成无字、无拼缝的主题底图；然后依次运行 `cover_compositor.py` 与 `puzzle_compositor.py`。标题换词、字号、强调色、木炭划线、缺块格或散件摆位发生变化时复用同一底图，只重跑受影响的本地阶段。只有用户明确要多方向探索或印刷级放大时才切换 `explore` / `quality`。
- **可恢复快线**：社媒成品优先把中文标题、平台预设、主体保护框和拼图参数写入 UTF-8 `render.request.json`，再运行 `python scripts/render_social_cover.py render.request.json`。该入口串联确定性排字、精确拼图和配对审计，并按底图 hash 与阶段参数复用已验证结果；完整命中时不重开图像模型、不重算刀模或审计。直接调用两个合成器保留给单阶段诊断与算法调试。
- **拼图算法**：生产版使用 owner-label 快速路径。整板刀模先栅格为单张无损块归属图，拼缝浮雕按共享边常数次计算，三块缺失蒙版按需生成；每个稀疏洞口只在 mask 外接框加安全边距的局部 patch 内计算纸纤维、腐蚀层和阴影，再一次性合回画布，不为三处小洞重复建立全幅纹理场。可恢复快线在暂存资产上执行一次完整独立配对审计，晋升后逐文件核对成品、拼回图和原始裁片哈希，避免对同一几何做第二次完整重算；独立 `audit_pairs.py` 仍可从最终文件重新复核。不以跳过 exact-pair、assembled proof 或视觉 QA 换速度。
- **重试门槛**：`balanced` 仅当主体/结构或木炭媒介任一硬门槛失败时允许一次定向生成修正，而且每次只修一个主变量；文字、主体保护、拼图质感和 exact-pair 失败全部在确定性阶段修正。纯偏好微调留在本地阶段；同一底图不做无目标的 A/B 扩散。
- 非社媒任务以 `balanced` 为默认交付档，社媒封面以 `rapid` 为默认；`instant` 只复用严格命中的已批准底图。内置图像工具没有可由本 Skill 控制的速度/质量参数，不能声称已压缩供应端单次推理时间，也不能为追求速度静默切换到需 API Key 的其他生成路径。用户明确要求探索多方向时才切 `explore`；明确要求超高分辨率或印刷级放大时才切 `quality`。所有档位都不得降低配对审计，只改变生成调用上限、候选数量与输出分辨率。

若只有生成模型、没有确定性合成工具，将结果标记为 `prompt_only`。该模式可以提供视觉草图，但不得声称缺块在形状和像素内容上精确对应。

### 交付与过程稿

- 默认在临时目录中完成底图试验、排版尝试和构图候选；确定最终版本后，只把最终成图提升为用户可见交付，不在回复中罗列过程图、失败稿、缩略图或被替代版本。
- 不把 exact composite 的连续源图、排字底图、未旋转裁片、`assembled_output`、manifest 和审计结果当作过程稿删除。它们是证明最终成图中文字与缺块严格对应的内部资产；默认不展示，用户要求核验时再提供。
- 用户明确要求 A/B 对比、过程复盘、保留历史或继续从某一版修改时，才保存并呈现对应候选。不得删除用户输入、既有批准稿或用户要求保留的版本。
- 最终回复优先直接展示一张选定成图，并只报告必要的尺寸、状态和关键验证结论；不把工作日志写成视觉交付的一部分。

## 不可破坏的规则

- `charcoal_drawing` 是用炭笔描绘人物/毛发/金属/山石，不是把这些对象做成炭块。用侧锋铺调、顺形排线、擦揉暗面、橡皮提亮和虚实边缘构成细节。
- `charcoal_object` 才表现干燥脆性炭棒、断面与接触阴影。品牌材料封面的默认炭棒是低矮、压制成形的长方炭条：长轴清楚、边棱略有手工不齐，棒身保留顺长度的片层/纤维纹、浅裂与克制石墨光，不能变成圆柱铅笔、树枝、整齐工业砖或蜂窝焦炭。显式开启单端崩解时遵循 `SOLID → CRACK → FRACTURE → FRAGMENT → GRANULE → BLACK DUST → EMPTY`；断口为斜向纤维片层，碎屑从断端贴地延伸并逐级变细，不以烟雾、液态墨或均匀喷点替代实体粉尘。完整标准读 [references/visual-system.md](references/visual-system.md) 的“实体炭棒定稿形态”。
- 最终拼图为 edge-to-edge 完整表面、无装饰外框；在查看洞口和散件之前，整幅必须先读成一块由标准拼块组成的哑光纸板。`standard-v5` 使用更易辨认的圆头宽颈、连续切线共享边、约 2px 单侧暗槽、方向性双肩和更宽的三段衰减；侧壁厚度按材质分档，`ivory-board` 在 1980×792 为约 4px，其他预设通常为 5–6px。禁止细小收口、尖钩、全图 emboss、棋盘亮度、固定灰白线、盐胡椒纸纹、随机墨点或把统一纹理贴在原画上冒充拼图材质。
- 深色背景也要有可读的炭笔层次，不能为了让散落块显眼而给原块面提亮、改色或画整圈白描边；应调整底图负空间、取块区或摆位。
- 每个缺口与取出块必须一一配对：轮廓、方向、原位置图像、颜色和光线一致；不镜像、不生成孤立块、随机洞或重复内容。
- 缺口与散件共用同一几何 mask，且 `mask_sha256`、`content_sha256` 可审计；散件顶面不得提亮、重绘、加纹理或改变原图内容。浅色社媒封面不为证明配对强行取多块高反差炭粉图案；优先减少缺块数并选择一块中等过渡、一块细纸齿/轻炭痕，保持真实而克制。
- 每轮 exact composite 都要保存无缺口的 `assembled_output`。它必须由同一底图、刀模和拼缝参数重建，并通过 `assembled_sha256` 审计；用它直接查看建筑线条、产品结构和其他图案在拼回后是否连续。
- 默认避开眼睛、脸部关键点、Logo、标题、产品核心结构、建筑关键几何和主要引导线。
- 强调橙固定为 `#FF5A1F`，只作小面积锚点；其余为 warm ivory、cream、charcoal black 和 graphite gray。
- 技术 Skill 名为 `black-dust`，中文对外名为“墨尘 Skill”，通用英文署名为 `BLACK DUST`；品牌封面锁定字组则显示“墨尘 / SKILL / 把灵感，拼成画面”。早期“黑尘”和 `I'M BLACK DUST` 只作为探索参考，除非用户明确指定。

## 输出完成条件

交付前必须检查：

只检查当前阶段适用项。`base_art` 检查主体、绘制/材料、参考意境与实际像素尺寸；拼缝、缺块、配对和最终排版标记为“未进入”，不能为通过这些检查提前添加元素。

- 主体、比例、构图、透视和主要光线是否保留；
- 不依赖缺口与散件，整幅是否先读成满版、连续、无外框的成熟标准拼板；若先看成平面画再靠洞块识别拼图，直接返工；
- 拼缝是否采用 `standard-v5` 共享边、清楚圆头宽颈、无细小收口的连续切线、约 2px 单侧切槽和左上光源下的方向性双肩；整板是否在适屏视图可辨；明暗是否相对局部原画而非固定灰白线；保护区仍保留约 75–90% 可读强度，且深炭笔触与画面其余区域未被全局浮雕化；
- 缺块数量与位置是否服从画面层级；
- 每个 `pair_id` 是否唯一，块能否只通过旋转回位；
- 默认散件是否同时具有凸头和凹槽；`assembled_output` 中对应图案是否完整连续；
- 默认散件是否具有足够的局部灰阶变化，能通过木炭图案与周围画面直接识别其来源；
- 块面内容是否来自原缺口位置；
- 洞口是否呈上/左暗、下/右内壁反光的凹陷极性；散件是否有严格对应的原图顶面与近/远接触影；`ivory-board` 在 1980×792 是否为约 4px 暖色薄切壁且无固定暗圈，其他预设是否保持 5–6px 分层侧壁；纸纤维是否连续且具粗细双尺度；
- 绘画模式是否有随形笔触、擦揉灰阶和选择性提亮，而非墨点、浮雕滤镜；实物模式的断面与颗粒是否有真实尺度关系；
- 平台比例、安全区、标题与中文是否正确；
- Signal Orange 是否克制，缩略图是否仍能识别标题和主体。

只报告实际验证过的项目。对 prompt-only 结果，把“精确拼图匹配”和“最终文字准确性”列为待后期验证。

区分 `generated`、`structural_pass`、`visual_candidate`、`user_approved`。人物、动物、静物/产品、建筑、风景、机械、抽象、社媒封面八类主体都必须单独回归；涉及文字时另外回归中文与英文两类，并逐字/逐词校对。单一生成工具、每类一张的测试不能宣称所有模型通用或类别已经稳定。默认只保留最终成图与必要审计资产；Prompt、参数和未解决问题可写入最终 manifest，普通初稿和被替代修订稿不作长期展示资产。
