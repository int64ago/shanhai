---
name: build-beast
description: "按《山海异兽录》已验证的国风工笔水墨 3D 管线制作或更新一只山海经神兽（设定 JSON → Rodin 初版 → Blender 矫正姿态出四视图 → Rodin 多视图高模 → Blender 去重尾/绑骨骼/生成慢步动画 → gltf-transform 压缩 → 水墨着色与运行时奇异部件挂接 → 截图自检）。当用户要求制作、生成、绑定或优化某只神兽时调用。"
---

# 山海经神兽制作工作流（Build Beast）

本技能沉淀自 **M2 九尾狐试点** 的完整踩坑与调优过程。每做一只新神兽（驳、陆吾、毕方、帝江、穷奇、饕餮、开明兽、凤凰、应龙），严格按以下 7 步执行。

---

## 1. 古籍设定与部件拆解（`content/beasts/<id>.json`）

1. 新建 `content/beasts/<id>.json`：
   - `source`：只收《山海经》原文与篇目，严禁把后世引申或现代设定混进原文。
   - `inferred`：所有视觉补足（毛色、纹样、特效）逐条标明依据（如“艺术设计”或古本插图出处），供左侧古籍卡片朱框单独展示。
2. **主体与奇异部件拆分原则**：
   - **能一次生成的标准体型**（如 `驳`：马身独角）：整体生成，不拆部件。
   - **多尾 / 多首 / 双翼 / 腋下眼**（如 `九尾狐`、`陆吾`、`开明兽`、`穷奇`、`饕餮`）：**标准躯干**与**单个奇异部件**分开生成。躯干走 Blender 自动骨架，奇异部件在运行时或挂接点上复制并程序化驱动，绝不让 AI 直接生成九头九尾（必粘连错乱）。

---

## 2. 两阶段 Rodin 3D 生成（方案 4：初版 → 姿态矫正四视图 → 多视图高模）

AI 文生 3D 的四足动物普遍存在**后腿半蹲、自带多余短尾**的问题，直接改提示词收效甚微。必须走两阶段生成：

### 2.1 第一阶段：文生 3D 初版（拿解剖与贴图基底）
- 写 `pipeline/rodin/jobs/<id>-body-v1.json`：
  - 提示词写明解剖比例、毛色分布、东方点缀（每兽最多 1–2 处，如额间云纹、独角），并注明 `standing tall on four straight legs, level back, head facing forward`。
  - 若单独生成细长部件（尾、翼、长颈），提示词必须写明长宽比（如 `elongated tapered shape about five times longer than its thickness, thin at the root`），否则会生成短胖团块。
- 执行 `pnpm rodin pipeline/rodin/jobs/<id>-body-v1.json`。

### 2.2 第二阶段：Blender 姿态矫正 + 渲染正交四视图 → 图生 3D 高模
1. 先将初版模型归一：
   ```bash
   /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
     --python pipeline/blender/normalize.py -- \
     raw/<id>-body-v1/base_high_pbr.glb /tmp/<id>_norm.glb --length 1.0 --max-texture 2048
   ```
2. 用 `pipeline/blender/turnaround.py` 自动抬高后躯、拉直后腿、压平多余短尾，并渲染无透视正交四视图（`view_34.png`、`view_side.png`、`view_front.png`、`view_back.png`）：
   ```bash
   mkdir -p concept/<id>
   /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
     --python pipeline/blender/turnaround.py -- /tmp/<id>_norm.glb concept/<id>
   ```
   - 渲染后**必须先用 Read 查看四视图**，确认背线平直、四腿直立、正背面无畸变。
3. 写 `pipeline/rodin/jobs/<id>-body-i2m.json`，把 4 张视图放入 `images`（`view_34.png` 放第一张以决定材质），配置拉满：
   ```json
   {
     "tier": "Gen-2.5-Extreme-High",
     "images": [
       "concept/<id>/view_34.png",
       "concept/<id>/view_side.png",
       "concept/<id>/view_front.png",
       "concept/<id>/view_back.png"
     ],
     "params": {
       "mesh_mode": "Raw",
       "geometry_file_format": "glb",
       "quality_override": 50000,
       "texture_mode": "extreme-high",
       "addons": "HighPack"
     }
   }
   ```
   - 注意：`Extreme-High` 会返回两个 GLB：`base_high_pbr.glb`（5 万面 + 12K 颜色贴图 + 4K 法线，运行时用这个）和 `model_export_raw.glb`（1000 万面无贴图高模）。

---

## 3. Blender 自动化清理、去重尾、绑骨与动画（`pipeline/build_beast.sh`）

一行命令跑完标准化、绑骨、关键帧与 `gltf-transform` 压缩：
```bash
pipeline/build_beast.sh <id> <body-job-id> [part-job-id]
```

### 关键机制与必查项：
1. **12K 贴图预缩（`normalize.py --max-texture 4096`）**：Rodin 最高档的 12K PNG 会让中间 GLB 膨胀到 130MB+，必须在 `normalize.py` 里先缩到 4096，最后由 `gltf-transform` 压成 2048 WebP。
2. **多尾神兽去重尾（`normalize.py --trim-tail`）**：
   - 即使四视图压了尾巴，Rodin 图生 3D 仍常在两后腿之间生成一条下垂短尾。若不清理，叠上外挂尾巴会出现“两组尾巴”。
   - `--trim-tail` 只删两腿中缝（`|x| < 0.052`）和踝部后方明显超出后腿轮廓的尾尖，**绝不能切进两侧后腿（`|x| >= 0.052`）**，否则从右侧（`-X`）看后腿脚踝会被削成细丝。
   - **必须同时检查左右两侧预览（`+X` 与 `-X`）**，因为 AI 模型左右后腿前后位置常有微小不对称。
3. **三层蒙皮权重兜底（`rig_quadruped.py`）**：
   - AI 网格上默认热扩散（`ARMATURE_AUTO`）几乎 100% 失败。
   - 脚本自动退到：① 水密体素代理求权重 + `DATA_TRANSFER` 传回；② 若仍失败，退到按骨骼线段距离（反距离幂）算权重 + 网格平滑（100% 成功）。
4. **尾根挂接骨位置（`tail_attach`）**：
   - `tail_attach` 必须定在**骶骨高度**（`hips_z` 偏上、中轴后缘往内缩 `2.5%` 身长），绝不能取整个后半身最靠后的点（否则会落到后膝或下垂尾尖上）。
5. **四拍慢步与脚掌防翘趾（`anim_walk`）**：
   - 步态用 `leg_cycle(p, duty=0.6)`：支撑相匀速后移（防滑步），摆动相平滑前送。
   - 脚掌骨 `foot` 的旋转必须抵消上两节旋转 `-(u_ang + l_ang) + 0.15 * lift`，保证支撑相脚掌平踩地面、抬腿时趾尖自然微垂，避免出现“脚尖翘天上用脚后跟走路”。

---

## 4. 国风工笔淡彩 / 水墨渲染（`src/systems/ink/`）

所有神兽统一使用 `src/systems/ink/` 着色，不再走 PBR 写实毛发：
1. **工笔设色（`inkMaterial.ts`）**：
   - 从贴图提取色相：`vec3 hue = albedo / max(max(albedo.r, max(albedo.g, albedo.b)), 0.24)`。**分母下限必须保持在 `0.24` 左右**，否则深褐色的瞳孔、眼线、鼻吻会被归一化拉成亮橙色，导致“白眼/瞎眼”。
   - 暗部浓墨阈值 `lum < 0.18` 平滑入墨，保留五官神采与黑足。
   - 纸纹与水渍噪声**必须采样模型空间坐标 `vObj`**，不可采样世界坐标 `vWorld`（否则神兽走动或转头时，墨迹会在皮毛表面滑动，看起来像嘴脸在怪动）。
2. **毛笔提按外轮廓（`createOutlineMaterial`）**：
   - 反向外壳沿法线外扩，顶点着色器末尾**必须保留裁剪空间深度微偏 `gl_Position.z += 0.0012 * gl_Position.w`**，防止胸毛、吻部的浅凹凸背面穿出正面形成黑斑横杠。
   - 外挂部件（如九尾、羽翼）同样调用 `createOutline(mesh, 0.0035)` 加细墨线，保证与躯干画风一致，不要用半透明噪点镂空尾面。

---

## 5. 运行时组件与交互规范（`src/beasts/<id>/`）

1. **禁止鼠标注视扭头**：
   - **不要**加鼠标跟随转头（Look-At IK），神兽头部只随自身动画（`idle` / `walk` / `alert`）自然运动。
2. **React 19 `StrictMode` 场景图副作用规范**：
   - `useGLTF(url)` 返回的 `scene` 是全局缓存单例。
   - 在 `useMemo` 中调用 `inkify(scene)` 是安全的（内部有 `scene.userData.inked` 幂等保护）。
   - **严禁在 `useMemo` 里把外挂部件节点（如 `holder`）直接 `attach.add(holder)`**！因为 React 19 `StrictMode` 会执行两次 `useMemo` 并**丢弃第二次返回值、保留第一次返回值**，在 `useMemo` 里清理或挂载会导致残留静止部件或主部件脱离场景树。
   - 外挂节点必须在 `useEffect` 中挂载并在 cleanup 中移除：
     ```ts
     useEffect(() => {
       rig.attach.add(rig.holder)
       return () => {
         rig.attach.remove(rig.holder)
         rig.mixer.stopAllAction()
       }
     }, [rig])
     ```
   - 计算外挂节点的抵消旋转 `restQ` 时，必须取 `attach` **相对于 `scene` 根节点**的旋转（`attach.getWorldQuaternion().premultiply(scene.getWorldQuaternion().invert())`），排除外层 `<group>` 的旋转。
3. **非等比缩放与法线安全**：
   - 对 AI 网格做非等比缩放后，**严禁调用 `geometry.computeVertexNormals()`**（AI 网格常含退化三角形，会算出 `NaN` 法线并污染画面），应直接对已有法线按缩放比逆转置修正并做零长保护。
4. **特效与宣纸融合**：
   - 宣纸浅色背景上**禁用 `AdditiveBlending` 发光粒子**（会被冲白看不见），一律改用正常 Alpha 混合的水彩晕染粒子（中心浅、边缘积色水痕）。

---

## 6. 视觉自检（交付前必跑）

每次改完模型、骨骼或着色器，必须在无头 Chrome 中跑通截图并用 Read 肉眼核查：
```bash
# 1. 静 / 行 / 神通 全景图（自动等待 [beast] ready）
for a in idle walk special; do
  node scripts/shot.mjs "http://localhost:5199/?action=$a" /tmp/shanhai-check/<id>-$a.png 1440x900 2200
done
# 2. 行走连续帧特写（检查后腿厚度、脚掌是否翘趾、外挂部件是否脱节）
node scripts/closeups.mjs "http://localhost:5199/?action=walk" /tmp/shanhai-check/<id>-w 3 280 320,160,1060,580
```
核查清单：
- [ ] 五官清晰（瞳孔有神、无白眼），胸腹与面部无外轮廓穿模黑斑
- [ ] 无多余原生短尾或 `StrictMode` 残影部件
- [ ] 行走时四足脚掌平踩地面、小腿无削细变形、步速与位移匹配不打滑
- [ ] 左侧古籍卡片竖排从右向左阅读正常，“原文”与“设计”朱框严格分栏
- [ ] `pnpm typecheck && pnpm build` 零报错，单兽 GLB 总大小 ≤ 15MB（常规 1.5–3MB）
- [ ] 新增 `.glb` / `.png` / `.ogg` 等二进制资产已由 Git LFS 跟踪（`git lfs status` 确认）
