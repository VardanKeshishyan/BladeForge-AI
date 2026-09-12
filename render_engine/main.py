"""Headless Blender leading-edge erosion renderer.

Run with:
blender --background --python render_engine/main.py -- --job-file path/to/job.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
import time
import zipfile
from pathlib import Path

import bpy
from mathutils import Vector


def arguments() -> argparse.Namespace:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-file", required=True)
    return parser.parse_args(args)


def emit(progress: int, stage: str, message: str, **metadata: object) -> None:
    payload = {"progress": progress, "stage": stage, "message": message, "metadata": metadata}
    print(f"BLADEFORGE_PROGRESS {json.dumps(payload, separators=(',', ':'))}", flush=True)


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for material in list(bpy.data.materials):
        bpy.data.materials.remove(material)


def emission_material(name: str, color: tuple[float, float, float, float]):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = 1.0
    material.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def principled_material(
    name: str,
    color: tuple[float, float, float, float],
    roughness: float,
    metallic: float = 0.0,
):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    return material


def build_blade(material) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    sections = 36
    ring = 32
    for section in range(sections):
        z = -3.5 + 7.0 * section / (sections - 1)
        taper = 1.0 - 0.28 * section / (sections - 1)
        chord = 1.15 * taper
        thickness = 0.22 * taper
        twist = math.radians(-5 + 11 * section / (sections - 1))
        for index in range(ring):
            angle = 2 * math.pi * index / ring
            # Elliptical airfoil approximation. x=-chord is the leading edge.
            x = chord * math.cos(angle)
            y = thickness * math.sin(angle) * (0.72 + 0.28 * abs(math.cos(angle)))
            xr = x * math.cos(twist) - y * math.sin(twist)
            yr = x * math.sin(twist) + y * math.cos(twist)
            vertices.append((xr, yr, z))
    for section in range(sections - 1):
        for index in range(ring):
            nxt = (index + 1) % ring
            a = section * ring + index
            b = section * ring + nxt
            c = (section + 1) * ring + nxt
            d = (section + 1) * ring + index
            faces.append((a, b, c, d))
    mesh = bpy.data.meshes.new("BladeSegmentMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    blade = bpy.data.objects.new("BladeSegment", mesh)
    bpy.context.collection.objects.link(blade)
    blade.data.materials.append(material)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bevel = blade.modifiers.new("ManufacturingBevel", "BEVEL")
    bevel.width = 0.012
    bevel.segments = 2
    return blade


def create_patch(
    index: int,
    z: float,
    angle: float,
    span: float,
    width: float,
    depth: float,
    material,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1)
    patch = bpy.context.object
    patch.name = f"ErosionPatch_{index:03d}"
    # Overlay the leading edge. Scale and displacement are severity-derived.
    section_fraction = max(0.0, min(1.0, (z + 3.5) / 7.0))
    local_chord = 1.15 * (1.0 - 0.28 * section_fraction)
    patch.location = Vector((-local_chord - depth * 0.006, -0.02 + angle, z))
    patch.scale = Vector((depth * 0.018 + 0.012, width, span))
    patch.data.materials.append(material)
    displacement = patch.modifiers.new("IrregularErosion", "DISPLACE")
    texture = bpy.data.textures.new(f"ErosionNoise_{index:03d}", type="CLOUDS")
    texture.noise_scale = max(0.02, width * 0.45)
    texture.noise_depth = 2
    displacement.texture = texture
    displacement.strength = depth * 0.012
    return patch


def setup_camera() -> bpy.types.Object:
    bpy.ops.object.camera_add(location=(6.4, -6.4, 0.4))
    camera = bpy.context.object
    camera.data.type = "PERSP"
    bpy.context.scene.camera = camera
    return camera


def point_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def setup_light() -> tuple[bpy.types.Object, bpy.types.Object]:
    bpy.ops.object.light_add(type="AREA", location=(2.5, -3.5, 4.5))
    key = bpy.context.object
    key.data.shape = "DISK"
    key.data.size = 5.0
    bpy.ops.object.light_add(type="AREA", location=(-3.0, 2.5, 1.0))
    fill = bpy.context.object
    fill.data.size = 4.0
    return key, fill


def configure_render(width: int, height: int) -> None:
    scene = bpy.context.scene
    available_engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in available_engines else "BLENDER_EEVEE"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.image_settings.color_depth = "8"


def render(path: Path) -> None:
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def mask_bbox(mask_path: Path, width: int, height: int) -> list[int]:
    image = bpy.data.images.load(str(mask_path), check_existing=False)
    pixels = list(image.pixels[:])
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        offset = y * width * 4
        for x in range(width):
            if pixels[offset + x * 4] > 0.5:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
    bpy.data.images.remove(image)
    if max_x < min_x or max_y < min_y:
        raise RuntimeError("Rendered erosion mask is empty")
    # Blender pixel rows begin at the bottom; annotation coordinates begin at top-left.
    top = height - 1 - max_y
    return [min_x, top, max_x - min_x + 1, max_y - min_y + 1]


def set_materials(blade, patches, blade_material, patch_material) -> None:
    blade.data.materials[0] = blade_material
    for patch in patches:
        patch.data.materials[0] = patch_material


def write_annotations(
    output: Path,
    samples: list[dict[str, object]],
    width: int,
    height: int,
    annotation_format: str,
) -> None:
    annotations = output / "annotations"
    annotations.mkdir(exist_ok=True)
    if annotation_format == "coco_json":
        coco: dict[str, object] = {
            "info": {"description": "BladeForge procedural leading-edge erosion MVP"},
            "licenses": [],
            "categories": [{"id": 1, "name": "leading_edge_erosion"}],
            "images": [],
            "annotations": [],
        }
        for index, sample in enumerate(samples, start=1):
            bbox = sample["bbox"]
            coco["images"].append(
                {
                    "id": index,
                    "file_name": sample["image"],
                    "width": width,
                    "height": height,
                }
            )
            coco["annotations"].append(
                {
                    "id": index,
                    "image_id": index,
                    "category_id": 1,
                    "bbox": bbox,
                    "area": bbox[2] * bbox[3],
                    "iscrowd": 0,
                    "attributes": {"severity": sample["severity"], "seed": sample["seed"]},
                }
            )
        (annotations / "coco.json").write_text(json.dumps(coco, indent=2), encoding="utf-8")
    else:
        labels = annotations / "labels"
        labels.mkdir(exist_ok=True)
        for sample in samples:
            x, y, box_width, box_height = sample["bbox"]
            cx = (x + box_width / 2) / width
            cy = (y + box_height / 2) / height
            normalized_width = box_width / width
            normalized_height = box_height / height
            stem = Path(sample["image"]).stem
            (labels / f"{stem}.txt").write_text(
                f"0 {cx:.8f} {cy:.8f} {normalized_width:.8f} {normalized_height:.8f}\n",
                encoding="utf-8",
            )
        (annotations / "data.yaml").write_text(
            "path: ..\ntrain: images\nval: images\nnames:\n  0: leading_edge_erosion\n",
            encoding="utf-8",
        )


def package(output: Path, dataset_name: str) -> Path:
    archive = output / f"{dataset_name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file() and path != archive:
                bundle.write(path, path.relative_to(output))
    return archive


def main() -> None:
    args = arguments()
    job = json.loads(Path(args.job_file).read_text(encoding="utf-8"))
    output = Path(job["output_directory"]).resolve()
    if output.exists():
        shutil.rmtree(output)
    for folder in ("images", "masks", "metadata", "annotations"):
        (output / folder).mkdir(parents=True, exist_ok=True)

    width = int(job["image_width"])
    height = int(job["image_height"])
    image_count = int(job["image_count"])
    severity_min = int(job["severity_min"])
    severity_max = int(job["severity_max"])
    base_seed = int(job["seed"])
    config = job["config"]

    clean_scene()
    configure_render(width, height)
    composite = principled_material("GelcoatComposite", (0.72, 0.76, 0.79, 1), 0.38)
    erosion = principled_material("ErodedComposite", (0.16, 0.19, 0.20, 1), 0.92)
    black = emission_material("MaskBlack", (0, 0, 0, 1))
    white = emission_material("MaskWhite", (1, 1, 1, 1))
    blade = build_blade(composite)
    camera = setup_camera()
    key, fill = setup_light()
    scene = bpy.context.scene
    samples: list[dict[str, object]] = []
    started = time.monotonic()
    emit(1, "rendering", "Blender scene initialized.")

    for sample_index in range(image_count):
        seed = base_seed + sample_index
        rng = random.Random(seed)
        severity = rng.uniform(severity_min, severity_max)
        normalized = severity / 100.0
        pit_density = 0.08 + normalized * 0.77
        erosion_depth_mm = 0.1 + normalized * 2.9
        roughness = 0.35 + normalized * 0.60
        affected_span = 0.08 + normalized * 0.57
        patch_count = max(2, round(3 + pit_density * 18))
        patches = []
        for patch_index in range(patch_count):
            z = rng.uniform(-3.1, 3.1) * affected_span / 0.65
            patch = create_patch(
                patch_index,
                z=z,
                angle=rng.uniform(-0.045, 0.045),
                span=rng.uniform(0.025, 0.09) * (0.65 + normalized),
                width=rng.uniform(0.015, 0.055) * (0.7 + normalized),
                depth=erosion_depth_mm,
                material=erosion,
            )
            patches.append(patch)

        angle = math.radians(rng.uniform(-14, 14))
        distance = rng.uniform(7.8, 9.6)
        camera.location = Vector(
            (distance * math.cos(angle), -distance * math.sin(angle) - 5.4, rng.uniform(-0.6, 0.8))
        )
        camera.data.lens = 36 / math.tan(math.radians(float(config["camera_fov"])) / 2)
        point_at(camera, Vector((0, 0, rng.uniform(-0.4, 0.4))))

        preset_strength = {
            "overcast": (850, 420),
            "golden_hour": (1050, 260),
            "midday": (1450, 180),
            "cloudy": (620, 520),
        }[config["lighting_preset"]]
        key.data.energy = preset_strength[0] * rng.uniform(0.85, 1.15)
        fill.data.energy = preset_strength[1] * rng.uniform(0.85, 1.15)
        key.rotation_euler[2] = rng.uniform(-0.5, 0.5)
        erosion.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = roughness
        scene.world.color = (
            rng.uniform(0.025, 0.07),
            rng.uniform(0.03, 0.08),
            rng.uniform(0.04, 0.10),
        )

        file_stem = f"sample_{sample_index:06d}"
        image_relative = f"images/{file_stem}.png"
        mask_relative = f"masks/{file_stem}.png"
        metadata_relative = f"metadata/{file_stem}.json"
        set_materials(blade, patches, composite, erosion)
        render(output / image_relative)
        original_world = scene.world.color[:]
        set_materials(blade, patches, black, white)
        scene.world.color = (0, 0, 0)
        key.hide_render = True
        fill.hide_render = True
        render(output / mask_relative)
        key.hide_render = False
        fill.hide_render = False
        scene.world.color = original_world
        bbox = mask_bbox(output / mask_relative, width, height)

        parameters = {
            "seed": seed,
            "severity": round(severity, 4),
            "severity_label": "early" if severity < 34 else "moderate" if severity < 67 else "severe",
            "pit_density": round(pit_density, 5),
            "erosion_depth_mm": round(erosion_depth_mm, 5),
            "roughness": round(roughness, 5),
            "affected_span_fraction": round(affected_span, 5),
            "patch_count": patch_count,
            "camera_location": list(camera.location),
            "camera_fov": config["camera_fov"],
            "lighting_preset": config["lighting_preset"],
            "weather_enabled": bool(config.get("weather", False)),
            "bbox": bbox,
        }
        (output / metadata_relative).write_text(json.dumps(parameters, indent=2), encoding="utf-8")
        samples.append(
            {
                "image": image_relative,
                "mask": mask_relative,
                "metadata": metadata_relative,
                "bbox": bbox,
                "seed": seed,
                "severity": round(severity, 4),
            }
        )
        for patch in patches:
            bpy.data.objects.remove(patch, do_unlink=True)
        progress = max(2, min(88, round((sample_index + 1) / image_count * 88)))
        emit(progress, "rendering", f"Rendered sample {sample_index + 1} of {image_count}.")

    emit(90, "processing_annotations", "Deriving annotation exports from rendered masks.")
    write_annotations(output, samples, width, height, job["annotation_format"])
    manifest = {
        "schema_version": "1.0",
        "job_id": job["id"],
        "dataset_name": job["dataset_name"],
        "defect_type": "leading_edge_erosion",
        "blade_material": "gelcoat_composite_v1",
        "annotation_format": job["annotation_format"],
        "image_width": width,
        "image_height": height,
        "sample_count": len(samples),
        "renderer": "bladeforge_procedural_blender_v1",
        "samples": samples,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "README.md").write_text(
        "# BladeForge dataset\n\n"
        "This procedural MVP dataset contains aligned PNG RGB images and binary masks.\n"
        "Annotations are derived from the masks. Per-sample seeds and parameters are in `metadata/`.\n",
        encoding="utf-8",
    )
    package(output, job["dataset_name"])
    emit(
        99,
        "processing_annotations",
        "Dataset package validated locally.",
        elapsed_seconds=round(time.monotonic() - started, 3),
    )


if __name__ == "__main__":
    main()
