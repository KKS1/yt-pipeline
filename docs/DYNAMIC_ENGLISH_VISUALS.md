# Dynamic English Visuals Prototype

This is an opt-in prototype for `english-shorts`. The normal loop-based pipeline
remains the default.

## Manual setup

1. Create transparent waist-up host images:

   ```text
   assets/characters/emma/body.png
   assets/characters/liam/body.png
   ```

2. Add one vertical or high-resolution background:

   ```text
   assets/dynamic_backgrounds/test_scene.png
   ```

3. Install Rhubarb Lip Sync and expose the binary with one of these options:

   ```bash
   export RHUBARB_BIN=/absolute/path/to/rhubarb
   ```

   or:

   ```text
   tools/rhubarb/rhubarb
   ```

4. Adjust mouth placement if needed in:

   ```text
   assets/characters/character_config.json
   ```

The placeholder mouth PNGs are generated automatically in
`assets/characters/generated_mouths/`.

## Run

Dynamic visuals are prototype-only and cannot upload directly:

```bash
python scripts/manual_run.py --channel english-shorts --dynamic-visuals --no-upload
```

Without `--dynamic-visuals`, `english-shorts` continues to use the existing
`assets/english_shorts_visuals` loop workflow.
