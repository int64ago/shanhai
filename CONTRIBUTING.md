# Contributing to Shanhai World (山海异兽录)

Thank you for your interest in contributing to **Shanhai World** ([shanhaiworld.org](https://shanhaiworld.org/))! Whether you are a human developer, philologist, 3D technical artist, or an AI coding agent, this guide explains how to contribute cleanly.

---

## 1. Prerequisites

- **Node.js** `>= 22` (Node `24` recommended)
- **pnpm** `>= 10`
- **Git LFS** (`git lfs install` — required for `.glb` and `.png` assets)
- **Blender** `5.2 LTS` at `/Applications/Blender.app` (only required if running the offline 3D asset pipeline under `pipeline/blender/`)

```bash
git clone git@github.com:int64ago/shanhai.git
cd shanhai
git lfs pull
pnpm install
pnpm dev
```

---

## 2. Adding or Updating a Mythical Beast

We use an **archetype-driven, scriptable pipeline** documented in detail in:

- **[`AGENTS.md`](./AGENTS.md)** — Architecture & engineering invariants
- **[`.claude/skills/build-beast/SKILL.md`](./.claude/skills/build-beast/SKILL.md)** — Step-by-step workflow for all 5 anatomical archetypes (`sac`, `avian`, `serpentine`, `quadruped`, `biped`)

### Core Rules for Beast Contributions

1. **Textual Integrity (`content/beasts/<id>.json`)**:
   - `source`: Verbatim《山海经》classical Chinese quotes and chapter names only.
   - `inferred`: All artistic extrapolations (palette, markings, VFX) must be listed separately with their basis.
2. **Asset Budget**:
   - Total compressed `.glb` size per beast in `public/models/<id>/` must be **≤ 15 MB** (typically **1.5–3.0 MB** after `gltf-transform` WebP + `meshopt` compression).
3. **Visual Self-Check**:
   - Capture `idle`, `walk`, and `special` screenshots via `scripts/shot.mjs` and motion close-ups via `scripts/closeups.mjs`.
   - Run `pnpm typecheck && pnpm validate && pnpm build` before opening a Pull Request.
