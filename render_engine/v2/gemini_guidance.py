"""Surface-only guidance for Gemini. These meshes are NEVER visible in RGB.

The browser paints UV brush strokes on explicitly hit faces. Resolve those faces
from world hits instead of trusting triangle indices across FBX/OBJ importers.
"""

import math

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform


def spawn_regions(
    layer, parts, document, rng, sample_index, layer_index, engine, placement=None
):
    strokes = (document or {}).get("strokes") or []
    region_id = layer.get("region_id")
    targets = engine.objects_for_part(parts, str(layer.get("part_id") or "blades"))
    placed = None
    if not region_id:
        placed = placement or engine.pick_placement(
            parts,
            str(layer.get("part_id") or "blades"),
            str(layer["defect_id"]),
            None,
            None,
            rng,
        )
        targets = [placed[0]] if placed is not None else []
    result = []
    for host in targets:
        surface_id = engine.surface_id_for_object(host)
        selected = [
            s
            for s in strokes
            if engine._stroke_fields(s)[0] == region_id
            and engine._stroke_fields(s)[4] == surface_id
        ]
        if region_id and not selected:
            continue
        vertices = [host.matrix_world @ v.co for v in host.data.vertices]
        host.data.calc_loop_triangles()
        triangles = list(host.data.loop_triangles)
        tree = BVHTree.FromPolygons(
            vertices, [tuple(t.vertices) for t in triangles], all_triangles=True
        )
        uv_data = host.data.uv_layers.active.data
        uv_min = [min(uv.uv[axis] for uv in uv_data) - 0.5 for axis in (0, 1)]
        uv_span = max(
            max(uv.uv[axis] for uv in uv_data) - uv_min[axis] + 0.5 for axis in (0, 1)
        )

        def atlas(uv):
            return ((uv[0] - uv_min[0]) / uv_span, (uv[1] - uv_min[1]) / uv_span)

        def resolve_hit(hit):
            nearest, normal, triangle_id, distance = tree.find_nearest(Vector(hit))
            if triangle_id is None:
                raise RuntimeError(
                    "Could not resolve a paint hit on the imported model."
                )
            triangle = triangles[triangle_id]
            triangle_uvs = [Vector((*uv_data[i].uv, 0)) for i in triangle.loops]
            uv = barycentric_transform(
                nearest, *(vertices[i] for i in triangle.vertices), *triangle_uvs
            )
            return nearest, normal, triangle.polygon_index, distance, atlas(uv)

        face_ids = set()
        centers = []
        brushes = []
        if region_id:
            # Include chronological paint/erase strokes for this surface so later
            # colours replace earlier ones, matching the viewport overlay.
            for stroke in strokes:
                sid, radius, points, mode, target = engine._stroke_fields(stroke)
                if target != surface_id or not points:
                    continue
                world_hits = (
                    stroke.get("world_points") or stroke.get("worldPoints") or []
                )
                if len(world_hits) != len(points):
                    raise RuntimeError(
                        "Paint mask is missing world hit data. Repaint the selected region once."
                    )
                resolved_points = []
                for hit in world_hits:
                    nearest, normal, face_id, distance, mapped_uv = resolve_hit(hit)
                    if distance > 0.1:
                        raise RuntimeError(
                            "Paint mask does not align with the imported model. Repaint this model."
                        )
                    resolved_points.append(mapped_uv)
                    if sid == region_id and mode == "paint":
                        face_ids.add(face_id)
                        centers.append((nearest, normal))
                brushes.append(
                    (
                        resolved_points,
                        radius / uv_span,
                        sid == region_id and mode == "paint",
                    )
                )
        else:
            # Deterministic model-surface placement when the user has not painted.
            if placed is None or placed[0] != host:
                continue
            _, location, uv, normal = placed
            nearest, normal, face_id, _, uv = resolve_hit(location)
            if face_id is None:
                continue
            face_ids.add(face_id)
            centers.append((nearest, normal))
            radius = min(0.25, max(0.015, 0.06 * float(layer.get("size_scale", 1))))
            brushes = [([uv], radius / uv_span, True)]
        if not centers:
            continue
        # Each host gets an independent mask even when its UVs are shared.
        mesh = bpy.data.meshes.new(f"GeminiMask_{layer_index}_{host.name}")
        coords, faces, uvs = [], [], []
        normal_matrix = host.matrix_world.to_3x3().inverted().transposed()
        for face_id in sorted(face_ids):
            poly = host.data.polygons[face_id]
            offset = len(coords)
            normal = (normal_matrix @ poly.normal).normalized()
            for loop_index in poly.loop_indices:
                vertex_index = host.data.loops[loop_index].vertex_index
                coords.append(vertices[vertex_index] + normal * 0.002)
                uvs.append(atlas(uv_data[loop_index].uv))
            faces.append(tuple(range(offset, len(coords))))
        mesh.from_pydata(coords, [], faces)
        mesh.uv_layers.new(name="UVMap")
        for loop in mesh.loops:
            mesh.uv_layers.active.data[loop.index].uv = uvs[loop.vertex_index]
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.hide_render = True
        obj["bladeforge_mask_only"] = True
        obj["bladeforge_gemini_guidance"] = True
        mat = brush_material(mesh.name, brushes)
        mesh.materials.append(mat)
        obj["bladeforge_guidance_material"] = mat.name
        location, normal = centers[0]
        result.append(
            {
                "instance_id": f"region:{sample_index}:{layer_index}:{surface_id}",
                "defect_id": str(layer["defect_id"]),
                "part_id": str(layer.get("part_id") or "blades"),
                "surface_id": surface_id,
                "object": obj,
                "uv": (0, 0),
                "location": list(location),
                "normal": list(normal),
                "severity": float(layer.get("severity", 50)) / 100,
                "region_id": region_id,
                "layer_index": layer_index,
            }
        )
    if not result:
        raise RuntimeError(
            f"No surface region found for {layer['defect_id']}. Check the selected part and paint."
        )
    return result


def frame_unpainted_regions(
    instances, layers, parts, camera, rng, sample_index, engine
):
    """Place unpainted layers on an actually visible face without changing the camera."""
    vertices, polygons = [], []
    for host in parts.values():
        if host.hide_render:
            continue
        offset = len(vertices)
        vertices.extend(host.matrix_world @ v.co for v in host.data.vertices)
        polygons.extend(
            tuple(offset + i for i in p.vertices) for p in host.data.polygons
        )
    occluders = BVHTree.FromPolygons(vertices, polygons)
    kept = [item for item in instances if item.get("region_id")]
    engine.remove_defect_objects(
        [item for item in instances if not item.get("region_id")]
    )
    for index, layer in enumerate(layers):
        if layer.get("region_id"):
            continue
        candidates = []
        for host in engine.objects_for_part(
            parts, str(layer.get("part_id") or "blades")
        ):
            if host.hide_render:
                continue
            host.data.calc_loop_triangles()
            for triangle in host.data.loop_triangles:
                points = [
                    host.matrix_world @ host.data.vertices[i].co
                    for i in triangle.vertices
                ]
                center = sum(points, Vector()) / 3
                projected = world_to_camera_view(bpy.context.scene, camera, center)
                if projected.z <= 0 or not (
                    0.03 < projected.x < 0.97 and 0.03 < projected.y < 0.97
                ):
                    continue
                direction = center - camera.location
                distance = direction.length
                hit, normal, _, _ = occluders.ray_cast(
                    camera.location, direction.normalized(), distance + 0.02
                )
                if hit is None or (hit - center).length > 0.03:
                    continue
                uv = (
                    sum(
                        (host.data.uv_layers.active.data[i].uv for i in triangle.loops),
                        Vector((0, 0)),
                    )
                    / 3
                )
                screen = [
                    world_to_camera_view(bpy.context.scene, camera, point)
                    for point in points
                ]
                area = abs(
                    (screen[1].x - screen[0].x) * (screen[2].y - screen[0].y)
                    - (screen[2].x - screen[0].x) * (screen[1].y - screen[0].y)
                )
                candidates.append((area, (host, center, tuple(uv), normal)))
        if not candidates:
            raise RuntimeError(
                f"No visible surface for {layer['defect_id']} in the selected camera view."
            )
        candidates.sort(key=lambda item: item[0], reverse=True)
        useful = candidates[: max(1, min(12, len(candidates) // 4))]
        placement = useful[rng.randrange(len(useful))][1]
        kept.extend(
            spawn_regions(
                layer, parts, None, rng, sample_index, index, engine, placement
            )
        )
    return kept


def brush_material(name, brushes):
    """Rasterize the same UV circles/connected strokes as the browser, in order."""
    import numpy as np

    size = 1024
    pixels = np.zeros((size, size), dtype=np.float32)
    for points, radius, paint in brushes:
        stamps = []
        for index, point in enumerate(points):
            if index:
                start = points[index - 1]
                steps = max(
                    1, math.ceil(math.dist(start, point) / max(radius * 0.3, 0.001))
                )
                stamps.extend(
                    (
                        start[0] + (point[0] - start[0]) * t / steps,
                        start[1] + (point[1] - start[1]) * t / steps,
                    )
                    for t in range(steps)
                )
            stamps.append(point)
        for u, v in stamps:
            x, y, r = u * size, v * size, radius * size
            x0, x1 = max(0, int(x - r)), min(size, math.ceil(x + r + 1))
            y0, y1 = max(0, int(y - r)), min(size, math.ceil(y + r + 1))
            yy, xx = np.ogrid[y0:y1, x0:x1]
            inside = (xx + 0.5 - x) ** 2 + (yy + 0.5 - y) ** 2 <= r * r
            pixels[y0:y1, x0:x1][inside] = 1.0 if paint else 0.0
    rgba = np.ones((size, size, 4), dtype=np.float32)
    rgba[:, :, :3] = pixels[:, :, None]
    image = bpy.data.images.new(name, width=size, height=size, alpha=True)
    image.colorspace_settings.name = "Non-Color"
    image.pixels.foreach_set(rgba.ravel())
    image.update()
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.extension = "CLIP"
    multiply = nodes.new("ShaderNodeMixRGB")
    multiply.name = "GuidanceColor"
    multiply.blend_type = "MULTIPLY"
    multiply.inputs[0].default_value = 1.0
    multiply.inputs[2].default_value = (1, 1, 1, 1)
    links.new(tex.outputs["Color"], multiply.inputs[1])
    emission = nodes.new("ShaderNodeEmission")
    links.new(multiply.outputs[0], emission.inputs["Color"])
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    links.new(tex.outputs["Color"], mix.inputs[0])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(emission.outputs[0], mix.inputs[2])
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(mix.outputs[0], output.inputs["Surface"])
    return mat


def set_color(obj, color):
    mat = bpy.data.materials[obj["bladeforge_guidance_material"]]
    mat.node_tree.nodes["GuidanceColor"].inputs[2].default_value = color
    obj.data.materials.clear()
    obj.data.materials.append(mat)
