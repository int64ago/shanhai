# CLAUDE.md

Please read **[`AGENTS.md`](./AGENTS.md)** first for the full architecture, commands, and engineering invariants of **Shanhai World (《山海异兽录》, https://shanhaiworld.org/)**.

## Quick Reference for Claude Code

- **Beast Production Skill**: When creating, rigging, or optimizing any mythical beast, load and follow **[`.claude/skills/build-beast/SKILL.md`](./.claude/skills/build-beast/SKILL.md)** (`/build-beast`).
- **Verification**:
  - Always run `pnpm typecheck && pnpm validate && pnpm build` before finishing code or asset changes.
  - Visually inspect 3D/shader/animation changes using `node scripts/shot.mjs "http://localhost:5199/?beast=<id>&action=idle|walk|special" <out.png>` and `node scripts/closeups.mjs`, then inspect the output images with `Read`.
- **Git & LFS**:
  - Large binary assets (`*.glb`, `*.png`, `*.webp`, etc.) must be tracked by Git LFS (`git lfs status`).
  - Never include `HYPER3D_API_KEY` from `.env.local` in any tracked file or commit diff.
