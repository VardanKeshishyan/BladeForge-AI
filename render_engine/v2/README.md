# BladeForge render engine v2

Cycles-first headless Blender renderer for the full procedural wind turbine,
multi-defect layers, environments, camera orbit, and region-gated placement.

## Run

```bash
blender --background --python render_engine/v2/main.py -- --job-file /path/to/job.json
```

`job.json` uses the same top-level fields as the legacy engine (`id`,
`dataset_name`, `image_count`, `image_width`, `image_height`, `severity_min`,
`severity_max`, `annotation_format`, `seed`, `output_directory`, `config`) plus
v2 config keys such as `environment_id`, `weather_intensity`, `turbine_part_id`,
`camera_view`, `generate_all_angles`, `defect_layers`, `region_document`,
`crop_policy`, `model_asset_key`, and `hdri_asset_key`.

Progress lines are printed as:

```text
BLADEFORGE_PROGRESS {"progress":…,"stage":…,"message":…,"metadata":{…}}
```

## Worker wiring

Point the worker at this script when using v2:

- Set `RENDER_ENGINE_VERSION=v2` (maps to `WorkerSettings.render_engine_version`)
- Or set `config.render_engine` to `"v2"` on the job
- Ensure `render_engine_v2_path` resolves to `render_engine/v2/main.py`

Legacy jobs keep using `render_engine/main.py` when the version is `legacy`.

## Output

Each job writes `images/`, `masks/`, `metadata/`, `annotations/`, `manifest.json`
(with `"renderer": "bladeforge_cycles_v2"` and the Blender engine name), and a
ZIP archive of the dataset.
