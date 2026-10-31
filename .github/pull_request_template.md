## Summary

- What changed and why?

## Verification Checklist

- [ ] `pnpm typecheck` passes
- [ ] `pnpm validate` passes (all `ready: true` beasts have valid metadata, LFS binary GLBs, and total size ≤ 15 MB)
- [ ] `pnpm build` succeeds without warnings
- [ ] Visual inspection completed via `scripts/shot.mjs` (`idle`, `walk`, `special`) and `scripts/closeups.mjs`
- [ ] New binary assets (`*.glb`, `*.png`, `*.webp`, `*.ogg`, `*.m4a`) are tracked via Git LFS (`git lfs status`)
