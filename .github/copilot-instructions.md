Read [`AGENTS.md`](../AGENTS.md) and [`.claude/skills/build-beast/SKILL.md`](../.claude/skills/build-beast/SKILL.md) before making changes.

- **Stack**: Vite 8 + React 19 (`StrictMode`) + TypeScript + Three.js (`~0.186.0`) + `@react-three/fiber` + headless Blender 5.2 LTS Python pipeline.
- **Verification**: Run `pnpm typecheck && pnpm validate && pnpm build` on every change.
- **Invariants**:
  - Keep verbatim《山海经》text (`source`) strictly separate from design extrapolations (`inferred`).
  - Respect the 5 beast archetypes (`sac`, `avian`, `serpentine`, `quadruped`, `biped`) — never hardcode quadruped/head assumptions.
  - Attach procedural scene-graph nodes (`holder`) in `useEffect`, never inside `useMemo`.
  - Track binary assets (`*.glb`, `*.png`, `*.webp`, etc.) with Git LFS.
