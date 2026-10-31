# AGENTS.md — AI Agent Engineering Guide for Shanhai World (山海异兽录)

This repository is designed to be **agent-native** (compatible with Claude Code, OpenAI Codex, Grok, Cursor, Windsurf, GitHub Copilot, and autonomous CI agents). Read this file before modifying code, shaders, or 3D assets.

---

## 1. Project Overview

**Shanhai World (《山海异兽录》, https://shanhaiworld.org/)** is an interactive Web 3D bestiary of ten mythical creatures from the ancient Chinese *Classic of Mountains and Seas* (《山海经》), rendered in real-time **Chinese Gongbi ink-wash style (工笔淡彩 + 水墨线描)**.

- **Frontend Stack**: Vite 8 + React 19 (`StrictMode`) + TypeScript + Three.js (`~0.186.0`) + `@react-three/fiber` + `@react-three/drei` + `@react-three/postprocessing` + `zustand`
- **3D Asset Pipeline**: Hyper3D Rodin Gen-2.5 API (`pipeline/rodin/generate.ts`) + Headless Blender 5.2 LTS Python scripts (`pipeline/blender/*.py`) + `@gltf-transform/cli` (`meshopt` + WebP compression)
- **Audio**: Procedural Web Audio API synthesizer (`src/systems/audio/AudioEngine.ts`) — mountain wind, pentatonic Guqin harmonics, bronze chime bells, and beast-specific vocalizations/footsteps
- **Deployment**: GitHub Actions (`.github/workflows/deploy.yml`) → Cloudflare Workers Static Assets (`wrangler.jsonc`, custom domain `shanhaiworld.org`)

---

## 2. Essential Commands

| Command | Purpose |
| :--- | :--- |
| `pnpm dev` | Start local Vite dev server (default `http://localhost:5199` when run with `--port 5199`) |
| `pnpm typecheck` | Run TypeScript project-references check (`tsc -b`) across `src/` and `pipeline/` |
| `pnpm validate` | Verify Git LFS binary integrity, beast JSON metadata (`archetype`, `source`, `inferred`), and ≤ 15 MB per-beast budget |
| `pnpm build` | Typecheck and build production bundle into `dist/` |
| `pipeline/build_beast.sh <id> <body-job> [part:job:len ...]` | Run headless Blender normalization, archetype-specific auto-rigging & animation, and `gltf-transform` compression |
| `node scripts/shot.mjs <url> <out.png> [WxH] [waitMs]` | Headless Chrome screenshot that waits for `[beast] ready <id>` in console |
| `node scripts/closeups.mjs <url> <prefix> [count] [gapMs] [x,y,w,h]` | Capture multi-frame motion sequences to verify limb/appendage deformation |

---

## 3. Repository Layout

```text
shanhai/
├── AGENTS.md                        # Universal instructions for all AI coding agents
├── CLAUDE.md                        # Claude Code entry point & skill index
├── .claude/skills/build-beast/      # Step-by-step workflow for creating/updating a beast
├── content/
│   ├── asset-credits.json           # Third-party / AI asset license registry
│   └── beasts/<id>.json             # Classical source quotes, inferred design notes, archetype & parts
├── concept/<id>/                    # Orthographic 4-view turnarounds (Git LFS)
├── pipeline/
│   ├── build_beast.sh               # End-to-end Blender + gltf-transform build script
│   ├── validate.ts                  # Pre-build & CI validator (LFS, schema, size limits)
│   ├── rodin/
│   │   ├── generate.ts              # Rodin Gen-2.5 client with SHA-256 cache, credits.log & budget cap
│   │   └── jobs/*.json              # Rodin generation job specs
│   └── blender/
│       ├── normalize.py             # Mesh cleanup, unit scaling, +Z alignment, optional --trim-tail
│       ├── turnaround.py            # Pose correction & orthographic 4-view renderer for image-to-3D
│       ├── rig_quadruped.py         # Quadruped auto-rigger + 3-tier weight fallback + 4-beat walk
│       └── rig_sac.py               # Headless/faceless sac auto-rigger (e.g., Dijiang) + wing/leg mounts
├── public/
│   ├── models/<id>/*.glb            # Runtime compressed GLBs (Git LFS, ≤ 15 MB per beast)
│   └── llms.txt                     # Machine-readable project summary for web agents
└── src/
    ├── app/                         # App shell, Zustand store (?beast=<id>&action=idle|walk|special), beast index
    ├── scene/                       # Sky, 4-layer ink mountains, drifting mist, rice-paper ground & post-effect
    ├── beasts/<id>/                 # Per-beast React Three Fiber component & procedural appendage chains
    ├── systems/
    │   ├── ink/                     # Gongbi ink-wash GLSL shader (inkMaterial.ts) & calligraphic outline (inkify.ts)
    │   ├── vfx/                     # Watercolor particle system (FoxFire.tsx — cyan fox-fire / cinnabar dan-fire)
    │   └── audio/                   # Web Audio procedural synthesizer (AudioEngine.ts)
    └── ui/                          # Vertical scroll selector, classic text card, seal controls, action bar
```

---

## 4. Architectural Invariants & Hard Rules (Do Not Violate)

### 4.1 Do Not Assume "Head, Eyes, Four Legs, or Tail"
Mythical beasts in《山海经》have radically diverse anatomies. Every beast in `content/beasts/<id>.json` declares one of five **`archetype`** values:
- **`sac`** (e.g., `dijiang` 帝江): Headless and faceless ("浑敦无面目"), plump sac torso with `core` + `upper` breathing/dance bones and modular wing/leg mounts.
- **`avian`** (e.g., `bifang` 毕方 one-legged crane, `fenghuang` 凤凰): Bird torso with variable leg count (`1` centered at `x=0`, `2`, or `3`) and wings.
- **`serpentine`** (e.g., `yinglong` 应龙): Multi-segment undulating spine (`16–32` bones) with optional wings/limbs.
- **`quadruped`** (e.g., `jiuweihu` 九尾狐, `bo` 驳, `luwu` 陆吾, `qiongqi` 穷奇, `taotie` 饕餮, `kaiming` 开明兽): Four-legged torso; may have no native head (9 modular heads on `kaiming`), displaced eyes (underarm eyes on `taotie`), or 9 modular tails (`--trim-tail`).
- **`biped`**: Upright two-legged torso (may be headless like `xingtian`).

For the full 6-step production workflow, read **`.claude/skills/build-beast/SKILL.md`**.

### 4.2 Philological Strictness (`source` vs. `inferred`)
In `content/beasts/<id>.json` and `src/ui/Card.tsx`:
- **`source`** must contain **only verbatim classical quotes and chapter titles** from《山海经》.
- **`inferred`** must explicitly list all artistic/visual extrapolations (colors, markings, VFX) and their basis, displayed in a separate cinnabar-bordered section. Never mix inferred lore into `source`.

### 4.3 React 19 `StrictMode` & Cached `useGLTF` Scene Graphs
- `useGLTF(url).scene` is a cached global singleton.
- React 19 `StrictMode` double-invokes `useMemo` in development and **discards the second return value while keeping the first**.
- **NEVER mutate `scene` by attaching child nodes (`attachBone.add(holder)`) inside `useMemo`**. Create the `holder` and procedural meshes inside `useMemo`, and attach/detach them inside **`useEffect`**:
  ```ts
  useEffect(() => {
    rig.attach.add(rig.holder)
    return () => {
      rig.attach.remove(rig.holder)
      rig.mixer.stopAllAction()
    }
  }, [rig])
  ```
- When computing a holder's inverse rest rotation `restQ`, always compute `attachBone`'s rotation **relative to `scene`** (`attach.getWorldQuaternion(new Quaternion()).premultiply(scene.getWorldQuaternion(new Quaternion()).invert())`), excluding the outer `<group>` rotation.

### 4.4 Gongbi Ink-Wash Shader & Geometry Rules
- **No Mouse Head-Tracking**: Beasts do not twist their heads to follow the mouse pointer; movement comes purely from their animations (`idle` / `walk` / `special`) and proximity alert.
- **No `geometry.computeVertexNormals()` After Non-Uniform Scaling**: AI-generated meshes contain near-degenerate triangles where `computeVertexNormals()` produces `NaN` normals (rendering black). Transform existing normals via the inverse-transpose scale factors with a zero-length guard.
- **No `AdditiveBlending` on Rice-Paper Backgrounds**: Additive particles wash out to invisible white against the light `#efe6d2` rice-paper background. Use normal alpha blending with watercolor edge-pooling (`src/systems/vfx/FoxFire.tsx`).
- **No Negative Scale on Outlined Meshes**: Never mirror an appendage with `scale.x = -1` (it flips triangle winding and turns `BackSide` outlines inside-out). Mirror wings/limbs via rotation (e.g., `rotation.y = Math.PI - sweep`).

### 4.5 Secrets & Git LFS
- **Secrets**: `HYPER3D_API_KEY` lives exclusively in `.env.local` (git-ignored). Never hardcode or commit API keys.
- **Git LFS**: All binary assets (`*.glb`, `*.png`, `*.webp`, `*.hdr`, `*.ktx2`, `*.ogg`, `*.m4a`, `*.mp3`, `*.wav`) are tracked by Git LFS in `.gitattributes`. Run `pnpm validate` and `git lfs status` before committing.
