"""Gemini image edits confined to Blender-projected surface masks."""

from __future__ import annotations

import base64
import io
import json
import re
import zipfile
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageFilter

from bladeforge_worker.config import WorkerSettings


class GeminiEditError(RuntimeError):
    """Fail visibly; do not auto-retry a potentially billed generation."""


APPEARANCE = {
    "leading_edge_erosion": "Irregular fine pitting and worn gelcoat along the leading edge, transitioning to exposed composite; no brown dots or attached lumps.",
    "surface_crack": "Thin irregular branching hairline fractures in the coating, tapered ends, dark narrow fissures, not thick painted lines.",
    "trailing_edge_damage": "Localized fraying and splitting along the trailing edge, with fine exposed composite fibres.",
    "corrosion": "Irregular oxidized patches with fine pitting on exposed metal. Composite does not corrode like steel; use localized corrosion residue at a metal fitting if on a composite part.",
    "rust_staining": "Thin orange-brown runoff streaks from a plausible metal source, following gravity across the surface.",
    "paint_peeling": "Irregular missing paint flakes with thin chipped margins and exposed underlying primer, surface scale only.",
    "coating_loss": "Uneven worn-away coating with feathered boundaries and contrasting exposed substrate.",
    "scratches": "Fine directional abrasion grooves, variable length, width and depth, subtle exposed primer.",
    "dents": "Shallow smooth depressions conveyed by physically consistent shading and reflections; no attached bumps.",
    "lightning_strike": "Localized dark scorch with branching fine burns, a small charred strike site and composite fibre discoloration.",
    "holes": "Localized puncture with a dark recessed interior and thin irregular chipped rim, never an attached object.",
    "chips": "Small irregular missing coating fragments with sharp broken boundaries and exposed primer.",
    "delamination": "Localized composite layer separation with fine fracture boundaries and subtle shallow blistering, no large protruding chunks.",
    "oil_stains": "Translucent dark oily smears and gravity-driven drips with subtle wet sheen.",
    "dirt_buildup": "Uneven translucent grey-brown grime with fine speckles, streaks and soft accumulation boundaries; preserve underlying paint.",
    "ice_buildup": "Thin uneven frost and translucent ice adhering to the existing surface, restrained crystalline detail.",
    "structural_deformation": "Localized shallow warping conveyed within the masked surface by curvature shading and stress creases; preserve the overall silhouette and framing.",
}


def decode_mask(segmentation: dict, size: tuple[int, int]) -> Image.Image:
    width, height = size
    counts = segmentation.get("counts")
    if segmentation.get("size") != [height, width] or not isinstance(counts, list):
        raise GeminiEditError("Region mask dimensions or RLE are invalid.")
    if (
        any(type(n) is not int or n < 0 for n in counts)
        or sum(counts) != width * height
    ):
        raise GeminiEditError("Region mask RLE is invalid.")
    # COCO RLE is column-major, unlike Pillow's row-major storage.
    data = bytearray(width * height)
    offset = 0
    for index, length in enumerate(counts):
        if index % 2:
            data[offset : offset + length] = b"\xff" * length
        offset += length
    return Image.frombytes("L", (height, width), bytes(data)).transpose(
        Image.Transpose.TRANSPOSE
    )


def image_part(image: Image.Image) -> dict:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {
        "inlineData": {
            "mimeType": "image/png",
            "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }
    }


def build_prompt(metadata: dict, region: dict, layer: dict) -> str:
    defect = region["defect_id"]
    context_keys = (
        "seed",
        "camera",
        "camera_fov",
        "lighting_preset",
        "environment_id",
        "weather_intensity",
        "weather_enabled",
        "weather",
        "turbine_part_id",
        "crop_policy",
        "model_source",
        "defect_layers",
        "sensor_settings",
        "output_settings",
    )
    context = {key: metadata[key] for key in context_keys if key in metadata}
    specification = {
        "defect_id": defect,
        "appearance": APPEARANCE.get(defect, defect),
        "region_id": region.get("region_id"),
        "surface_id": region.get("surface_id"),
        "part_id": region.get("part_id"),
        "severity_percent": region.get("severity"),
        "settings": layer,
        "scene": context,
    }
    return (
        "Edit IMAGE 1, the existing wind-turbine inspection photograph/render. Return exactly ONE edited image. "
        "IMAGE 2 is a pixel-aligned binary permission mask: white is editable, black must remain unchanged. "
        "IMAGE 3 shows that same allowed region highlighted for location only. Never reproduce its highlight. "
        "Add ONLY the current defect specified in the JSON, entirely on the original surface inside white pixels. "
        "Other defect layers in scene data are context; do not add or change them in this step. "
        "Keep the exact camera, perspective, position, scale, turbine geometry, silhouette, background, weather, "
        "lighting, shadows, image dimensions and all unmasked pixels. Do not crop, zoom, rotate or reframe. "
        "Keep damage physically plausible at the scene's scale; painted blades are composite, towers are painted steel. "
        "Use irregular natural surface texture and lighting-consistent relief, no floating objects, extra meshes, "
        "cartoon symbols, labels, coloured brush strokes or large attached chunks. "
        "Make the requested damage clearly discernible within the region at the specified severity, without "
        "turning the entire white region into a solid patch. Severity, coverage/density, size_scale, opacity, "
        "rotation_deg, spread and randomness control appearance; the mask is a hard location boundary. "
        "Region colour identifiers are UI labels, not literal defect paint. Preserve existing edits elsewhere. "
        "For shape-changing defects, depict only the surface evidence possible within this boundary; do not alter silhouette. "
        "Do not return a mask, collage or explanation instead of the edited source image.\n"
        + json.dumps(specification, ensure_ascii=False, indent=2)
    )


def composite_edit(
    source: Image.Image, edited: Image.Image, mask: Image.Image
) -> Image.Image:
    source, edited = source.convert("RGB"), edited.convert("RGB")
    if abs(edited.width / edited.height - source.width / source.height) > 0.01:
        raise GeminiEditError(
            "Gemini changed the image aspect ratio. The edit was rejected."
        )
    if edited.size != source.size:
        edited = edited.resize(source.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(source, edited)
    channels = difference.split()
    magnitude = ImageChops.lighter(
        ImageChops.lighter(channels[0], channels[1]), channels[2]
    )
    changed = ImageChops.multiply(magnitude.point(lambda x: 255 if x > 3 else 0), mask)
    if sum(changed.histogram()[1:]) < 4:
        raise GeminiEditError(
            "Gemini returned no visible change inside the selected region. No unchanged result was delivered."
        )
    # Feather inward only; every pixel outside the binary mask stays byte-identical.
    alpha = ImageChops.multiply(mask, mask.filter(ImageFilter.GaussianBlur(0.7)))
    return Image.composite(edited, source, alpha)


async def request_edit(
    client: httpx.AsyncClient,
    settings: WorkerSettings,
    source: Image.Image,
    mask: Image.Image,
    prompt: str,
) -> Image.Image:
    model = settings.gemini_image_model
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", model):
        raise GeminiEditError("GEMINI_IMAGE_MODEL must be a model ID, not a URL.")
    overlay = Image.composite(
        Image.blend(source, Image.new("RGB", source.size, "#ff0066"), 0.5), source, mask
    )
    prompt += f"\nRequired output dimensions: {source.width} x {source.height} pixels."
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    image_part(source),
                    image_part(mask),
                    image_part(overlay),
                ],
            }
        ],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    try:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={
                "x-goog-api-key": settings.gemini_api_key.get_secret_value().strip()
            },
            json=payload,
        )
    except httpx.HTTPError:
        raise GeminiEditError(
            "Gemini could not be reached or timed out. Check connectivity; the job was not automatically retried."
        ) from None
    if response.is_error:
        advice = {
            400: "Check model access and request compatibility.",
            401: "Check GEMINI_API_KEY in render_worker/.env.gemini.local.",
            403: "Check the API key, project permissions and model access.",
            404: "Check GEMINI_IMAGE_MODEL is available to your API project.",
            429: "Gemini quota is exhausted. Check image-generation billing and rate limits.",
        }
        raise GeminiEditError(
            f"Gemini HTTP {response.status_code}. {advice.get(response.status_code, 'The service failed; try again later.')} No automatic paid retry was made."
        )
    try:
        body = response.json()
        for candidate in body.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if part.get("thought"):
                    continue
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if str(
                    inline.get("mimeType") or inline.get("mime_type", "")
                ).startswith("image/"):
                    image = Image.open(
                        io.BytesIO(base64.b64decode(inline["data"], validate=True))
                    )
                    image.load()
                    return image.convert("RGB")
    except (ValueError, KeyError, OSError):
        raise GeminiEditError("Gemini returned an invalid image response.") from None
    raise GeminiEditError(
        "Gemini returned no image (possibly blocked or text-only). Check model access; no unchanged render was delivered."
    )


async def edit_dataset(
    output: Path, settings: WorkerSettings, *, client=None, progress=None
) -> None:
    if client is None:
        async with httpx.AsyncClient(timeout=settings.gemini_timeout_seconds) as owned:
            return await edit_dataset(output, settings, client=owned, progress=progress)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Check all masks before making any billable requests.
    prepared = []
    for sample in manifest["samples"]:
        metadata = json.loads((output / sample["metadata"]).read_text(encoding="utf-8"))
        if metadata.get("image_edit_backend") != "gemini":
            raise GeminiEditError(
                "Gemini needs a clean guidance render. Submit the job again with the Gemini worker enabled."
            )
        masks = []
        for region in sample.get("instances", []):
            if region.get("fallback_annotation"):
                raise GeminiEditError(
                    "Artificial fallback annotations cannot be used as Gemini masks."
                )
            mask = decode_mask(
                region["segmentation"], (sample["width"], sample["height"])
            )
            if sum(mask.histogram()[1:]) < 9:
                raise GeminiEditError(
                    f"The {region['defect_id']} region is too small in this view. Move the camera closer or paint a larger region."
                )
            masks.append((region, mask))
        prepared.append((sample, metadata, masks))
    requested = set(manifest.get("defect_types") or [])
    visible = {r["defect_id"] for _, _, masks in prepared for r, _ in masks}
    if not requested.issubset(visible):
        raise GeminiEditError(
            "Some selected defects have no visible mask: "
            + ", ".join(sorted(requested - visible))
        )
    total = sum(len(masks) for _, _, masks in prepared)
    completed = 0
    for sample, metadata, masks in prepared:
        image_path = output / sample["image"]
        with Image.open(image_path) as image:
            edited = image.convert("RGB")
        stem = image_path.stem
        guidance_dir = output / "guidance" / stem
        guidance_dir.mkdir(parents=True, exist_ok=True)
        edited.save(guidance_dir / "source.png")
        for index, (region, mask) in enumerate(masks):
            layer_index = region.get("layer_index")
            layers = metadata.get("defect_layers") or []
            layer = (
                layers[layer_index]
                if isinstance(layer_index, int) and 0 <= layer_index < len(layers)
                else {}
            )
            prompt = build_prompt(metadata, region, layer)
            mask.save(guidance_dir / f"region_{index:03d}.png")
            (guidance_dir / f"region_{index:03d}.json").write_text(
                json.dumps(
                    {
                        "defect_id": region["defect_id"],
                        "region_id": region.get("region_id"),
                        "prompt": prompt,
                        "settings": layer,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if progress:
                await progress(completed, total, region["defect_id"])
            result = await request_edit(client, settings, edited, mask, prompt)
            edited = composite_edit(edited, result, mask)
            completed += 1
        edited.save(image_path)
        if sample.get("crop"):
            crop = sample["crop"]
            box = crop["source_crop_box"]
            x, y, w, h = box
            edited.crop((x, y, x + w, y + h)).save(output / crop["image"])
        details = {
            "provider": "gemini",
            "model": settings.gemini_image_model,
            "outside_mask_preserved": True,
            "region_count": len(masks),
            "annotation_semantics": "edit_region_guidance_unverified",
            "visual_defects_verified": False,
        }
        metadata["image_edit"] = details
        sample["image_edit"] = details
        (output / sample["metadata"]).write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
    manifest["image_edit"] = {
        "provider": "gemini",
        "model": settings.gemini_image_model,
        "annotation_semantics": "edit_region_guidance_unverified",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    coco_path = output / "annotations" / "coco.json"
    if coco_path.exists():
        coco = json.loads(coco_path.read_text(encoding="utf-8"))
        coco["info"]["description"] = (
            "Gemini edited BladeForge images. Annotations describe edit regions, not verified defect segmentation."
        )
        for annotation in coco["annotations"]:
            annotation.setdefault("attributes", {})["annotation_semantics"] = (
                "edit_region_guidance_unverified"
            )
        coco_path.write_text(json.dumps(coco, indent=2), encoding="utf-8")
    with (output / "README.md").open("a", encoding="utf-8") as readme:
        readme.write(
            "\nGemini edited these RGB images within rendered surface guidance masks. "
            "Pixels outside the masks are preserved. The original image, masks and prompts are in guidance/. "
            "COCO/YOLO annotations describe requested editing regions, NOT verified pixel-accurate AI defect labels. "
            "Review/relabel before using these images as training ground truth.\n"
        )
    archive = output / f"{manifest['dataset_name']}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file() and path != archive:
                bundle.write(path, path.relative_to(output))
