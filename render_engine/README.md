# BladeForge render engine

`main.py` is executed by Blender, not a normal Python interpreter:

```bash
blender --background --python render_engine/main.py -- --job-file /work/JOB_ID/job.json
```

The MVP builds a procedural composite blade segment and a reproducible set of
leading-edge erosion patches. It is an honest procedural renderer intended to
prove the pipeline and annotation alignment; it is not advertised as a
photorealistic replacement for a calibrated blade asset and measured material
library.

Each sample reuses one scene and camera for two renders:

1. RGB with composite and erosion materials.
2. A black/white emission pass with the same geometry and camera.

The script reads the actual mask pixels to calculate each bounding box. Seeds
and sampled physical/render parameters are written to per-image metadata.

