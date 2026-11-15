# Beast build recipes

`pnpm beast:recipe <id>` resolves the catalog entry, classical source, parts, scripts and assets. `pipeline/build_beast.sh <id>` builds the declared jobs from their downloaded `raw/<job-id>/` directories. It does not submit paid generation requests or change `ready`.

Without an explicit `recipe.prepareScript`, the builder normalizes the body and each extra part separately, then rigs the body and compresses all outputs. Legacy `prepare_<id>.py` discovery is informational: those scripts have different command-line interfaces and are not executed automatically.

An explicit preparation script can prepare the body and all extra parts together. It must produce `body_norm.glb` and `<part-id>_norm.glb` in the build directory. The builder verifies these files before rigging or publishing any model. Customize the script's interface with `prepareArgs`:

```json
{
  "recipe": {
    "mode": "custom",
    "prepareScript": "pipeline/blender/prepare_example.py",
    "prepareArgs": [
      "--body-in", "{body.raw}",
      "--wing-in", "{wing.raw}",
      "--out-dir", "{outDir}",
      "--body-length", "{body.length}",
      "--wing-span", "{wing.length}"
    ],
    "rigScript": "pipeline/blender/rig_example.py"
  }
}
```

The `example` filenames above illustrate the interface; replace them with scripts in the repository. Supported argument placeholders:

| Placeholder | Value |
| --- | --- |
| `{body.raw}` | Selected raw body GLB |
| `{body.out}` | Required `body_norm.glb` output path |
| `{body.length}` | Resolved body length |
| `{outDir}` | Isolated temporary build directory |
| `{<part-id>.raw}` | Selected raw GLB for that extra part |
| `{<part-id>.out}` | Required normalized output path for that extra part |
| `{<part-id>.length}` | Resolved length for that extra part |

Arguments are passed directly as argv, with spaces and empty arguments preserved. They are never evaluated as shell source. Unknown placeholders fail before Blender runs. If `prepareArgs` is omitted, the explicit script receives the two positional arguments `{body.raw}` and `{body.out}`.

The rig script receives `<normalized-body> <rigged-body> --preview <preview.png>`. It must export valid `idle`, `walk` and `special` clips. The builder compresses geometry with meshopt and textures with WebP, stages outputs, and copies them to `public/models/<id>/` after processing succeeds. A build completing does not establish visual acceptance: inspect anatomy, all three actions and close-up motion before setting `ready: true`.

Recipes may override compression for geometry or animation that requires it. For example, `"compression": { "weld": false, "resample": false, "meshoptLevel": "medium" }` preserves vertex separation and cubic animation curves during optimization. Only these three options are accepted (`weld`/`resample` booleans, `meshoptLevel` `medium` or `high`); omitted options retain the optimizer's existing defaults. Overrides apply to the body and every declared part of that beast. Validate the resulting compressed geometry and animation in the actual browser before acceptance.

Run the orchestration regression checks with:

```sh
node --test pipeline/build_beast.test.mjs
```

These checks use CLI fixtures to verify custom preparation, argument preservation, body-only recipes, the generic fallback, and failure isolation. Actual Blender builds and browser visual checks remain necessary for beast delivery.
