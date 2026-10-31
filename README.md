<div align="center">

<a href="https://shanhaiworld.org/">
  <img src="./docs/images/banner.jpg" width="100%" alt="山海异兽录 · Shanhai World — Interactive 3D Bestiary of the Classic of Mountains and Seas" />
</a>

<br />

[![shanhaiworld.org](https://img.shields.io/badge/Live_Scroll-shanhaiworld.org-b5322a?style=flat-square)](https://shanhaiworld.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/int64ago/shanhai/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/int64ago/shanhai/actions/workflows/ci.yml)
[![Cloudflare](https://img.shields.io/github/actions/workflow/status/int64ago/shanhai/deploy.yml?branch=main&style=flat-square&label=Cloudflare)](https://github.com/int64ago/shanhai/actions/workflows/deploy.yml)
[![Agent Native](https://img.shields.io/badge/Agent_Native-AGENTS.md_%7C_CLAUDE.md-2f5a53?style=flat-square)](./AGENTS.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-6b5a3a?style=flat-square)](./LICENSE)

<p align="center">
  <b>English</b> &nbsp;·&nbsp; <a href="./README.zh-CN.md">简体中文</a> &nbsp;·&nbsp; <a href="https://shanhaiworld.org/">Live Bestiary ↗</a>
</p>

</div>

---

**Shanhai World (《山海异兽录》)** is an interactive Web 3D bestiary of mythical creatures from the ancient Chinese cosmography *Classic of Mountains and Seas* (《山海经》), rendered in real-time **Chinese Gongbi ink-wash style (工笔淡彩 + 水墨线描)** at **[shanhaiworld.org](https://shanhaiworld.org/)**.

---

## Design Philosophy

- **Real-Time Gongbi Ink-Wash Shader (`src/systems/ink/`)** — Two-step watercolor washes with water-edge pooling over procedural rice-paper grain, paired with variable-pressure calligraphic outlines (`gl_Position` depth-biased back-face hulls).
- **Archetype-Driven Modular Anatomy** — Mythical beasts in《山海经》do not all have a head, eyes, four legs, or a tail. Every creature is built from one of **five anatomical archetypes** (`sac`, `avian`, `serpentine`, `quadruped`, `biped`) plus **modular procedural appendages** (nine tails, four wings, six legs, nine human-faced heads, underarm eyes).
- **Strict Philological Separation** — Every vertical scroll card separates **verbatim classical citations (`原文`)** from **modern artistic extrapolations (`设计`)** in a distinct cinnabar-bordered column.

---

## Five Anatomical Archetypes & Bestiary Roster

| Beast | Classical Citation (《山海经》) | Archetype | Modular Appendages | Status |
| :--- | :--- | :--- | :--- | :---: |
| **[九尾狐 · Jiuweihu](https://shanhaiworld.org/?beast=jiuweihu)** | 《南山经》：“其状如狐而九尾，其音如婴儿，能食人，食者不蛊。” | `quadruped` | 9 staggered procedural tails + cyan fox-fire | **Live** |
| **[帝江 · Dijiang](https://shanhaiworld.org/?beast=dijiang)** | 《西山经》：“其状如黄囊，赤如丹火，六足四翼，浑敦无面目，是识歌舞。” | `sac` (faceless) | 4 feathered wings + 6 tripod-gait legs + chime-dance | **Live** |
| **驳 · Bo** | 《西山经》：“其状如马，白身黑尾，一角，虎牙爪，音如鼓。” | `quadruped` | Single horn + drum-pulse chest | Planned |
| **陆吾 · Luwu** | 《西山经》：“其神状虎身而九尾，人面而虎爪。” | `quadruped` | Human-faced tiger torso + 9 tails | Planned |
| **毕方 · Bifang** | 《西山经》：“其状如鹤，一足，赤文青质而白喙，其鸣自叫也。” | `avian` | Single central leg (`x = 0`) + fire plumes | Planned |
| **穷奇 · Qiongqi** | 《海内北经》：“其状如虎，有翼。” | `quadruped` | 2 feathered wing chains | Planned |
| **饕餮 · Taotie** | 《北山经》：“其状如羊身人面，其目在腋下，虎齿人爪。” | `quadruped` | Displaced underarm eyes | Planned |
| **开明兽 · Kaiming** | 《海内西经》：“身大类虎而九首，皆人面，东向立昆仑上。” | `quadruped` | 9 independent neck & head chains | Planned |
| **凤凰 · Fenghuang** | 《南山经》：“其状如鸡，五采而文，名曰凤凰。” | `avian` | Five-color trailing tail plumes | Planned |
| **应龙 · Yinglong** | 《大荒东经》：“应龙处南极，杀蚩尤与夸父。” | `serpentine` | 32-segment undulating spine + 2 wings | Planned |

---

## Automated 3D Production Pipeline

Every beast is produced through a reproducible, script-driven pipeline (`pipeline/build_beast.sh`):

| Stage | Tooling | What It Does |
| :--- | :--- | :--- |
| **1. Spec & Decomposition** | `content/beasts/<id>.json` | Defines verbatim《山海经》sources, inferred design notes, `archetype`, and modular appendage jobs. |
| **2. Two-Stage 3D Generation** | `pipeline/rodin/generate.ts` + `turnaround.py` | Generates a Stage-1 base mesh, corrects posture in headless Blender to render 4 orthographic views (`concept/<id>/`), then runs Rodin Gen-2.5 `Extreme-High` (50k tris, 12K textures). |
| **3. Archetype Auto-Rigging** | `pipeline/blender/rig_<archetype>.py` | Normalizes scale/orientation (`+Z` forward, `z = 0` ground), builds the archetype skeleton with 3-tier weight fallback, and bakes `idle`, `walk`, and `alert` NLA cycles. |
| **4. Compression & Validation** | `gltf-transform` + `pipeline/validate.ts` | Compresses textures to WebP and geometry via `meshopt` (~1.5 MB per beast), verifying Git LFS binary integrity and the ≤ 15 MB budget. |
| **5. Ink-Wash Web Runtime** | `src/systems/ink/` + `src/beasts/<id>/` | Applies Gongbi watercolor shading, calligraphic outlines, procedural appendage bone chains, watercolor particles, and Web Audio synthesis. |

---

## Quick Start

Requires **Node.js >= 22**, **pnpm >= 10**, and **Git LFS** (`git lfs install`).

```bash
git clone git@github.com:int64ago/shanhai.git
cd shanhai && git lfs pull
pnpm install
pnpm dev
```

```bash
pnpm typecheck   # TypeScript check across app and pipeline
pnpm validate    # Verify Git LFS binaries, beast JSON schemas, and <= 15 MB budget
pnpm build       # Build production bundle into dist/
```

---

## AI Agent-Native Engineering

This repository is built for first-class collaboration with **Claude Code, OpenAI Codex, Grok, Cursor, Windsurf, GitHub Copilot, and web-browsing LLM agents**:

| File | Target Agents | Purpose |
| :--- | :--- | :--- |
| **[`AGENTS.md`](./AGENTS.md)** | Codex, Grok, Cursor, Windsurf, Devin, Claude | Architecture, commands, React 19 `StrictMode` scene-graph rules, GLSL ink shader invariants, and Git LFS rules. |
| **[`CLAUDE.md`](./CLAUDE.md)** | Claude Code | Quick entry point and verification checklist. |
| **[`.claude/skills/build-beast/SKILL.md`](./.claude/skills/build-beast/SKILL.md)** | Claude Code (`/build-beast`) & all agents | End-to-end 6-step workflow for creating, rigging, and visually verifying any mythical beast across all 5 archetypes. |
| **[`.cursorrules`](./.cursorrules)** & **[`.github/copilot-instructions.md`](./.github/copilot-instructions.md)** | Cursor, Windsurf, GitHub Copilot | Editor & PR coding agent rules. |
| **[`public/llms.txt`](./public/llms.txt)** | Web-browsing LLMs (`shanhaiworld.org/llms.txt`) | Machine-readable summary of the project, beasts, and classical citations. |

---

## Deployment (`shanhaiworld.org`)

Pushes to `main` run [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) and [`.github/workflows/deploy.yml`](./.github/workflows/deploy.yml), deploying `dist/` to **[https://shanhaiworld.org/](https://shanhaiworld.org/)** via Cloudflare Workers Static Assets ([`wrangler.jsonc`](./wrangler.jsonc)). Configure `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in **Settings → Secrets and variables → Actions** to enable live publishing.

---

## License

Code is licensed under the **[MIT License](./LICENSE)**. Asset attributions are documented in [`content/asset-credits.json`](./content/asset-credits.json).
