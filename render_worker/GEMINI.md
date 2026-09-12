# Gemini surface editing

1. Open `render_worker/.env.gemini.local` and paste a Google AI Studio key after `GEMINI_API_KEY=`.
2. Restart the render worker. New jobs automatically use Gemini when the key is nonempty.
   From `render_worker`: `..\.venv\Scripts\python.exe -m bladeforge_worker.main`
3. Submit a job with the desired camera, selected part and painted defect regions.

No frontend key or additional SDK is needed. `Pillow` is included in worker dependencies.
The key stays in the worker, is excluded from git, and is never included in job files,
prompts or downloads. Clear the key and restart to return to Blender-only rendering.
The default model is `gemini-3.1-flash-image`; `GEMINI_IMAGE_MODEL` can override it.
Your API project needs access and image-generation quota; a key alone does not grant
free usage. Quota, permission and missing-image errors are reported on the job.

The worker renders a clean image and camera-aligned surface masks. Paint hits are
resolved on the specific model surface in world coordinates to avoid repeated UVs.
No procedural defect geometry is visible in the Gemini source image. For unpainted
layers the renderer selects a deterministic surface location. Invisible or tiny regions
produce a clear error before requests are sent; they are never replaced by invented boxes.

For each visible region Gemini receives the current image, a binary mask, a highlighted
location guide, and the actual defect and scene settings. Only pixels inside that region
are composited back; other pixels remain identical. Multiple regions are edited in order.
The model's generated appearance inside a mask cannot be guaranteed by prompting.
Shape-changing defects are restricted to surface evidence within the original silhouette.

The dataset ZIP, RGB previews and crops contain the edited images. `guidance/` contains
the original render, per-region masks and exact prompts for review. Camera/environment
metadata stays attached. Masks and COCO/YOLO labels describe **editing regions**, not
verified AI defect segmentation. Review and relabel before using them as ground truth.

API calls are made once per visible region per image. Failed Gemini jobs are not
automatically retried to avoid repeated charges. Cancellation interrupts waiting for the
response but cannot undo a request already accepted by Google.

API reference: https://ai.google.dev/gemini-api/docs/generate-content/image-generation
