"""BladeForge v2 headless renderer (Cycles-first, full turbine + multi-defect).

Run with:
blender --background --python render_engine/v2/main.py -- --job-file path/to/job.json
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import random
import shutil
import sys
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any

import bpy
from mathutils import Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_guidance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HUB_HEIGHT_M = 90.0
BLADE_LENGTH_M = 45.0
TOWER_RADIUS_M = 2.2
NACELLE_SIZE = (12.0, 4.0, 4.0)  # length, width, height
HUB_RADIUS_M = 2.4
FOUNDATION_RADIUS_M = 8.0
FOUNDATION_HEIGHT_M = 1.5

PART_GROUPS: dict[str, frozenset[str]] = {
    "all": frozenset({"tower", "nacelle", "hub", "blade_0", "blade_1", "blade_2", "foundation"}),
    "tower": frozenset({"tower"}),
    "nacelle": frozenset({"nacelle"}),
    "hub": frozenset({"hub"}),
    "blades": frozenset({"blade_0", "blade_1", "blade_2"}),
    "rotor": frozenset({"hub", "blade_0", "blade_1", "blade_2"}),
    "foundation": frozenset({"foundation"}),
}

DEFECT_MASK_COLORS: dict[str, tuple[float, float, float, float]] = {
    "leading_edge_erosion": (1.0, 1.0, 1.0, 1.0),
    "surface_crack": (1.0, 0.0, 0.0, 1.0),
    "delamination": (0.0, 1.0, 0.0, 1.0),
    "lightning_strike": (0.0, 0.0, 1.0, 1.0),
    "coating_loss": (1.0, 1.0, 0.0, 1.0),
    "paint_peeling": (1.0, 0.5, 0.0, 1.0),
    "corrosion": (0.65, 0.28, 0.05, 1.0),
    "rust_staining": (0.85, 0.25, 0.05, 1.0),
    "dirt_buildup": (0.35, 0.30, 0.25, 1.0),
    "scratches": (0.55, 0.0, 0.55, 1.0),
    "chips": (0.0, 0.55, 0.55, 1.0),
    "dents": (0.55, 0.55, 0.0, 1.0),
    "holes": (1.0, 0.0, 0.55, 1.0),
    "oil_stains": (0.15, 0.08, 0.02, 1.0),
    "ice_buildup": (0.70, 0.85, 1.0, 1.0),
    "trailing_edge_damage": (0.0, 0.35, 0.10, 1.0),
    "structural_deformation": (0.45, 0.0, 0.0, 1.0),
}

DEFECT_CATEGORY_ORDER = list(DEFECT_MASK_COLORS.keys())

# Approximate UV anchors for default defect placement when no strokes exist.
# Blades: U along span (0=root, 1=tip), V around section (0≈LE, 0.5≈TE).
DEFAULT_UV_TARGETS: dict[str, list[tuple[float, float]]] = {
    "leading_edge_erosion": [(0.35, 0.02), (0.55, 0.02), (0.75, 0.02)],
    "trailing_edge_damage": [(0.45, 0.50), (0.65, 0.50), (0.85, 0.50)],
    "lightning_strike": [(0.92, 0.05), (0.95, 0.08)],
    "surface_crack": [(0.40, 0.20), (0.60, 0.25)],
    "delamination": [(0.50, 0.15), (0.70, 0.18)],
    "coating_loss": [(0.30, 0.30), (0.55, 0.35)],
    "paint_peeling": [(0.35, 0.28), (0.60, 0.32)],
    "dirt_buildup": [(0.25, 0.40), (0.50, 0.42)],
    "scratches": [(0.45, 0.22)],
    "chips": [(0.55, 0.10)],
    "holes": [(0.70, 0.20)],
    "ice_buildup": [(0.80, 0.15), (0.90, 0.20)],
    "oil_stains": [(0.20, 0.35)],
    "structural_deformation": [(0.40, 0.25)],
    "corrosion": [(0.50, 0.50)],
    "rust_staining": [(0.40, 0.45)],
    "dents": [(0.50, 0.40)],
}


# ---------------------------------------------------------------------------
# CLI / progress
# ---------------------------------------------------------------------------


def arguments() -> argparse.Namespace:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-file", required=True)
    return parser.parse_args(args)


def emit(progress: int, stage: str, message: str, **metadata: object) -> None:
    payload = {"progress": progress, "stage": stage, "message": message, "metadata": metadata}
    print(f"BLADEFORGE_PROGRESS {json.dumps(payload, separators=(',', ':'))}", flush=True)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


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
    if "Metallic" in shader.inputs:
        shader.inputs["Metallic"].default_value = metallic
    if "Alpha" in shader.inputs:
        shader.inputs["Alpha"].default_value = color[3]
    if color[3] < 1.0:
        material.blend_method = "BLEND"
        material.use_screen_refraction = False
        material.show_transparent_back = False
    return material


def volume_material(
    name: str,
    density: float,
    color: tuple[float, float, float, float],
):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    volume = nodes.new("ShaderNodeVolumePrincipled")
    volume.inputs["Density"].default_value = density
    volume.inputs["Color"].default_value = color
    if "Anisotropy" in volume.inputs:
        volume.inputs["Anisotropy"].default_value = 0.2
    material.node_tree.links.new(volume.outputs["Volume"], output.inputs["Volume"])
    return material


def set_principled(
    material,
    *,
    color: tuple[float, float, float, float] | None = None,
    roughness: float | None = None,
    metallic: float | None = None,
) -> None:
    shader = material.node_tree.nodes.get("Principled BSDF")
    if color is not None:
        shader.inputs["Base Color"].default_value = color
    if roughness is not None:
        shader.inputs["Roughness"].default_value = roughness
    if metallic is not None and "Metallic" in shader.inputs:
        shader.inputs["Metallic"].default_value = metallic


def materials_for_crack_shadow(base_material):
    material = bpy.data.materials.new(f"{base_material.name}_feather")
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (0.10, 0.095, 0.085, 0.18)
    shader.inputs["Roughness"].default_value = 0.96
    if "Alpha" in shader.inputs:
        shader.inputs["Alpha"].default_value = 0.18
    material.blend_method = "BLEND"
    material.show_transparent_back = False
    return material


def material_base_color(material) -> tuple[float, float, float, float]:
    if material is None:
        return (1.0, 1.0, 1.0, 1.0)
    if material.use_nodes:
        shader = material.node_tree.nodes.get("Principled BSDF")
        if shader is not None and "Base Color" in shader.inputs:
            value = shader.inputs["Base Color"].default_value
            return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    value = getattr(material, "diffuse_color", (1.0, 1.0, 1.0, 1.0))
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


def mix_rgba(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    amount: float,
) -> tuple[float, float, float, float]:
    t = max(0.0, min(1.0, amount))
    return (
        a[0] * (1 - t) + b[0] * t,
        a[1] * (1 - t) + b[1] * t,
        a[2] * (1 - t) + b[2] * t,
        a[3] * (1 - t) + b[3] * t,
    )


def add_material_variation(
    material,
    *,
    base: tuple[float, float, float, float],
    secondary: tuple[float, float, float, float],
    noise_scale: float,
    noise_detail: float = 8.0,
    bump_strength: float = 0.03,
    bump_distance: float = 0.018,
) -> None:
    """Subtle gelcoat/metal ageing so the turbine does not read as flat plastic."""
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    if shader is None:
        return

    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = noise_scale
    noise.inputs["Detail"].default_value = noise_detail
    noise.inputs["Roughness"].default_value = 0.58

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.18
    ramp.color_ramp.elements[0].color = base
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = secondary
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], shader.inputs["Base Color"])

    if not shader.inputs["Normal"].links:
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = bump_strength
        bump.inputs["Distance"].default_value = bump_distance
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], shader.inputs["Normal"])

    if "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = 0.18
    if "Specular IOR Level" in shader.inputs:
        shader.inputs["Specular IOR Level"].default_value = 0.42


def add_micro_surface(material, *, scale: float, strength: float, distance: float) -> None:
    """Add deterministic high-frequency surface relief for close inspection crops."""
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    if shader is None or shader.inputs["Normal"].links:
        return
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 5.0
    noise.inputs["Roughness"].default_value = 0.72
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], shader.inputs["Normal"])


def hex_to_rgba(color_hex: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    value = color_hex.lstrip("#")
    r = int(value[0:2], 16) / 255.0
    g = int(value[2:4], 16) / 255.0
    b = int(value[4:6], 16) / 255.0
    return (r, g, b, alpha)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def ensure_uv_map(mesh: bpy.types.Mesh, name: str = "UVMap") -> None:
    if mesh.uv_layers:
        if mesh.uv_layers.active.name != name:
            mesh.uv_layers.active.name = name
        return
    mesh.uv_layers.new(name=name)


def assign_cylindrical_uvs(obj: bpy.types.Object, axis: str = "Z") -> None:
    """Assign simple cylindrical UVs in object space for region gating."""
    mesh = obj.data
    ensure_uv_map(mesh)
    uv_layer = mesh.uv_layers.active.data
    verts = mesh.vertices
    # Bounds for normalisation.
    xs = [v.co.x for v in verts]
    ys = [v.co.y for v in verts]
    zs = [v.co.z for v in verts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    span_z = max(max_z - min_z, 1e-6)

    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vi = mesh.loops[loop_index].vertex_index
            co = verts[vi].co
            if axis == "Z":
                u = (math.atan2(co.y, co.x) + math.pi) / (2 * math.pi)
                v = (co.z - min_z) / span_z
            elif axis == "Y":
                u = (math.atan2(co.z, co.x) + math.pi) / (2 * math.pi)
                v = (co.y - min_y) / span_y
            else:
                u = (co.x - min_x) / span_x
                v = (co.y - min_y) / span_y
            uv_layer[loop_index].uv = (u, v)


def assign_blade_uvs(obj: bpy.types.Object, sections: int, ring: int) -> None:
    """U = span fraction (root→tip), V = circumferential (0 at leading edge approx)."""
    mesh = obj.data
    ensure_uv_map(mesh)
    uv_layer = mesh.uv_layers.active.data
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vi = mesh.loops[loop_index].vertex_index
            section = vi // ring
            index = vi % ring
            u = section / max(sections - 1, 1)
            # Leading edge is at angle π (x negative in build_blade_mesh).
            # Map so V≈0 near LE: shift by half ring.
            shifted = (index + ring // 2) % ring
            v = shifted / ring
            # Fold so LE-adjacent sits near 0 and TE near 0.5.
            v = min(v, 1.0 - v)
            uv_layer[loop_index].uv = (u, v)


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras, bpy.data.textures):
        for item in list(block):
            block.remove(item)


def _naca_4digit_y(t_ratio: float, x_norm: float) -> float:
    """NACA 4-digit thickness distribution (t_ratio = max thickness / chord).
    x_norm in [0, 1] from leading edge to trailing edge.
    Returns half-thickness / chord (multiply by chord to get real thickness).
    """
    x = max(0.0, min(1.0, x_norm))
    # Standard NACA formula coefficients
    y = (t_ratio / 0.2) * (
        0.2969 * math.sqrt(x)
        - 0.1260 * x
        - 0.3516 * x * x
        + 0.2843 * x * x * x
        - 0.1015 * x * x * x * x  # closed trailing edge variant
    )
    return y


def build_blade_mesh(
    name: str,
    length: float,
    root_chord: float,
    tip_chord: float,
    sections: int = 64,
    ring: int = 48,
) -> bpy.types.Mesh:
    """Build a blade mesh using a realistic NACA-family airfoil cross section.

    The trailing edge pinches to near-zero, the leading edge is a full round nose,
    giving the blade a proper aerodynamic silhouette instead of a toy ellipse.
    """
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []

    # Pre-sample airfoil contour: ring points evenly around profile.
    # We parameterise by angle around a squashed polar, map onto suction + pressure
    # NACA thickness distribution so TE is sharp and LE is rounded.
    def airfoil_xy(angle_rad: float, chord: float, t_frac: float, twist: float) -> tuple[float, float]:
        """One point on the airfoil perimeter.
        angle_rad in [0, 2π]. 0 = trailing edge, π = leading edge.
        t_frac = thickness/chord ratio at this span station.
        """
        # Map angle to normalized x along chord [0,1] (TE=0, LE=1, then back)
        # Upper surface: angle 0→π  maps to x 1→0 (TE to LE, suction side)
        # Lower surface: angle π→2π maps to x 0→1 (LE to TE, pressure side)
        if angle_rad <= math.pi:
            x_norm = 1.0 - angle_rad / math.pi          # 1 at TE, 0 at LE
            sign = 1.0  # suction side (upper)
        else:
            x_norm = (angle_rad - math.pi) / math.pi    # 0 at LE, 1 at TE
            sign = -1.0  # pressure side (lower)

        half_t = _naca_4digit_y(t_frac, x_norm) * chord

        # Chordwise position: leading edge at x=-chord/2, TE at x=+chord/2
        x_chord = (x_norm - 0.5) * chord
        y_offset = sign * half_t

        # Apply twist rotation in XY plane
        xr = x_chord * math.cos(twist) - y_offset * math.sin(twist)
        yr = x_chord * math.sin(twist) + y_offset * math.cos(twist)
        return xr, yr

    # Root cylinder radius — blades have a circular root section for the pitch bearing
    root_radius = root_chord * 0.42  # ~1.6m for 3.8m chord blade

    for section in range(sections):
        t = section / (sections - 1)
        # Non-linear spacing along span: denser near root
        t_span = t * t * (3.0 - 2.0 * t)  # smoothstep
        z = t_span * length

        chord = root_chord * (1.0 - t) + tip_chord * t
        # Thickness ratio from ~21% at root to ~13% at tip
        t_frac = 0.21 - 0.08 * t
        twist = math.radians(14.0 * (1.0 - t) - 1.5)

        # Blend factor: 0-15% of span = cylindrical root, 15-35% = blend, >35% = full airfoil
        root_blend = 1.0 - max(0.0, min(1.0, (t - 0.15) / 0.20))

        for index in range(ring):
            angle = 2.0 * math.pi * index / ring
            xr_af, yr_af = airfoil_xy(angle, chord, t_frac, twist)

            if root_blend > 0.0:
                # Circular cross-section (the root pitch-bearing tube)
                xr_cyl = root_radius * math.cos(angle)
                yr_cyl = root_radius * math.sin(angle)
                # Blend from cylinder at root to airfoil further up
                blend = root_blend * root_blend * (3.0 - 2.0 * root_blend)  # smoothstep
                xr = xr_cyl * blend + xr_af * (1.0 - blend)
                yr = yr_cyl * blend + yr_af * (1.0 - blend)
            else:
                xr, yr = xr_af, yr_af

            vertices.append((xr, yr, z))

    for section in range(sections - 1):
        for index in range(ring):
            nxt = (index + 1) % ring
            a = section * ring + index
            b = section * ring + nxt
            c = (section + 1) * ring + nxt
            d = (section + 1) * ring + index
            faces.append((a, b, c, d))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    return mesh


def build_turbine(gelcoat, metal, concrete) -> dict[str, bpy.types.Object]:
    """Build a procedural wind turbine. Returns part-name → object map."""
    parts: dict[str, bpy.types.Object] = {}

    # Foundation
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48,
        radius=FOUNDATION_RADIUS_M,
        depth=FOUNDATION_HEIGHT_M,
        location=(0, 0, FOUNDATION_HEIGHT_M * 0.5),
    )
    foundation = bpy.context.object
    foundation.name = "foundation"
    foundation["bladeforge_part_id"] = "foundation"
    foundation["bladeforge_surface_id"] = "foundation:0"
    foundation.data.materials.append(concrete)
    assign_cylindrical_uvs(foundation, "Z")
    parts["foundation"] = foundation

    # Tower (tapered via scale at top — approximate with cylinder)
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48,
        radius=TOWER_RADIUS_M,
        depth=HUB_HEIGHT_M,
        location=(0, 0, HUB_HEIGHT_M * 0.5 + FOUNDATION_HEIGHT_M * 0.25),
    )
    tower = bpy.context.object
    tower.name = "tower"
    tower["bladeforge_part_id"] = "tower"
    tower["bladeforge_surface_id"] = "tower:0"
    tower.data.materials.append(metal)
    assign_cylindrical_uvs(tower, "Z")
    # Mild taper via lattice-free nonuniform scale on mesh verts.
    mesh = tower.data
    for vert in mesh.vertices:
        frac = (vert.co.z + HUB_HEIGHT_M * 0.5) / HUB_HEIGHT_M
        taper = 1.0 - 0.35 * max(0.0, min(1.0, frac))
        vert.co.x *= taper
        vert.co.y *= taper
    mesh.update()
    assign_cylindrical_uvs(tower, "Z")
    parts["tower"] = tower

    hub_z = FOUNDATION_HEIGHT_M * 0.25 + HUB_HEIGHT_M

    # Nacelle
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.5, 0.0, hub_z))
    nacelle = bpy.context.object
    nacelle.name = "nacelle"
    nacelle["bladeforge_part_id"] = "nacelle"
    nacelle["bladeforge_surface_id"] = "nacelle:0"
    nacelle.scale = Vector(NACELLE_SIZE)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    nacelle.data.materials.append(metal)
    for polygon in nacelle.data.polygons:
        polygon.use_smooth = True
    bevel = nacelle.modifiers.new("Nacelle rounded shell", "BEVEL")
    bevel.width = 0.65
    bevel.segments = 8
    try:
        nacelle.modifiers.new("Nacelle weighted normals", "WEIGHTED_NORMAL")
    except Exception:
        pass
    assign_cylindrical_uvs(nacelle, "X")
    parts["nacelle"] = nacelle

    # Hub
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=32,
        ring_count=16,
        radius=HUB_RADIUS_M,
        location=(-NACELLE_SIZE[0] * 0.35, 0.0, hub_z),
    )
    hub = bpy.context.object
    hub.name = "hub"
    hub["bladeforge_part_id"] = "hub"
    hub["bladeforge_surface_id"] = "hub:0"
    hub.data.materials.append(gelcoat)
    assign_cylindrical_uvs(hub, "Y")
    parts["hub"] = hub

    hub_center = Vector(hub.location)
    root_chord = 3.8
    tip_chord = 1.1

    for blade_index in range(3):
        mesh = build_blade_mesh(
            f"BladeMesh_{blade_index}",
            length=BLADE_LENGTH_M,
            root_chord=root_chord,
            tip_chord=tip_chord,
        )
        blade = bpy.data.objects.new(f"blade_{blade_index}", mesh)
        bpy.context.collection.objects.link(blade)
        blade.data.materials.append(gelcoat)
        blade["bladeforge_part_id"] = "blades"
        blade["bladeforge_surface_id"] = f"blades:{blade_index}"
        assign_blade_uvs(blade, sections=28, ring=24)
        # Orient blade: local +Z along span, rotate around Y (rotor axis ≈ -X) wait —
        # Hub sits on -X face of nacelle; rotor spins around X axis.
        # Place blade root at hub, span initially +Z, then rotate around X by 120°*i.
        angle = math.radians(blade_index * 120.0)
        blade.location = hub_center + Vector((-HUB_RADIUS_M * 0.15, 0.0, 0.0))
        # Rotate so blade fans in YZ plane (spin axis = world X).
        blade.rotation_euler = (angle, math.radians(90.0), 0.0)
        bevel = blade.modifiers.new("BladeBevel", "BEVEL")
        bevel.width = 0.04
        bevel.segments = 2
        parts[f"blade_{blade_index}"] = blade

    return parts


NAME_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("blades", ("blade", "rotorblade", "wing")),
    ("hub", ("hub", "spinner", "nose")),
    ("nacelle", ("nacelle", "housing", "body", "generator", "gearbox")),
    ("tower", ("tower", "mast", "column", "pole")),
    ("foundation", ("foundation", "base", "footing", "plinth", "pad")),
)


def object_world_bounds(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = Vector(tuple(min(point[i] for point in corners) for i in range(3)))
    maximum = Vector(tuple(max(point[i] for point in corners) for i in range(3)))
    return minimum, maximum


def combined_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    if not objects:
        return Vector((0, 0, 0)), Vector((1, 1, 1))
    bounds = [object_world_bounds(obj) for obj in objects]
    minimum = Vector(tuple(min(pair[0][i] for pair in bounds) for i in range(3)))
    maximum = Vector(tuple(max(pair[1][i] for pair in bounds) for i in range(3)))
    return minimum, maximum


def normalize_imported_model(objects: list[bpy.types.Object]) -> None:
    """Match the browser's Z-up, metre-scale, ground-centred normalization."""
    root = bpy.data.objects.new("BladeForgeImportedRoot", None)
    bpy.context.collection.objects.link(root)
    object_set = set(objects)
    for obj in objects:
        if obj.parent not in object_set:
            obj.parent = root

    minimum, maximum = combined_bounds(objects)
    size = maximum - minimum
    if size.y > size.z * 1.5:
        root.rotation_euler.x = math.pi / 2
        bpy.context.view_layer.update()

    minimum, maximum = combined_bounds(objects)
    height = max(1e-6, maximum.z - minimum.z)
    unit_scale = 1.0
    if height > 20_000:
        unit_scale = 0.001
    elif height > 1_000:
        unit_scale = 0.01
    elif height < 5:
        unit_scale = 100.0
    root.scale = (unit_scale, unit_scale, unit_scale)
    bpy.context.view_layer.update()

    minimum, maximum = combined_bounds(objects)
    centre = (minimum + maximum) * 0.5
    root.location.x -= centre.x
    root.location.y -= centre.y
    root.location.z -= minimum.z
    bpy.context.view_layer.update()


def classify_imported_parts(objects: list[bpy.types.Object]) -> dict[str, bpy.types.Object]:
    minimum, maximum = combined_bounds(objects)
    overall = maximum - minimum
    total_height = max(1e-6, overall.z)
    total_width = max(1e-6, overall.x, overall.y)
    groups: dict[str, list[bpy.types.Object]] = {}

    for obj in objects:
        low_name = obj.name.lower().replace(" ", "")
        part_id: str | None = None
        for candidate, hints in NAME_HINTS:
            if any(hint in low_name for hint in hints):
                part_id = candidate
                break
        obj_min, obj_max = object_world_bounds(obj)
        size = obj_max - obj_min
        centre = (obj_min + obj_max) * 0.5
        if part_id is None:
            height_fraction = size.z / total_height
            width_fraction = max(size.x, size.y) / total_width
            elevation = (centre.z - minimum.z) / total_height
            slenderness = size.z / max(1e-6, size.x, size.y)
            if slenderness > 4 and height_fraction > 0.3:
                part_id = "tower"
            elif width_fraction > 0.35 and elevation > 0.5:
                part_id = "blades"
            elif elevation > 0.6 and width_fraction < 0.35:
                part_id = "nacelle"
            elif elevation < 0.2:
                part_id = "foundation"
            else:
                part_id = "nacelle"
        groups.setdefault(part_id, []).append(obj)

    # Generic CAD exports often call both top assemblies "Cube"/"Cylinder". When
    # there are at least two compact top meshes, the smaller-volume one is the rotor
    # hub and the larger one is the nacelle. Keep this identical to the web viewport.
    if not groups.get("hub") and len(groups.get("nacelle", [])) >= 2 and groups.get("blades"):
        nacelle_members = groups["nacelle"]
        hub = min(
            nacelle_members,
            key=lambda obj: math.prod(max(1e-6, value) for value in (object_world_bounds(obj)[1] - object_world_bounds(obj)[0])),
        )
        nacelle_members.remove(hub)
        groups["hub"] = [hub]

    parts: dict[str, bpy.types.Object] = {}
    for part_id, members in groups.items():
        for index, obj in enumerate(members):
            surface_id = f"{part_id}:{index}"
            obj["bladeforge_part_id"] = part_id
            obj["bladeforge_surface_id"] = surface_id
            parts[surface_id] = obj
    return parts


def import_turbine_model(
    model_path: Path,
    gelcoat,
    metal,
    concrete,
) -> dict[str, bpy.types.Object]:
    if not model_path.is_file():
        raise RuntimeError(f"Selected turbine model is missing: {model_path}")
    before = set(bpy.data.objects)
    suffix = model_path.suffix.lower()
    if suffix == ".fbx":
        if hasattr(bpy.ops.wm, "fbx_import"):
            bpy.ops.wm.fbx_import(filepath=str(model_path))
        else:
            bpy.ops.import_scene.fbx(filepath=str(model_path))
    elif suffix == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(model_path), forward_axis="NEGATIVE_Z", up_axis="Y")
        else:
            bpy.ops.import_scene.obj(filepath=str(model_path))
    else:
        raise RuntimeError(f"Unsupported turbine model format: {suffix}")

    meshes = [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("The selected model contains no renderable mesh objects.")
    normalize_imported_model(meshes)
    parts = classify_imported_parts(meshes)
    for obj in meshes:
        part_id = str(obj.get("bladeforge_part_id") or "nacelle")
        fallback = concrete if part_id == "foundation" else metal if part_id in {"tower", "nacelle"} else gelcoat
        if not obj.data.materials:
            obj.data.materials.append(fallback)
        if not obj.data.uv_layers:
            axis = "Z" if part_id in {"tower", "foundation"} else "Y"
            assign_cylindrical_uvs(obj, axis)
    return parts


def part_id_for_object(obj: bpy.types.Object) -> str:
    return str(obj.get("bladeforge_part_id") or obj.name)


def semantic_material_for_part(part_id: str, materials: dict[str, Any]):
    pid = part_id.lower()
    if pid == "foundation":
        return materials["concrete"]
    if pid == "tower":
        return materials["tower_shell"]
    if pid == "nacelle":
        return materials["nacelle_shell"]
    if pid == "hub":
        return materials["hub_shell"]
    if pid == "blades" or pid.startswith("blade_"):
        return materials["gelcoat"]
    return materials["gelcoat"]


def material_looks_like_editor_marker(material) -> bool:
    """Detect loud viewport/debug materials that should not appear in RGB renders."""
    r, g, b, _ = material_base_color(material)
    hi = max(r, g, b)
    lo = min(r, g, b)
    saturation = 0.0 if hi <= 1e-6 else (hi - lo) / hi
    hot_pink = r > 0.65 and b > 0.45 and g < 0.45
    bright_primary = saturation > 0.70 and hi > 0.55
    return hot_pink or bright_primary


def replace_object_material(obj: bpy.types.Object, material) -> None:
    if obj.type != "MESH":
        return
    obj.data.materials.clear()
    obj.data.materials.append(material)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    if not any(mod.type == "WEIGHTED_NORMAL" for mod in obj.modifiers):
        try:
            obj.modifiers.new("BladeForge weighted normals", "WEIGHTED_NORMAL")
        except Exception:
            pass


def apply_realistic_turbine_materials(
    parts: dict[str, bpy.types.Object],
    materials: dict[str, Any],
    *,
    force: bool,
) -> None:
    """Give default/procedural turbines production materials and remove toy colours."""
    for obj in parts.values():
        if obj.type != "MESH":
            continue
        part_id = part_id_for_object(obj)
        target = semantic_material_for_part(part_id, materials)
        existing = [mat for mat in obj.data.materials if mat is not None]
        should_replace = force or not existing or any(material_looks_like_editor_marker(mat) for mat in existing)
        if should_replace:
            replace_object_material(obj, target)
        elif not obj.data.uv_layers:
            axis = "Z" if part_id in {"tower", "foundation"} else "Y"
            assign_cylindrical_uvs(obj, axis)


def objects_visible_for_selection(
    parts: dict[str, bpy.types.Object], turbine_part_id: str
) -> list[bpy.types.Object]:
    if turbine_part_id == "all":
        return list(parts.values())
    accepted = {"blades", "hub"} if turbine_part_id == "rotor" else {turbine_part_id}
    return [obj for obj in parts.values() if part_id_for_object(obj) in accepted]


def apply_part_visibility(parts: dict[str, bpy.types.Object], turbine_part_id: str) -> None:
    visible = set(objects_visible_for_selection(parts, turbine_part_id))
    if not visible:
        raise RuntimeError(f"The selected model has no separable {turbine_part_id} geometry.")
    for obj in parts.values():
        hide = obj not in visible
        obj.hide_render = hide
        obj.hide_viewport = hide


def part_target_point(parts: dict[str, bpy.types.Object], turbine_part_id: str) -> Vector:
    objs = objects_visible_for_selection(parts, turbine_part_id)
    if not objs:
        objs = list(parts.values())
    minimum, maximum = combined_bounds(objs)
    return (minimum + maximum) * 0.5


# ---------------------------------------------------------------------------
# Region document / UV gating
# ---------------------------------------------------------------------------


def _stroke_fields(
    stroke: dict[str, Any],
) -> tuple[str | None, float, list[tuple[float, float]], str, str | None]:
    region_id = stroke.get("regionId") or stroke.get("region_id")
    radius = float(stroke.get("radiusUv") or stroke.get("radius_uv") or 0.04)
    mode = str(stroke.get("mode") or "paint")
    surface_id = stroke.get("surfaceId") or stroke.get("surface_id")
    raw_points = stroke.get("points") or []
    points: list[tuple[float, float]] = []
    for pt in raw_points:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            points.append((float(pt[0]), float(pt[1])))
    return region_id, radius, points, mode, str(surface_id) if surface_id else None


def region_accepts_uv(
    region_document: dict[str, Any] | None,
    region_id: str | None,
    uv: tuple[float, float],
    surface_id: str | None = None,
) -> bool:
    """True only inside the region painted on this exact surface."""
    if not region_document or not region_id:
        return True
    strokes = region_document.get("strokes") or []
    relevant = []
    has_region_strokes = False
    for stroke in strokes:
        sid, radius, points, mode, target_surface_id = _stroke_fields(stroke)
        if sid == region_id and points:
            has_region_strokes = True
            if target_surface_id and target_surface_id != surface_id:
                continue
            relevant.append((radius, points, mode))
    if not relevant:
        # Legacy documents without strokes use default placement. If this region was
        # painted elsewhere, however, this surface is a hard no.
        return not has_region_strokes

    u, v = uv
    # Paint wins if any paint stamp covers; erase cancels coverage.
    painted = False
    for radius, points, mode in relevant:
        for pu, pv in points:
            du = u - pu
            dv = v - pv
            if du * du + dv * dv <= radius * radius:
                if mode == "erase":
                    painted = False
                else:
                    painted = True
    return painted


def sample_uv_on_object(
    obj: bpy.types.Object, rng: random.Random
) -> tuple[float, float, Vector, Vector]:
    """Pick a random surface UV and corresponding world position (approx from face)."""
    mesh = obj.data
    if not mesh.polygons:
        return 0.5, 0.5, obj.matrix_world.translation.copy(), Vector((0, 0, 1))
    ensure_uv_map(mesh)
    uv_layer = mesh.uv_layers.active.data
    poly = mesh.polygons[rng.randrange(len(mesh.polygons))]
    uvs = [uv_layer[li].uv for li in poly.loop_indices]
    # Barycentric-ish average with jitter.
    weights = [rng.random() for _ in uvs]
    total = sum(weights) or 1.0
    weights = [w / total for w in weights]
    u = sum(uv.x * w for uv, w in zip(uvs, weights))
    v = sum(uv.y * w for uv, w in zip(uvs, weights))
    # Position from face center in world space.
    local = Vector(poly.center)
    world = obj.matrix_world @ local
    normal = (obj.matrix_world.to_3x3() @ poly.normal).normalized()
    world = world + normal * 0.02
    return u, v, world, normal


def uv_to_object_world(obj: bpy.types.Object, u: float, v: float) -> tuple[Vector, Vector]:
    """Map a UV to the nearest imported/rendered surface vertex and its normal."""
    mesh = obj.data
    # Prefer nearest loop UV.
    ensure_uv_map(mesh)
    uv_layer = mesh.uv_layers.active.data
    best_li = 0
    best_d = 1e9
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            uv = uv_layer[li].uv
            d = (uv.x - u) ** 2 + (uv.y - v) ** 2
            if d < best_d:
                best_d = d
                best_li = li
    vi = mesh.loops[best_li].vertex_index
    local = mesh.vertices[vi].co.copy()
    # Offset slightly outward along vertex normal if available.
    local_normal = mesh.vertices[vi].normal.copy().normalized()
    world_normal = (obj.matrix_world.to_3x3() @ local_normal).normalized()
    world = obj.matrix_world @ local
    return world + world_normal * 0.01, world_normal


def objects_for_part(parts: dict[str, bpy.types.Object], part_id: str) -> list[bpy.types.Object]:
    return objects_visible_for_selection(parts, part_id)


def surface_id_for_object(obj: bpy.types.Object) -> str:
    """Map renderer objects to the browser's stable semantic surface ids."""
    configured = obj.get("bladeforge_surface_id")
    if configured:
        return str(configured)
    if obj.name.startswith("blade_"):
        return f"blades:{obj.name.removeprefix('blade_')}"
    part = {
        "hub": "hub",
        "nacelle": "nacelle",
        "tower": "tower",
        "foundation": "foundation",
    }.get(obj.name, obj.name)
    return f"{part}:0"


def painted_uv_samples(
    region_document: dict[str, Any] | None,
    region_id: str | None,
    surface_id: str,
) -> list[tuple[float, float, float]]:
    """Return (u, v, radius) samples explicitly painted on one surface."""
    if not region_document or not region_id:
        return []
    samples: list[tuple[float, float, float]] = []
    for stroke in region_document.get("strokes") or []:
        sid, radius, points, mode, target_surface_id = _stroke_fields(stroke)
        if sid != region_id or mode != "paint":
            continue
        if target_surface_id and target_surface_id != surface_id:
            continue
        samples.extend((u, v, radius) for u, v in points)
    return samples


def painted_surface_samples(
    region_document: dict[str, Any] | None,
    region_id: str | None,
    surface_id: str,
) -> list[
    tuple[
        float,
        float,
        float,
        Vector | None,
        Vector | None,
        Vector | None,
        Vector | None,
    ]
]:
    """Return UV plus the exact local hit and normal captured by the browser."""
    if not region_document or not region_id:
        return []
    samples: list[
        tuple[
            float,
            float,
            float,
            Vector | None,
            Vector | None,
            Vector | None,
            Vector | None,
        ]
    ] = []
    for stroke in region_document.get("strokes") or []:
        sid, radius, points, mode, target_surface_id = _stroke_fields(stroke)
        if sid != region_id or mode != "paint":
            continue
        if target_surface_id and target_surface_id != surface_id:
            continue
        raw_local_points = stroke.get("local_points") or stroke.get("localPoints") or []
        raw_local_normals = stroke.get("local_normals") or stroke.get("localNormals") or []
        raw_world_points = stroke.get("world_points") or stroke.get("worldPoints") or []
        raw_world_normals = stroke.get("world_normals") or stroke.get("worldNormals") or []
        for index, (u, v) in enumerate(points):
            local_point = None
            local_normal = None
            world_point = None
            world_normal = None
            if index < len(raw_local_points) and len(raw_local_points[index]) >= 3:
                local_point = Vector(tuple(float(value) for value in raw_local_points[index][:3]))
            if index < len(raw_local_normals) and len(raw_local_normals[index]) >= 3:
                local_normal = Vector(tuple(float(value) for value in raw_local_normals[index][:3]))
                if local_normal.length > 1e-8:
                    local_normal.normalize()
                else:
                    local_normal = None
            if index < len(raw_world_points) and len(raw_world_points[index]) >= 3:
                world_point = Vector(tuple(float(value) for value in raw_world_points[index][:3]))
            if index < len(raw_world_normals) and len(raw_world_normals[index]) >= 3:
                world_normal = Vector(tuple(float(value) for value in raw_world_normals[index][:3]))
                if world_normal.length > 1e-8:
                    world_normal.normalize()
                else:
                    world_normal = None
            samples.append(
                (u, v, radius, local_point, local_normal, world_point, world_normal)
            )
    return samples


# ---------------------------------------------------------------------------
# Defect creation
# ---------------------------------------------------------------------------


def create_sphere_patch(
    name: str,
    location: Vector,
    radius: float,
    material,
    scale: Vector | None = None,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    if scale is not None:
        obj.scale = scale
    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)
    return obj


def create_box_mark(
    name: str,
    location: Vector,
    dimensions: Vector,
    rotation: tuple[float, float, float],
    material,
    normal: Vector | None = None,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = dimensions
    if normal is None:
        obj.rotation_euler = rotation
    else:
        obj.rotation_mode = "QUATERNION"
        align = Vector((0, 0, 1)).rotation_difference(normal.normalized())
        spin = Quaternion(normal.normalized(), rotation[1])
        obj.rotation_quaternion = spin @ align
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)
    return obj


def create_damage_curve(
    name: str,
    points: list[Vector],
    bevel_depth: float,
    material,
) -> bpy.types.Object:
    """Create a surface-following irregular line instead of a rectangular decal."""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = bevel_depth
    curve.bevel_resolution = 1
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for target, point in zip(spline.points, points):
        target.co = (*point, 1.0)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    obj.visible_shadow = False
    return obj


def create_surface_decal(
    name: str,
    location: Vector,
    normal: Vector,
    radius: float,
    material,
    rng: random.Random,
    *,
    stretch: tuple[float, float] = (1.0, 1.0),
    rotation: float = 0.0,
    vertices: int = 18,
    lift: float = 0.006,
) -> bpy.types.Object:
    """Create a paper-thin irregular surface patch. It reads like texture/decal,
    not a raised 3D lump, while still being renderable for masks."""
    n = normal.normalized()
    tangent = n.cross(Vector((0, 0, 1)))
    if tangent.length < 1e-6:
        tangent = n.cross(Vector((0, 1, 0)))
    tangent.normalize()
    bitangent = n.cross(tangent).normalized()
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    front_points: list[Vector] = []
    back_points: list[Vector] = []
    for index in range(vertices):
        angle = (math.tau * index) / vertices
        wobble = rng.uniform(0.72, 1.12)
        x = math.cos(angle) * radius * stretch[0] * wobble
        y = math.sin(angle) * radius * stretch[1] * wobble
        xr = x * cos_r - y * sin_r
        yr = x * sin_r + y * cos_r
        surface_point = tangent * xr + bitangent * yr
        front_points.append(location + n * lift + surface_point)
        back_points.append(location - n * lift + surface_point)
    mesh = bpy.data.meshes.new(name)
    # Two opposite winding orders make the decal visible from both sides in
    # mask/RGB passes without adding thickness or a raised solid shape.
    all_points = front_points + back_points
    front = list(range(vertices))
    back = list(range(vertices, vertices * 2))
    mesh.from_pydata(
        [tuple(point) for point in all_points],
        [],
        [front, list(reversed(front)), back, list(reversed(back))],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    obj.visible_shadow = False
    return obj


def create_crater_rim(
    name: str,
    location: Vector,
    radius: float,
    thickness: float,
    material,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_torus_add(
        major_radius=radius,
        minor_radius=thickness,
        major_segments=20,
        minor_segments=6,
        location=location,
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def apply_displace(obj: bpy.types.Object, name: str, strength: float, noise_scale: float) -> None:
    displacement = obj.modifiers.new(name, "DISPLACE")
    texture = bpy.data.textures.new(f"{name}_tex", type="CLOUDS")
    texture.noise_scale = max(0.01, noise_scale)
    texture.noise_depth = 2
    displacement.texture = texture
    displacement.strength = strength


def pick_placement(
    parts: dict[str, bpy.types.Object],
    part_id: str,
    defect_id: str,
    region_id: str | None,
    region_document: dict[str, Any] | None,
    rng: random.Random,
    attempt_limit: int = 40,
) -> tuple[bpy.types.Object, Vector, tuple[float, float], Vector] | None:
    candidates = objects_for_part(parts, part_id)
    if not candidates:
        return None

    # Exact-surface strokes narrow the candidate objects before any UV sampling. A
    # mark on blade 0 can therefore never be reproduced on blade 1 or blade 2.
    targeted_surface_ids: set[str] = set()
    if region_document and region_id:
        for stroke in region_document.get("strokes") or []:
            sid, _radius, points, _mode, target_surface_id = _stroke_fields(stroke)
            if sid == region_id and points and target_surface_id:
                targeted_surface_ids.add(target_surface_id)
    if targeted_surface_ids:
        candidates = [
            obj for obj in candidates if surface_id_for_object(obj) in targeted_surface_ids
        ]
        if not candidates:
            return None

    # Painted points are much more reliable than hoping a random default UV happens to
    # land inside a small brush mark.
    painted_candidates: list[
        tuple[
            bpy.types.Object,
            float,
            float,
            float,
            Vector | None,
            Vector | None,
            Vector | None,
            Vector | None,
        ]
    ] = []
    for obj in candidates:
        object_surface_id = surface_id_for_object(obj)
        for u, v, radius, local_point, local_normal, world_point, world_normal in painted_surface_samples(
            region_document, region_id, object_surface_id
        ):
            painted_candidates.append(
                (obj, u, v, radius, local_point, local_normal, world_point, world_normal)
            )
    for _ in range(attempt_limit):
        if not painted_candidates:
            break
        (
            obj,
            base_u,
            base_v,
            radius,
            local_point,
            local_normal,
            world_point,
            world_normal,
        ) = painted_candidates[rng.randrange(len(painted_candidates))]
        u = min(1.0, max(0.0, base_u + rng.uniform(-radius * 0.35, radius * 0.35)))
        v = min(1.0, max(0.0, base_v + rng.uniform(-radius * 0.35, radius * 0.35)))
        object_surface_id = surface_id_for_object(obj)
        if not region_accepts_uv(region_document, region_id, (u, v), object_surface_id):
            continue
        if world_point is not None and world_normal is not None:
            minimum, maximum = object_world_bounds(obj)
            tolerance = max(0.05, (maximum - minimum).length * 0.08)
            if all(
                minimum[axis] - tolerance <= world_point[axis] <= maximum[axis] + tolerance
                for axis in range(3)
            ):
                return obj, world_point + world_normal * 0.01, (u, v), world_normal
        if local_point is not None:
            world = obj.matrix_world @ local_point
            normal = (
                (obj.matrix_world.to_3x3() @ local_normal).normalized()
                if local_normal is not None
                else uv_to_object_world(obj, u, v)[1]
            )
            return obj, world + normal * 0.01, (u, v), normal
        world, normal = uv_to_object_world(obj, u, v)
        return obj, world, (u, v), normal

    # Prefer default UV targets on blades when available.
    defaults = DEFAULT_UV_TARGETS.get(defect_id, [(0.5, 0.2)])
    for _ in range(attempt_limit):
        obj = candidates[rng.randrange(len(candidates))]
        if obj.name.startswith("blade_") and defaults:
            u, v = defaults[rng.randrange(len(defaults))]
            u = min(0.98, max(0.02, u + rng.uniform(-0.08, 0.08)))
            v = min(0.48, max(0.0, v + rng.uniform(-0.04, 0.04)))
            if not region_accepts_uv(
                region_document, region_id, (u, v), surface_id_for_object(obj)
            ):
                continue
            world, normal = uv_to_object_world(obj, u, v)
            return obj, world, (u, v), normal
        u, v, world, normal = sample_uv_on_object(obj, rng)
        if region_accepts_uv(
            region_document, region_id, (u, v), surface_id_for_object(obj)
        ):
            return obj, world, (u, v), normal
    # A painted region is a hard permission boundary. Never escape it just to force a
    # visible defect into the image.
    if region_document and region_id:
        region_strokes = [
            stroke
            for stroke in (region_document.get("strokes") or [])
            if (_stroke_fields(stroke)[0] == region_id and _stroke_fields(stroke)[2])
        ]
        if region_strokes:
            return None
    # No paint exists for this layer, so normal default placement remains valid.
    obj = candidates[0]
    u, v, world, normal = sample_uv_on_object(obj, rng)
    return obj, world, (u, v), normal


def spawn_defects_for_layer(
    layer: dict[str, Any],
    parts: dict[str, bpy.types.Object],
    materials: dict[str, Any],
    region_document: dict[str, Any] | None,
    rng: random.Random,
    sample_index: int,
) -> list[dict[str, Any]]:
    """Create geometry/material defect instances. Returns descriptors with objects."""
    defect_id = str(layer["defect_id"])
    part_id = str(layer.get("part_id") or "blades")
    severity = float(layer.get("severity", 50)) / 100.0
    coverage = float(layer.get("coverage", 20)) / 100.0
    size_scale = float(layer.get("size_scale", 1.0))
    opacity = float(layer.get("opacity", 100)) / 100.0
    rotation_deg = float(layer.get("rotation_deg", 0.0))
    spread = float(layer.get("spread", 40)) / 100.0
    randomness = float(layer.get("randomness", 50)) / 100.0
    color_hex = str(layer.get("color_hex") or "#ef4444")
    region_id = layer.get("region_id")

    count = max(1, int(round(1 + coverage * 10 * (0.45 + severity))))
    count = max(1, int(round(count * (0.6 + randomness))))
    instances: list[dict[str, Any]] = []
    mat = materials["defect_rgb"].get(defect_id) or materials["erosion"]

    # Tint material from color_hex where meaningful.
    tint_strength = {
        "corrosion": 0.12,
        "rust_staining": 0.12,
        "dirt_buildup": 0.08,
        "oil_stains": 0.06,
        "coating_loss": 0.04,
        "paint_peeling": 0.04,
    }.get(defect_id, 0.0)
    if tint_strength > 0:
        mat = mat.copy()
        mat.name = f"{mat.name}_{sample_index:04d}_{rng.randrange(10_000):04d}"
        tint = hex_to_rgba(color_hex)
        base = list(mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value)
        mixed = (
            base[0] * (1 - opacity * tint_strength) + tint[0] * opacity * tint_strength,
            base[1] * (1 - opacity * tint_strength) + tint[1] * opacity * tint_strength,
            base[2] * (1 - opacity * tint_strength) + tint[2] * opacity * tint_strength,
            1.0,
        )
        set_principled(mat, color=mixed)

    for i in range(count):
        placed = pick_placement(parts, part_id, defect_id, region_id, region_document, rng)
        if placed is None:
            break
        host, location, uv, normal = placed
        # Jitter in the local tangent plane so defects stay attached to the host surface.
        tangent = normal.cross(Vector((0, 0, 1)))
        if tangent.length < 1e-6:
            tangent = normal.cross(Vector((0, 1, 0)))
        tangent.normalize()
        bitangent = normal.cross(tangent).normalized()
        jitter = spread * size_scale * (0.18 + randomness * 0.35)
        location = location + tangent * rng.uniform(-jitter, jitter) + bitangent * rng.uniform(-jitter, jitter)
        name = f"DEF_{defect_id}_{sample_index:04d}_{i:03d}"
        objs = create_defect_geometry(
            defect_id=defect_id,
            name=name,
            location=location,
            host=host,
            normal=normal,
            severity=severity,
            size_scale=size_scale,
            rotation_deg=rotation_deg + rng.uniform(-15, 15) * randomness,
            material=mat,
            rng=rng,
        )
        instance_id = f"{defect_id}:{sample_index}:{i}"
        for obj in objs:
            instances.append(
                {
                    "instance_id": instance_id,
                    "defect_id": defect_id,
                    "part_id": part_id,
                    "surface_id": surface_id_for_object(host),
                    "object": obj,
                    "uv": uv,
                    "location": list(location),
                    "normal": list(normal),
                    "severity": severity,
                    "size_scale": size_scale,
                }
            )
    return instances


def _ensure_erosion_material_mix(mat: bpy.types.Material) -> None:
    """
    One-time injection: add a Mix Shader to *mat* driven by a 'DefectMask' colour
    attribute.  The clean gelcoat blends smoothly into an exposed-composite
    (rough, desaturated) material wherever DefectMask is non-zero.
    Compatible with Blender 3.x through 5.x.  Calling this twice is a no-op.
    """
    if any(n.name == "_DefectMixShader" for n in mat.node_tree.nodes):
        return

    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None or not out.inputs["Surface"].is_linked:
        return

    old_surface = out.inputs["Surface"].links[0].from_socket

    # ShaderNodeAttribute works in ALL Blender versions and reads any named
    # geometry attribute (including colour attributes created via color_attributes).
    vc_node = nodes.new("ShaderNodeAttribute")
    vc_node.name = "_DefectVC"
    vc_node.attribute_name = "DefectMask"
    # Fac = luminance(R,G,B). We paint R=G=B=mask so Fac == mask exactly.

    # Fine-grained noise so the erosion edge looks organic
    noise = nodes.new("ShaderNodeTexNoise")
    noise.name = "_DefectNoise"
    noise.inputs["Scale"].default_value = 20.0
    noise.inputs["Detail"].default_value = 6.0
    noise.inputs["Roughness"].default_value = 0.65
    noise.inputs["Distortion"].default_value = 0.35

    mult = nodes.new("ShaderNodeMath")
    mult.name = "_DefectMult"
    mult.operation = "MULTIPLY"
    links.new(vc_node.outputs["Fac"], mult.inputs[0])
    links.new(noise.outputs["Fac"], mult.inputs[1])

    # Smooth step → crisp but not jagged transition
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.name = "_DefectRamp"
    ramp.color_ramp.interpolation = "EASE"
    ramp.color_ramp.elements[0].position = 0.18
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
    ramp.color_ramp.elements[1].position = 0.68
    ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    links.new(mult.outputs["Value"], ramp.inputs["Fac"])

    # Eroded composite BSDF (exposed fibreglass/resin)
    eroded = nodes.new("ShaderNodeBsdfPrincipled")
    eroded.name = "_DefectErodedBSDF"
    eroded.inputs["Base Color"].default_value = (0.64, 0.60, 0.52, 1.0)
    eroded.inputs["Roughness"].default_value = 0.83
    eroded.inputs["Metallic"].default_value = 0.0
    for sp_name in ("Specular IOR Level", "Specular"):
        if sp_name in eroded.inputs:
            eroded.inputs[sp_name].default_value = 0.08
            break

    # Subtle bump so eroded zone has micro-texture
    bump = nodes.new("ShaderNodeBump")
    bump.name = "_DefectBump"
    bump.inputs["Strength"].default_value = 0.28
    bump.inputs["Distance"].default_value = 0.007
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], eroded.inputs["Normal"])

    mix = nodes.new("ShaderNodeMixShader")
    mix.name = "_DefectMixShader"
    links.new(ramp.outputs["Color"], mix.inputs["Fac"])
    links.new(old_surface, mix.inputs[1])
    links.new(eroded.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])


def _paint_defect_mask(host: bpy.types.Object, center: Vector, radius: float, strength: float = 1.0) -> None:
    """
    Paint the 'DefectMask' colour attribute on *host* with a smooth radial
    falloff centred at *center* (world space).  Multiple calls accumulate.
    Compatible with Blender 3.x (vertex_colors) and 4.x/5.x (color_attributes).
    """
    mesh = host.data
    vc_name = "DefectMask"

    if hasattr(mesh, "color_attributes"):
        # Blender 4.0+ API: FLOAT_COLOR POINT attribute (one entry per vertex)
        is_new = vc_name not in mesh.color_attributes
        vc = mesh.color_attributes.get(vc_name)
        if vc is None:
            vc = mesh.color_attributes.new(name=vc_name, type="FLOAT_COLOR", domain="POINT")
        if is_new:
            for item in vc.data:
                item.color = (0.0, 0.0, 0.0, 1.0)

        mw = host.matrix_world
        inv_r2 = 1.0 / max(radius * radius, 1e-6)
        for i, vertex in enumerate(mesh.vertices):
            wpos = mw @ vertex.co
            dist2 = (wpos - center).length_squared
            falloff = max(0.0, 1.0 - dist2 * inv_r2) ** 1.5
            new_val = min(1.0, vc.data[i].color[0] + falloff * strength)
            # Paint R=G=B=mask so ShaderNodeAttribute "Fac" output == mask exactly
            vc.data[i].color = (new_val, new_val, new_val, 1.0)
    else:
        # Legacy Blender 3.x: per-loop vertex_colors
        is_new = vc_name not in mesh.vertex_colors
        vc = mesh.vertex_colors.get(vc_name) or mesh.vertex_colors.new(name=vc_name)
        if is_new:
            for item in vc.data:
                item.color = (0.0, 0.0, 0.0, 1.0)

        mw = host.matrix_world
        inv_r2 = 1.0 / max(radius * radius, 1e-6)
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                wpos = mw @ mesh.vertices[vi].co
                dist2 = (wpos - center).length_squared
                falloff = max(0.0, 1.0 - dist2 * inv_r2) ** 1.5
                new_val = min(1.0, vc.data[li].color[0] + falloff * strength)
                vc.data[li].color = (new_val, new_val, new_val, 1.0)


def create_defect_geometry(
    *,
    defect_id: str,
    name: str,
    location: Vector,
    host: bpy.types.Object,
    normal: Vector,
    severity: float,
    size_scale: float,
    rotation_deg: float,
    material,
    rng: random.Random,
) -> list[bpy.types.Object]:
    s = max(0.05, size_scale) * (0.42 + severity * 0.85)
    rot = math.radians(rotation_deg)
    created: list[bpy.types.Object] = []
    alignment = Vector((0, 0, 1)).rotation_difference(normal.normalized())

    def surface_offset(value: Vector) -> Vector:
        return alignment @ value

    if defect_id == "leading_edge_erosion":
        # ------------------------------------------------------------------ #
        # Material-only approach: paint an erosion zone on the blade surface. #
        # No 3D geometry is placed — the eroded composite blends in via the   #
        # vertex-colour mask injected into the host object's material.        #
        # ------------------------------------------------------------------ #
        local_s = min(s, 1.35)
        base_radius = (0.10 + severity * 0.24) * local_s

        # Ensure the blade has a per-object material copy so other blades
        # in the scene are not affected.
        if host.data.materials:
            orig_mat = host.data.materials[0]
            if not orig_mat.name.startswith("_def_"):
                unique_mat = orig_mat.copy()
                unique_mat.name = f"_def_{orig_mat.name}"
                host.data.materials[0] = unique_mat
            else:
                unique_mat = orig_mat
            _ensure_erosion_material_mix(unique_mat)

            # Primary erosion zone
            _paint_defect_mask(host, location, base_radius, strength=0.75 + severity * 0.25)

            # Additional pits at higher severity for realistic progression
            pits = int(2 + severity * 6)
            for p in range(pits):
                offset = surface_offset(Vector((
                    rng.uniform(-0.10, 0.10) * local_s,
                    rng.uniform(-0.04, 0.04) * local_s,
                    rng.uniform(-0.16, 0.16) * local_s,
                )))
                pit_r = base_radius * rng.uniform(0.20, 0.55)
                _paint_defect_mask(
                    host, location + offset, pit_r,
                    strength=0.55 + severity * 0.45,
                )

        # Flush scuffed leading-edge decal: visible as surface wear, not as a
        # raised object. It also gives masks/COCO reliable pixels.
        decal = create_surface_decal(
            f"{name}_scuff",
            location,
            normal,
            base_radius,
            material,
            rng,
            stretch=(2.8, 0.34),
            rotation=rot + rng.uniform(-0.18, 0.18),
            vertices=26,
            lift=0.08,
        )
        decal.hide_render = False
        created.append(decal)

    elif defect_id == "surface_crack":
        local_s = min(s, 1.4)
        length = (0.20 + severity * 0.48) * local_s
        crack = create_surface_decal(
            name,
            location,
            normal,
            length,
            material,
            rng,
            stretch=(0.010 + severity * 0.010, 1.0),
            rotation=rot + rng.uniform(-0.22, 0.22),
            vertices=16,
            lift=0.055,
        )
        created.append(crack)
        if severity > 0.35:
            for branch_index in range(2):
                branch_offset = surface_offset(
                    Vector((rng.uniform(-0.03, 0.03) * length, rng.uniform(-0.12, 0.12) * length, 0.0))
                )
                branch = create_surface_decal(
                    f"{name}_branch{branch_index}",
                    location + branch_offset,
                    normal,
                    length * rng.uniform(0.28, 0.45),
                    material,
                    rng,
                    stretch=(0.010, 1.0),
                    rotation=rot + math.radians(rng.choice([-35, 35])) + rng.uniform(-0.16, 0.16),
                    vertices=14,
                    lift=0.058,
                )
                created.append(branch)
        feather = create_surface_decal(
            f"{name}_feather",
            location,
            normal,
            length * 0.58,
            materials_for_crack_shadow(material),
            rng,
            stretch=(0.045, 1.0),
            rotation=rot,
            vertices=18,
            lift=0.052,
        )
        created.append(feather)

    elif defect_id == "delamination":
        radius = (0.15 + severity * 0.45) * s
        obj = create_sphere_patch(name, location, radius, material)
        # Partially embed: squash and push into surface.
        obj.scale = Vector((1.4, 1.4, 0.35 + severity * 0.25))
        created.append(obj)

    elif defect_id == "lightning_strike":
        tip = location
        scorch_r = (0.12 + severity * 0.35) * s
        disk = create_sphere_patch(f"{name}_scorch", tip, scorch_r, material, scale=Vector((1.6, 1.6, 0.25)))
        created.append(disk)
        branches = max(2, int(2 + severity * 5))
        for b in range(branches):
            ang = rot + b * (math.pi * 2 / branches) + rng.uniform(-0.4, 0.4)
            length = (0.3 + severity * 1.2) * s * rng.uniform(0.5, 1.0)
            branch_points = [tip]
            for step in range(1, 6):
                fraction = step / 5
                local = Vector(
                    (
                        math.cos(ang) * length * fraction + rng.uniform(-0.04, 0.04) * length,
                        math.sin(ang) * length * fraction + rng.uniform(-0.04, 0.04) * length,
                        0.012,
                    )
                )
                branch_points.append(tip + surface_offset(local))
            branch = create_damage_curve(
                f"{name}_br{b}", branch_points, 0.012 + severity * 0.012, material
            )
            created.append(branch)

    elif defect_id in ("coating_loss", "paint_peeling"):
        patches = max(1, int(2 + severity * 5))
        for p in range(patches):
            offset = Vector((rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2), rng.uniform(-0.15, 0.15))) * s
            radius = (0.08 + severity * 0.25) * s * rng.uniform(0.5, 1.3)
            obj = create_sphere_patch(
                f"{name}_p{p}", location + surface_offset(offset), radius, material
            )
            obj.scale = Vector((1.5, 1.2, 0.12))
            created.append(obj)

    elif defect_id in ("corrosion", "rust_staining"):
        stains = max(2, int(2 + severity * 6))
        for p in range(stains):
            offset = Vector((rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25), rng.uniform(-0.4, 0.4))) * s
            radius = (0.06 + severity * 0.2) * s
            obj = create_sphere_patch(
                f"{name}_p{p}", location + surface_offset(offset), radius, material
            )
            obj.scale = Vector((1.3, 1.0, 0.15 + severity * 0.1))
            created.append(obj)

    elif defect_id == "dirt_buildup":
        local_s = min(s, 1.35)
        radius = (0.07 + severity * 0.16) * local_s
        streaks = max(2, int(2 + severity * 5))
        for p in range(streaks):
            offset = surface_offset(
                Vector((rng.uniform(-0.10, 0.10) * local_s, rng.uniform(-0.18, 0.18) * local_s, 0))
            )
            obj = create_surface_decal(
                f"{name}_stain{p}",
                location + offset,
                normal,
                radius * rng.uniform(0.45, 0.95),
                material,
                rng,
                stretch=(rng.uniform(0.35, 0.75), rng.uniform(1.6, 3.2)),
                rotation=rot + rng.uniform(-0.35, 0.35),
                vertices=22,
                lift=0.06,
            )
            created.append(obj)

    elif defect_id == "scratches":
        for p in range(max(1, int(1 + severity * 4))):
            length = (0.25 + severity * 1.0) * s
            angle = rot + rng.uniform(-0.5, 0.5)
            centre = location + surface_offset(Vector((rng.uniform(-0.1, 0.1), 0, 0)))
            direction = Vector((math.cos(angle), math.sin(angle), 0))
            obj = create_damage_curve(
                f"{name}_s{p}",
                [
                    centre + surface_offset(direction * (-length * 0.5) + Vector((0, 0, 0.055))),
                    centre + surface_offset(Vector((rng.uniform(-0.02, 0.02), 0, 0.055))),
                    centre + surface_offset(direction * (length * 0.5) + Vector((0, 0, 0.055))),
                ],
                0.006 + severity * 0.005,
                material,
            )
            created.append(obj)

    elif defect_id == "chips":
        radius = (0.05 + severity * 0.12) * s
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=location)
        obj = bpy.context.object
        obj.name = name
        obj.data.materials.append(material)
        obj.scale = Vector((1.0, 0.7, 0.4))
        apply_displace(obj, f"{name}_irregular", strength=radius * 0.35, noise_scale=radius)
        created.append(obj)

    elif defect_id == "dents":
        radius = (0.12 + severity * 0.35) * s
        inset = create_sphere_patch(
            name,
            location - normal * radius * 0.16,
            radius,
            material,
            scale=Vector((1.2, 1.2, 0.20)),
        )
        rim = create_crater_rim(
            f"{name}_rim", location + normal * 0.008, radius * 0.88, radius * 0.09, material
        )
        created.extend((inset, rim))

    elif defect_id == "holes":
        radius = (0.04 + severity * 0.15) * s
        cavity = create_sphere_patch(
            name,
            location - normal * radius * 0.35,
            radius,
            material,
            scale=Vector((1.0, 1.0, 0.32)),
        )
        rim = create_crater_rim(
            f"{name}_rim", location + normal * 0.006, radius * 0.92, radius * 0.13, material
        )
        apply_displace(rim, f"{name}_broken_edge", strength=radius * 0.18, noise_scale=radius)
        created.extend((cavity, rim))

    elif defect_id == "oil_stains":
        radius = (0.15 + severity * 0.4) * s
        obj = create_sphere_patch(name, location, radius, material)
        obj.scale = Vector((1.6, 1.1, 0.08))
        created.append(obj)

    elif defect_id == "ice_buildup":
        chunks = max(1, int(2 + severity * 4))
        for p in range(chunks):
            offset = Vector((rng.uniform(-0.15, 0.15), rng.uniform(-0.1, 0.1), rng.uniform(-0.2, 0.2))) * s
            radius = (0.06 + severity * 0.18) * s
            obj = create_sphere_patch(
                f"{name}_i{p}", location + surface_offset(offset), radius, material
            )
            obj.scale = Vector((1.1, 0.9, 1.3))
            created.append(obj)

    elif defect_id == "trailing_edge_damage":
        pits = max(2, int(2 + severity * 6))
        for p in range(pits):
            offset = Vector((rng.uniform(-0.05, 0.05), rng.uniform(-0.04, 0.04), rng.uniform(-0.3, 0.3))) * s
            radius = (0.03 + severity * 0.1) * s
            obj = create_sphere_patch(
                f"{name}_t{p}", location + surface_offset(offset), radius, material
            )
            obj.scale = Vector((0.5, 1.2, 1.5))
            created.append(obj)

    elif defect_id == "structural_deformation":
        # Visible bulge / warp via scaled elongated sphere + mild displace on host.
        radius = (0.2 + severity * 0.5) * s
        obj = create_sphere_patch(name, location, radius, material)
        obj.scale = Vector((0.6, 1.4, 2.0))
        apply_displace(obj, f"{name}_d", strength=0.05 + severity * 0.08, noise_scale=0.2)
        if host and host.type == "MESH":
            apply_displace(host, f"{name}_host", strength=0.02 * severity, noise_scale=0.5)
        created.append(obj)

    else:
        # Unknown id → small dark patch so something still appears.
        obj = create_sphere_patch(name, location, 0.1 * s, material)
        created.append(obj)

    # Every generated mark is expressed in a local XY tangent plane with +Z pointing
    # away from the inspected surface. This prevents floating or world-axis-aligned
    # defects when a blade is rotated or a customer model uses a different pose.
    spin = Quaternion(normal.normalized(), rot)
    for obj in created:
        if obj.type == "MESH" and not obj.name.startswith(("DEF_surface_crack", "DEF_lightning_strike", "DEF_scratches")):
            obj.rotation_mode = "QUATERNION"
            obj.rotation_quaternion = spin @ alignment
    return created


def remove_defect_objects(instances: list[dict[str, Any]]) -> None:
    for item in instances:
        obj = item.get("object")
        if obj is not None:
            if obj.get("bladeforge_gemini_guidance"):
                mat = bpy.data.materials.get(obj.get("bladeforge_guidance_material", ""))
                if mat:
                    textures = [n.image for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
                    bpy.data.materials.remove(mat, do_unlink=True)
                    for texture in textures:
                        if texture.users == 0:
                            bpy.data.images.remove(texture)
            data = getattr(obj, "data", None)
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except ReferenceError:
                pass
            if data is not None and getattr(data, "users", 0) == 0:
                if isinstance(data, bpy.types.Curve):
                    bpy.data.curves.remove(data)
                elif isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)


# ---------------------------------------------------------------------------
# Environment / lighting / camera
# ---------------------------------------------------------------------------


def setup_world_nodes() -> tuple[Any, Any, Any]:
    """Create Background (+ optional Sky Texture). Returns (world, bg_node, sky_or_none)."""
    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    background.inputs["Color"].default_value = (0.4, 0.55, 0.8, 1.0)
    background.inputs["Strength"].default_value = 1.0
    links.new(background.outputs["Background"], output.inputs["Surface"])
    sky = None
    if hasattr(bpy.types, "ShaderNodeTexSky"):
        try:
            sky = nodes.new("ShaderNodeTexSky")
            if hasattr(sky, "sky_type"):
                try:
                    sky.sky_type = "NISHITA"
                except (TypeError, ValueError, AttributeError):
                    pass
            links.new(sky.outputs["Color"], background.inputs["Color"])
        except Exception:
            sky = None
    return world, background, sky


def connect_hdri(world, background, hdri_path: Path | None) -> bool:
    if hdri_path is None:
        return False
    if not hdri_path.is_file():
        raise RuntimeError(f"Selected HDRI is missing: {hdri_path}")
    try:
        image = bpy.data.images.load(str(hdri_path), check_existing=True)
    except RuntimeError as exc:
        raise RuntimeError(f"Blender could not read the selected HDRI: {hdri_path.name}") from exc
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    for link in list(background.inputs["Color"].links):
        links.remove(link)
    texcoord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    environment = nodes.new("ShaderNodeTexEnvironment")
    environment.image = image
    environment.interpolation = "Linear"
    # The bundled and uploaded lat-long maps use image-up, while Blender's world
    # coordinates are Z-up. Flip the sphere vertically and retain the useful yaw.
    mapping.inputs["Rotation"].default_value[0] = math.pi
    mapping.inputs["Rotation"].default_value[2] = math.radians(90.0)
    links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
    links.new(environment.outputs["Color"], background.inputs["Color"])
    return True


def selected_hdri_path(config: dict[str, Any], environment_id: str | None) -> Path | None:
    uploaded = config.get("hdri_asset_path")
    if uploaded:
        return Path(str(uploaded)).resolve()
    root = Path(__file__).resolve().parents[2]
    eid = (environment_id or "").upper()
    if eid == "DESERT_CLEAR_V1":
        return root / "public" / "assets" / "hdri" / "desert.hdr"
    if eid == "MOONLIGHT_HDRI_V1":
        return root / "public" / "assets" / "hdri" / "moon-light.hdr"
    return None


def configure_environment(
    environment_id: str | None,
    weather_intensity: float,
    world,
    background,
    sky,
    sun: bpy.types.Object,
    materials: dict[str, Any],
) -> dict[str, Any]:
    """Set world colour / sun / wetness from environment_id. Returns env metadata."""
    eid = (environment_id or "CLEAR_DAY_V1").upper()
    wi = max(0.0, min(1.0, weather_intensity))
    wetness = 0.0
    sun_energy = 5.0
    bg_color = (0.45, 0.60, 0.90, 1.0)
    bg_strength = 1.0
    exposure = 1.0
    precipitation = "none"
    precipitation_rate = 0.0
    fog_density = 0.0
    lightning_probability = 0.0
    wind_speed = 2.0

    if eid in ("DESERT_CLEAR_V1", "CLEAR_DAY_V1"):
        bg_color = (0.46, 0.58, 0.72, 1.0)
        bg_strength = 0.70 + wi * 0.12
        sun_energy = 3.8 + wi * 2.2
        exposure = 1.0
    elif eid in ("MOONLIGHT_HDRI_V1", "NIGHT_MOONLIT_V1"):
        bg_color = (0.02, 0.03, 0.06, 1.0)
        bg_strength = 0.15 + wi * 0.1
        sun_energy = 0.35 + wi * 0.4
        exposure = 2.2 + wi * 0.8
        sun.data.color = (0.75, 0.82, 1.0)
    elif eid in ("LIGHT_RAIN_WET_V1", "HEAVY_RAIN_STORM_V1", "POST_RAIN_WET_V1"):
        bg_color = (0.35, 0.38, 0.40, 1.0)
        bg_strength = 0.6 + wi * 0.3
        sun_energy = 1.5 + (1.0 - wi) * 2.0
        wetness = 0.45 + wi * 0.45
        fog_density = 0.001 + wi * 0.002
        wind_speed = 5.0 + wi * 7.0
        if eid == "LIGHT_RAIN_WET_V1":
            precipitation = "rain"
            precipitation_rate = 2.0 + wi * 7.0
        elif eid == "HEAVY_RAIN_STORM_V1":
            precipitation = "rain"
            precipitation_rate = 18.0 + wi * 32.0
            lightning_probability = 0.12 + wi * 0.38
        if "STORM" in eid:
            wetness = 0.7 + wi * 0.25
            bg_color = (0.22, 0.24, 0.26, 1.0)
            sun_energy = 0.8 + wi * 0.5
    elif eid in ("LIGHT_SNOW_V1", "SNOW_STORM_V1"):
        bg_color = (0.58, 0.64, 0.70, 1.0)
        bg_strength = 0.55 + wi * 0.18
        sun_energy = 3.2 + wi * 1.4
        wetness = 0.2
        precipitation = "snow"
        precipitation_rate = 0.8 + wi * 3.5
        fog_density = 0.00008 + wi * 0.00016
        wind_speed = 3.0 + wi * 5.0
        if "STORM" in eid:
            bg_color = (0.48, 0.52, 0.56, 1.0)
            bg_strength = 0.45 + wi * 0.12
            sun_energy = 1.8
            precipitation_rate = 4.0 + wi * 8.0
            fog_density = 0.00022 + wi * 0.00038
            wind_speed = 9.0 + wi * 12.0
    elif eid in ("OVERCAST", "OVERCAST_DAY_V1"):
        bg_color = (0.55, 0.58, 0.62, 1.0)
        bg_strength = 0.9
        sun_energy = 2.5
    elif eid in ("CLOUDY", "CLOUDY_DAY_V1"):
        bg_color = (0.48, 0.52, 0.58, 1.0)
        bg_strength = 0.85
        sun_energy = 3.5
    elif eid in ("GOLDEN_HOUR", "GOLDEN_HOUR_V1"):
        bg_color = (0.85, 0.55, 0.30, 1.0)
        bg_strength = 1.1
        sun_energy = 6.0
        sun.data.color = (1.0, 0.72, 0.45)
    elif eid in ("OFFSHORE_HAZE", "OFFSHORE_HAZE_V1"):
        bg_color = (0.55, 0.62, 0.68, 1.0)
        bg_strength = 0.95
        sun_energy = 4.0
        wetness = 0.15
        fog_density = 0.00035 + wi * 0.00065
        wind_speed = 4.0 + wi * 5.0
    else:
        # Fall back via legacy lighting_preset mapping handled by caller defaults.
        bg_color = (0.45, 0.55, 0.70, 1.0)
        sun_energy = 5.0

    background.inputs["Color"].default_value = bg_color
    background.inputs["Strength"].default_value = bg_strength
    if sky is not None and hasattr(sky, "sun_intensity"):
        try:
            sky.sun_intensity = sun_energy * 0.15
        except Exception:
            pass

    sun.data.energy = sun_energy * (0.7 + wi * 0.6)
    scene = bpy.context.scene
    if hasattr(scene.view_settings, "exposure"):
        scene.view_settings.exposure = math.log2(max(exposure, 0.01))

    # Wetter materials → lower roughness on gelcoat/metal (wet surface = mirror-like).
    if wetness > 0:
        for key in ("gelcoat", "metal"):
            mat = materials.get(key)
            if mat is not None:
                shader = mat.node_tree.nodes.get("Principled BSDF")
                base_r = 0.16 if key == "gelcoat" else 0.28
                shader.inputs["Roughness"].default_value = max(0.02, base_r * (1.0 - wetness * 0.85))

    nodes = world.node_tree.nodes
    links = world.node_tree.links
    output = next((node for node in nodes if node.type == "OUTPUT_WORLD"), None)
    fog = nodes.get("BladeForgeFog")
    if fog is None:
        fog = nodes.new("ShaderNodeVolumeScatter")
        fog.name = "BladeForgeFog"
    # An infinite world volume integrates all the way to the far clip and turns even
    # light fog opaque. A finite camera-local volume is created per sample instead.
    fog.inputs["Density"].default_value = 0.0
    fog.inputs["Anisotropy"].default_value = 0.35
    if output is not None:
        for link in list(output.inputs["Volume"].links):
            links.remove(link)

    return {
        "environment_id": eid,
        "weather_intensity": wi,
        "wetness": wetness,
        "sun_energy": sun.data.energy,
        "background_strength": bg_strength,
        "exposure": exposure,
        "precipitation": precipitation,
        "precipitation_rate": precipitation_rate,
        "fog_density": fog_density,
        "lightning_probability": lightning_probability,
        "wind_speed": wind_speed,
    }


def curve_segments(
    name: str,
    segments: list[tuple[Vector, Vector]],
    bevel_depth: float,
    material,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = bevel_depth
    curve.bevel_resolution = 0
    for start, end in segments:
        spline = curve.splines.new("POLY")
        spline.points.add(1)
        spline.points[0].co = (*start, 1.0)
        spline.points[1].co = (*end, 1.0)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def create_weather_effects(
    env: dict[str, Any],
    target: Vector,
    camera: bpy.types.Object,
    materials: dict[str, Any],
    rng: random.Random,
    enabled: bool,
) -> list[bpy.types.Object]:
    if not enabled:
        return []
    precipitation = str(env.get("precipitation") or "none")
    rate = float(env.get("precipitation_rate") or 0.0)
    wind = float(env.get("wind_speed") or 0.0)
    effects: list[bpy.types.Object] = []
    span = min(80.0, max(12.0, (camera.location - target).length * 0.55))
    centre = target.lerp(camera.location, 0.45)

    fog_density = float(env.get("fog_density") or 0.0)
    if fog_density > 0:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=target.lerp(camera.location, 0.62))
        fog = bpy.context.object
        fog.name = "WeatherFog"
        distance = max(10.0, (camera.location - target).length)
        fog.scale = Vector((span * 0.95, span * 0.95, distance * 0.36))
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        density = min(0.00075, fog_density)
        fog.data.materials.append(
            volume_material(
                f"WeatherFogMaterial_{rng.randrange(1_000_000)}",
                density,
                (0.64, 0.68, 0.72, 1.0),
            )
        )
        effects.append(fog)

    if precipitation == "rain" and rate > 0:
        count = min(220, max(28, int(35 + rate * 3.5)))
        length = 0.35 + min(2.2, rate * 0.035)
        drift = min(1.2, wind * 0.035)
        segments: list[tuple[Vector, Vector]] = []
        for _ in range(count):
            start = centre + Vector(
                (
                    rng.uniform(-span, span),
                    rng.uniform(-span, span),
                    rng.uniform(-span * 0.7, span * 0.7),
                )
            )
            end = start + Vector((drift, 0.0, -length))
            segments.append((start, end))
        effects.append(curve_segments("WeatherRain", segments, 0.008, materials["rain"]))

    if precipitation == "snow" and rate > 0:
        count = min(95, max(18, int(22 + rate * 4)))
        vertices: list[tuple[float, float, float]] = []
        faces: list[tuple[int, int, int, int]] = []
        for _ in range(count):
            centre_flake = centre + Vector(
                (
                    rng.uniform(-span, span),
                    rng.uniform(-span, span),
                    rng.uniform(-span * 0.7, span * 0.7),
                )
            )
            radius = rng.uniform(0.018, 0.052) * max(0.50, span / 32.0)
            base = len(vertices)
            vertices.extend(
                [
                    tuple(centre_flake + Vector((radius, 0, -radius * 0.5))),
                    tuple(centre_flake + Vector((-radius, 0, -radius * 0.5))),
                    tuple(centre_flake + Vector((0, radius, radius * 0.5))),
                    tuple(centre_flake + Vector((0, -radius, radius * 0.5))),
                ]
            )
            faces.append((base, base + 1, base + 2, base + 3))
        mesh = bpy.data.meshes.new("WeatherSnowMesh")
        mesh.from_pydata(vertices, [], faces)
        snow = bpy.data.objects.new("WeatherSnow", mesh)
        bpy.context.collection.objects.link(snow)
        snow.data.materials.append(materials["snow"])
        effects.append(snow)

    if rng.random() < float(env.get("lightning_probability") or 0.0):
        direction = (target - camera.location).normalized()
        origin = target - direction * span * 0.35 + Vector((0, 0, span * 0.65))
        points = [origin]
        for index in range(1, 9):
            fraction = index / 8
            points.append(
                origin
                + Vector(
                    (
                        rng.uniform(-1.8, 1.8),
                        rng.uniform(-1.0, 1.0),
                        -span * 1.25 * fraction,
                    )
                )
            )
        effects.append(
            curve_segments(
                "WeatherLightning",
                list(zip(points[:-1], points[1:])),
                0.035,
                materials["lightning"],
            )
        )
        bpy.ops.object.light_add(type="POINT", location=origin)
        flash = bpy.context.object
        flash.name = "WeatherLightningFlash"
        flash.data.energy = 35_000
        flash.data.color = (0.72, 0.82, 1.0)
        effects.append(flash)
    return effects


def remove_weather_effects(effects: list[bpy.types.Object]) -> None:
    for obj in effects:
        data = getattr(obj, "data", None)
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except ReferenceError:
            continue
        if data is not None and getattr(data, "users", 0) == 0:
            if isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
            elif isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)
    for material in list(bpy.data.materials):
        if material.name.startswith("WeatherFogMaterial_") and material.users == 0:
            bpy.data.materials.remove(material)


def orbit_camera_location(
    target: Vector,
    azimuth_deg: float,
    elevation_deg: float,
    distance_m: float,
) -> Vector:
    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    x = target.x + distance_m * math.cos(el) * math.cos(az)
    y = target.y + distance_m * math.cos(el) * math.sin(az)
    z = target.z + distance_m * math.sin(el)
    return Vector((x, y, z))


def point_at(obj: bpy.types.Object, target: Vector, roll_deg: float = 0.0) -> None:
    direction = target - obj.location
    if direction.length < 1e-8:
        return
    quat = direction.to_track_quat("-Z", "Y")
    euler = quat.to_euler()
    euler.rotate_axis("Z", math.radians(roll_deg))
    obj.rotation_euler = euler


def inspection_camera_from_instances(
    instances: list[dict[str, Any]],
    rng: random.Random,
    fov_deg: float,
) -> dict[str, Any] | None:
    """Place the camera like a drone inspection shot: close to the damaged surface."""
    candidates = [
        item
        for item in instances
        if str(item.get("part_id")) in {"blades", "hub", "rotor"} or "blade" in str(item.get("surface_id", ""))
    ] or instances
    if not candidates:
        return None
    chosen = max(
        candidates,
        key=lambda item: (
            float(item.get("severity") or 0.0),
            1.0 if str(item.get("defect_id")) == "leading_edge_erosion" else 0.0,
        ),
    )
    target = Vector(chosen.get("location", (0.0, 0.0, 0.0)))
    normal = Vector(chosen.get("normal", (0.0, 0.0, 1.0)))
    if normal.length < 1e-6:
        normal = Vector((0.0, -1.0, 0.2))
    normal.normalize()

    tangent = normal.cross(Vector((0, 0, 1)))
    if tangent.length < 1e-6:
        tangent = normal.cross(Vector((0, 1, 0)))
    tangent.normalize()
    bitangent = normal.cross(tangent).normalized()

    # Pull back enough that defects read as surface damage on a blade, not giant
    # abstract geometry filling the lens.
    distance = rng.uniform(5.5, 9.0)
    target = target + tangent * rng.uniform(-0.15, 0.15) + bitangent * rng.uniform(-0.12, 0.12)
    location = target + normal * distance + tangent * rng.uniform(-0.35, 0.35) + bitangent * rng.uniform(0.10, 0.45)
    return {
        "target": target,
        "location": location,
        "roll_deg": rng.uniform(-1.2, 1.2),
        "fov_deg": min(float(fov_deg), 40.0),
    }


def fov_to_lens(fov_deg: float, sensor_width: float = 36.0) -> float:
    return sensor_width / (2.0 * math.tan(math.radians(max(fov_deg, 1.0)) / 2.0))


def wrap_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def all_angle_views(
    image_count: int, base_distance: float, target_height: float
) -> list[dict[str, float]]:
    """Mirror the browser plan and never repeat a pose."""
    candidates: list[dict[str, float]] = []

    def add(azimuth: float, elevation: float, distance_factor: float) -> None:
        candidates.append(
            {
                "target_x_m": 0.0,
                "target_y_m": 0.0,
                "target_z_m": target_height,
                "azimuth_deg": wrap_degrees(azimuth),
                "elevation_deg": elevation,
                "distance_m": base_distance * distance_factor,
                "roll_deg": 0.0,
            }
        )

    cardinals = (-90.0, 0.0, 90.0, 180.0)
    for azimuth in cardinals:
        add(azimuth, 4.0, 1.0)
    for azimuth in (-90.0, 90.0):
        add(azimuth, 6.0, 0.45)
        add(azimuth, 10.0, 2.1)
    for elevation, factor in ((32.0, 1.0), (-18.0, 1.1)):
        for azimuth in cardinals:
            add(azimuth, elevation, factor)
    for azimuth in cardinals:
        add(azimuth + 45.0, 12.0, 1.0)
    for factor in (0.45, 1.0, 2.1):
        for elevation in (4.0, 32.0, -18.0):
            for azimuth in cardinals:
                add(azimuth + 22.5, elevation, factor)

    def duplicate(left: dict[str, float], right: dict[str, float]) -> bool:
        azimuth_gap = abs(wrap_degrees(left["azimuth_deg"] - right["azimuth_deg"]))
        elevation_gap = abs(left["elevation_deg"] - right["elevation_deg"])
        distance_ratio = max(left["distance_m"], right["distance_m"]) / max(
            1e-6, min(left["distance_m"], right["distance_m"])
        )
        height_gap = abs(left["target_z_m"] - right["target_z_m"])
        return (
            azimuth_gap < 18
            and elevation_gap < 10
            and distance_ratio < 1.25
            and height_gap < 3
        )

    chosen: list[dict[str, float]] = []
    for candidate in candidates:
        if len(chosen) >= image_count:
            break
        if not any(duplicate(existing, candidate) for existing in chosen):
            chosen.append(candidate)
    cursor = 0
    golden_angle = 137.50776405
    while len(chosen) < image_count:
        factor = (0.45, 1.0, 2.1)[(cursor // 3) % 3]
        elevation = (4.0, 32.0, -18.0)[cursor % 3]
        candidate = {
            "target_x_m": 0.0,
            "target_y_m": 0.0,
            "target_z_m": target_height,
            "azimuth_deg": wrap_degrees(cursor * golden_angle),
            "elevation_deg": elevation,
            "distance_m": base_distance * factor,
            "roll_deg": 0.0,
        }
        cursor += 1
        if any(duplicate(existing, candidate) for existing in chosen):
            if cursor <= image_count * 12:
                continue
        chosen.append(candidate)
    return chosen[:image_count]


def framing_for_part(
    parts: dict[str, bpy.types.Object], turbine_part_id: str, fov_deg: float
) -> dict[str, float]:
    selected = objects_visible_for_selection(parts, turbine_part_id) or list(parts.values())
    minimum, maximum = combined_bounds(selected)
    radius = max(0.5, (maximum - minimum).length * 0.5)
    distance = radius / max(0.08, math.tan(math.radians(fov_deg) * 0.5)) * 1.22
    defaults = {
        "all": (35.0, 12.0),
        "tower": (40.0, 5.0),
        "nacelle": (25.0, 8.0),
        "hub": (20.0, 5.0),
        "blades": (30.0, 10.0),
        "rotor": (25.0, 8.0),
        "foundation": (45.0, 15.0),
    }
    azimuth, elevation = defaults.get(turbine_part_id, defaults["all"])
    return {"azimuth_deg": azimuth, "elevation_deg": elevation, "distance_m": distance}


# ---------------------------------------------------------------------------
# Render engine / passes
# ---------------------------------------------------------------------------


def select_render_engine() -> str:
    scene = bpy.context.scene
    available = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    requested = os.getenv("BLADEFORGE_RENDER_ENGINE", "CYCLES").upper()
    if requested in {"BLENDER_EEVEE_NEXT", "EEVEE", "BLENDER_EEVEE"}:
        eevee = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in available else "BLENDER_EEVEE"
        if eevee in available:
            scene.render.engine = eevee
            return eevee
    if "CYCLES" in available:
        scene.render.engine = "CYCLES"
        cycles = scene.cycles
        cycles.samples = max(1, int(os.getenv("BLADEFORGE_CYCLES_SAMPLES", "256")))
        cycles.use_denoising = True
        if hasattr(cycles, "denoising_prefilter"):
            try:
                cycles.denoising_prefilter = "ACCURATE"
            except Exception:
                pass
        if hasattr(cycles, "device"):
            # Prefer GPU when available; fall back silently.
            for device in ("GPU", "CPU"):
                try:
                    cycles.device = device
                    break
                except TypeError:
                    continue
        return "CYCLES"
    if "BLENDER_EEVEE_NEXT" in available:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
        return "BLENDER_EEVEE_NEXT"
    scene.render.engine = "BLENDER_EEVEE"
    return "BLENDER_EEVEE"


def configure_render(width: int, height: int, compression_quality: int = 92) -> str:
    scene = bpy.context.scene
    engine = select_render_engine()
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.image_settings.color_depth = "8"
    # PNG is lossless; this setting controls compression effort/file size, not pixels.
    scene.render.image_settings.compression = max(0, min(100, int(compression_quality)))
    try:
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium Contrast"
    except (TypeError, ValueError):
        try:
            scene.view_settings.view_transform = "Filmic"
        except Exception:
            pass
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    if hasattr(scene, "eevee"):
        try:
            scene.eevee.use_gtao = True
            scene.eevee.gtao_distance = 4
            scene.eevee.gtao_factor = 1.2
        except Exception:
            pass
    return engine


def render_still(path: Path) -> None:
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def capture_materials(objects: list[bpy.types.Object]) -> dict[str, list[Any]]:
    return {obj.name: list(obj.data.materials) for obj in objects if obj.type == "MESH"}


def assign_only_material(obj: bpy.types.Object, material) -> None:
    if obj.type != "MESH" or obj.data is None:
        return
    obj.data.materials.clear()
    obj.data.materials.append(material)


def restore_materials(objects: list[bpy.types.Object], snapshot: dict[str, list[Any]]) -> None:
    for obj in objects:
        if obj.type != "MESH":
            continue
        obj.data.materials.clear()
        for material in snapshot.get(obj.name, []):
            if material is not None:
                obj.data.materials.append(material)


def set_mask_mode(
    parts: dict[str, bpy.types.Object],
    instances: list[dict[str, Any]],
    materials: dict[str, Any],
    enabled: bool,
    original_materials: dict[str, list[Any]],
) -> None:
    black = materials["mask_black"]
    if enabled:
        for obj in parts.values():
            assign_only_material(obj, black)
        for item in instances:
            defect_id = item["defect_id"]
            mask_mat = materials["defect_mask"][defect_id]
            obj = item["object"]
            if obj.get("bladeforge_gemini_guidance"):
                gemini_guidance.set_color(obj, DEFECT_MASK_COLORS[defect_id])
            else:
                assign_only_material(obj, mask_mat)
    else:
        restore_materials(list(parts.values()) + [item["object"] for item in instances], original_materials)


def instance_palette(
    instance_ids: list[str],
) -> tuple[
    dict[str, tuple[float, float, float, float]],
    dict[tuple[float, float, float], str],
]:
    """Use unique hues so anti-aliasing cannot turn one instance into another.

    Edge pixels are a darkened version of the emission colour. Hue/chromatic direction
    survives that blending; the old per-channel base-8 code did not.
    """
    colors: dict[str, tuple[float, float, float, float]] = {}
    lookup: dict[tuple[float, float, float], str] = {}
    for index, instance_id in enumerate(instance_ids):
        if index >= 256:
            raise RuntimeError("A sample cannot contain more than 256 separately annotated defect instances.")
        hue = (index * 0.618033988749895) % 1.0
        rgb = colorsys.hsv_to_rgb(hue, 0.92, 0.88)
        color = (rgb[0], rgb[1], rgb[2], 1.0)
        colors[instance_id] = color
        lookup[rgb] = instance_id
    return colors, lookup


def set_instance_mask_mode(
    parts: dict[str, bpy.types.Object],
    instances: list[dict[str, Any]],
    materials: dict[str, Any],
    palette: dict[str, tuple[float, float, float, float]],
) -> list[Any]:
    black = materials["mask_black"]
    for obj in parts.values():
        assign_only_material(obj, black)
    created_materials: list[Any] = []
    by_id: dict[str, Any] = {}
    for item in instances:
        instance_id = str(item["instance_id"])
        if item["object"].get("bladeforge_gemini_guidance"):
            gemini_guidance.set_color(item["object"], palette[instance_id])
            continue
        material = by_id.get(instance_id)
        if material is None:
            material = emission_material(f"INSTANCE_{len(by_id):03d}", palette[instance_id])
            by_id[instance_id] = material
            created_materials.append(material)
        assign_only_material(item["object"], material)
    return created_materials


def color_match(pixel: tuple[float, float, float], target: tuple[float, float, float, float], tol: float = 0.35) -> bool:
    return (
        abs(pixel[0] - target[0]) <= tol
        and abs(pixel[1] - target[1]) <= tol
        and abs(pixel[2] - target[2]) <= tol
    )


def extract_bboxes_from_mask(
    mask_path: Path,
    width: int,
    height: int,
    defect_ids_present: list[str],
) -> dict[str, list[int]]:
    """Return defect_id → [x, y, w, h] in top-left image coords."""
    image = bpy.data.images.load(str(mask_path), check_existing=False)
    pixels = list(image.pixels[:])
    result: dict[str, list[int]] = {}
    for defect_id in defect_ids_present:
        color = DEFECT_MASK_COLORS.get(defect_id)
        if color is None:
            continue
        min_x, min_y, max_x, max_y = width, height, -1, -1
        for y in range(height):
            offset = y * width * 4
            for x in range(width):
                i = offset + x * 4
                if color_match((pixels[i], pixels[i + 1], pixels[i + 2]), color):
                    min_x = min(min_x, x)
                    max_x = max(max_x, x)
                    min_y = min(min_y, y)
                    max_y = max(max_y, y)
        if max_x >= min_x and max_y >= min_y:
            top = height - 1 - max_y
            result[defect_id] = [min_x, top, max_x - min_x + 1, max_y - min_y + 1]
    bpy.data.images.remove(image)
    return result


def rle_from_positions(positions: set[int], total_pixels: int) -> dict[str, Any]:
    """COCO uncompressed RLE in column-major order."""
    if not positions:
        return {"counts": [total_pixels]}
    ordered = sorted(positions)
    runs: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        runs.append((start, previous))
        start = previous = value
    runs.append((start, previous))
    counts: list[int] = []
    cursor = 0
    for start, end in runs:
        counts.append(start - cursor)
        counts.append(end - start + 1)
        cursor = end + 1
    counts.append(total_pixels - cursor)
    return {"counts": counts}


def extract_instance_annotations(
    mask_path: Path,
    width: int,
    height: int,
    instances: list[dict[str, Any]],
    palette_lookup: dict[tuple[float, float, float], str],
) -> list[dict[str, Any]]:
    image = bpy.data.images.load(str(mask_path), check_existing=False)
    pixels = list(image.pixels[:])
    positions: dict[str, set[int]] = {instance_id: set() for instance_id in palette_lookup.values()}
    normalized_targets = []
    for target, instance_id in palette_lookup.items():
        length = math.sqrt(sum(value * value for value in target)) or 1.0
        normalized_targets.append((tuple(value / length for value in target), instance_id))
    for y in range(height):
        row = y * width * 4
        top_y = height - 1 - y
        for x in range(width):
            offset = row + x * 4
            rgb = (pixels[offset], pixels[offset + 1], pixels[offset + 2])
            if max(rgb) < 0.002:
                continue
            length = math.sqrt(sum(value * value for value in rgb)) or 1.0
            direction = tuple(value / length for value in rgb)
            distance, instance_id = min(
                (
                    math.sqrt(sum((direction[channel] - target[channel]) ** 2 for channel in range(3))),
                    candidate_id,
                )
                for target, candidate_id in normalized_targets
            )
            if distance > 0.22:
                continue
            positions[instance_id].add(x * height + top_y)
    bpy.data.images.remove(image)

    metadata: dict[str, dict[str, Any]] = {}
    for item in instances:
        instance_id = str(item["instance_id"])
        metadata.setdefault(
            instance_id,
            {
                "instance_id": instance_id,
                "defect_id": str(item["defect_id"]),
                "region_id": item.get("region_id"),
                "layer_index": item.get("layer_index"),
                "part_id": str(item["part_id"]),
                "surface_id": str(item["surface_id"]),
                "severity": round(float(item["severity"]) * 100.0, 4),
                "uv": [round(float(value), 7) for value in item.get("uv", (0.0, 0.0))],
                "location": [
                    round(float(value), 7) for value in item.get("location", (0.0, 0.0, 0.0))
                ],
                "normal": [
                    round(float(value), 7) for value in item.get("normal", (0.0, 0.0, 1.0))
                ],
            },
        )

    annotations: list[dict[str, Any]] = []
    for instance_id, occupied in positions.items():
        if not occupied:
            continue
        xs = [index // height for index in occupied]
        ys = [index % height for index in occupied]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        record = dict(metadata[instance_id])
        record.update(
            {
                "bbox": [min_x, min_y, max_x - min_x + 1, max_y - min_y + 1],
                "area": len(occupied),
                "segmentation": {
                    "size": [height, width],
                    **rle_from_positions(occupied, width * height),
                },
            }
        )
        annotations.append(record)
    return annotations


def bboxes_by_class(instances: list[dict[str, Any]]) -> dict[str, list[int]]:
    grouped: dict[str, list[list[int]]] = {}
    for instance in instances:
        grouped.setdefault(str(instance["defect_id"]), []).append(list(instance["bbox"]))
    result: dict[str, list[int]] = {}
    for defect_id, boxes in grouped.items():
        min_x = min(box[0] for box in boxes)
        min_y = min(box[1] for box in boxes)
        max_x = max(box[0] + box[2] for box in boxes)
        max_y = max(box[1] + box[3] for box in boxes)
        result[defect_id] = [min_x, min_y, max_x - min_x, max_y - min_y]
    return result


def save_crop(source_path: Path, destination_path: Path, box: list[int]) -> tuple[int, int]:
    left, top, crop_width, crop_height = box
    source = bpy.data.images.load(str(source_path), check_existing=False)
    source_width, source_height = source.size
    pixels = list(source.pixels[:])
    bottom = source_height - (top + crop_height)
    cropped: list[float] = []
    for y in range(bottom, bottom + crop_height):
        start = (y * source_width + left) * 4
        cropped.extend(pixels[start : start + crop_width * 4])
    target = bpy.data.images.new(
        destination_path.stem,
        width=crop_width,
        height=crop_height,
        alpha=True,
        float_buffer=False,
    )
    target.pixels.foreach_set(cropped)
    target.filepath_raw = str(destination_path)
    target.file_format = "PNG"
    target.save()
    bpy.data.images.remove(source)
    bpy.data.images.remove(target)
    return crop_width, crop_height


def padded_crop_box(
    bbox: list[int], width: int, height: int, padding_fraction: float
) -> list[int]:
    x, y, box_width, box_height = bbox
    padding = max(2, round(max(box_width, box_height) * padding_fraction))
    left = max(0, x - padding)
    top = max(0, y - padding)
    right = min(width, x + box_width + padding)
    bottom = min(height, y + box_height + padding)
    return [left, top, max(1, right - left), max(1, bottom - top)]


# ---------------------------------------------------------------------------
# Annotations / packaging
# ---------------------------------------------------------------------------


def write_annotations(
    output: Path,
    samples: list[dict[str, Any]],
    width: int,
    height: int,
    annotation_format: str,
    categories: list[str],
) -> None:
    annotations = output / "annotations"
    annotations.mkdir(exist_ok=True)
    cat_to_id = {name: index + 1 for index, name in enumerate(categories)}

    if annotation_format == "coco_json":
        coco: dict[str, Any] = {
            "info": {"description": "BladeForge Cycles v2 dataset"},
            "licenses": [],
            "categories": [{"id": cid, "name": name} for name, cid in cat_to_id.items()],
            "images": [],
            "annotations": [],
        }
        ann_id = 1
        image_id = 1
        for sample in samples:
            views = [sample]
            if sample.get("crop"):
                views.append(sample["crop"])
            for view in views:
                view_width = int(view.get("width") or width)
                view_height = int(view.get("height") or height)
                coco["images"].append(
                    {
                        "id": image_id,
                        "file_name": view["image"],
                        "width": view_width,
                        "height": view_height,
                        "mask_file": view.get("mask"),
                        "instance_mask_file": view.get("instance_mask"),
                    }
                )
                for instance in view.get("instances") or []:
                    defect_id = str(instance["defect_id"])
                    if defect_id not in cat_to_id:
                        continue
                    bbox = instance["bbox"]
                    coco["annotations"].append(
                        {
                            "id": ann_id,
                            "image_id": image_id,
                            "category_id": cat_to_id[defect_id],
                            "bbox": bbox,
                            "segmentation": instance["segmentation"],
                            "area": instance["area"],
                            "iscrowd": 0,
                            "attributes": {
                                "instance_id": instance["instance_id"],
                                "severity": instance["severity"],
                                "seed": sample.get("seed"),
                                "defect_id": defect_id,
                                "part_id": instance["part_id"],
                                "surface_id": instance["surface_id"],
                                "uv": instance["uv"],
                                "world_location_m": instance["location"],
                                "world_normal": instance["normal"],
                            },
                        }
                    )
                    ann_id += 1
                image_id += 1
        (annotations / "coco.json").write_text(json.dumps(coco, indent=2), encoding="utf-8")
    else:
        labels = annotations / "labels"
        labels.mkdir(exist_ok=True)
        name_to_yolo = {name: index for index, name in enumerate(categories)}
        for sample in samples:
            views = [sample]
            if sample.get("crop"):
                views.append(sample["crop"])
            for view in views:
                view_width = int(view.get("width") or width)
                view_height = int(view.get("height") or height)
                lines: list[str] = []
                for instance in view.get("instances") or []:
                    defect_id = str(instance["defect_id"])
                    if defect_id not in name_to_yolo:
                        continue
                    x, y, box_w, box_h = instance["bbox"]
                    cx = (x + box_w / 2) / view_width
                    cy = (y + box_h / 2) / view_height
                    nw = box_w / view_width
                    nh = box_h / view_height
                    lines.append(
                        f"{name_to_yolo[defect_id]} {cx:.8f} {cy:.8f} {nw:.8f} {nh:.8f}"
                    )
                stem = Path(view["image"]).stem
                (labels / f"{stem}.txt").write_text(
                    "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
                )
        yaml_names = "\n".join(f"  {i}: {name}" for i, name in enumerate(categories))
        (annotations / "data.yaml").write_text(
            f"path: ..\ntrain: images\nval: images\nnames:\n{yaml_names}\n",
            encoding="utf-8",
        )


def package(output: Path, dataset_name: str) -> Path:
    archive = output / f"{dataset_name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file() and path != archive:
                bundle.write(path, path.relative_to(output))
    return archive


# ---------------------------------------------------------------------------
# Defect layer resolution
# ---------------------------------------------------------------------------


def resolve_defect_layers(job: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    primary = str(job.get("defect_type") or "leading_edge_erosion")
    layers = [dict(layer) for layer in (config.get("defect_layers") or [])]
    if any(str(layer.get("defect_id")) == primary for layer in layers):
        return layers
    defaults = {
        "surface_crack": "blades",
        "leading_edge_erosion": "blades",
        "trailing_edge_damage": "blades",
        "corrosion": "tower",
        "rust_staining": "tower",
        "paint_peeling": "blades",
        "coating_loss": "blades",
        "scratches": "blades",
        "dents": "tower",
        "lightning_strike": "blades",
        "holes": "blades",
        "chips": "blades",
        "delamination": "blades",
        "oil_stains": "nacelle",
        "dirt_buildup": "tower",
        "ice_buildup": "blades",
        "structural_deformation": "tower",
    }
    selected_part = str(config.get("turbine_part_id") or "all")
    default_part = defaults.get(primary, "blades")
    primary_part = (
        selected_part
        if selected_part not in {"all", "rotor"}
        else (default_part if selected_part == "all" or default_part in {"blades", "hub"} else "hub")
    )
    primary_layer = {
        "defect_id": primary,
        "part_id": primary_part,
        "severity": int((int(job["severity_min"]) + int(job["severity_max"])) / 2),
        "coverage": 25,
        "size_scale": 1.0,
        "opacity": 100,
        "rotation_deg": 0.0,
        "spread": 40,
        "randomness": 50,
        "color_hex": "#6b7280",
        "region_id": None,
    }
    return [primary_layer, *layers]


def build_defect_materials() -> dict[str, Any]:
    """RGB + mask materials for every supported defect."""
    rgb: dict[str, Any] = {}
    mask: dict[str, Any] = {}

    specs: dict[str, tuple[tuple[float, float, float, float], float, float]] = {
        # color, roughness, metallic
        "leading_edge_erosion": ((0.50, 0.48, 0.42, 0.72), 0.96, 0.0),
        "surface_crack": ((0.035, 0.034, 0.032, 1), 0.92, 0.0),
        "delamination": ((0.62, 0.63, 0.58, 1), 0.72, 0.0),
        "lightning_strike": ((0.08, 0.08, 0.09, 1), 0.95, 0.05),
        "coating_loss": ((0.72, 0.73, 0.69, 1), 0.92, 0.0),
        "paint_peeling": ((0.78, 0.75, 0.66, 1), 0.94, 0.0),
        "corrosion": ((0.46, 0.24, 0.10, 1), 0.82, 0.05),
        "rust_staining": ((0.52, 0.25, 0.09, 1), 0.84, 0.0),
        "dirt_buildup": ((0.30, 0.25, 0.18, 0.48), 0.98, 0.0),
        "scratches": ((0.46, 0.47, 0.46, 1), 0.62, 0.0),
        "chips": ((0.50, 0.51, 0.48, 1), 0.88, 0.0),
        "dents": ((0.64, 0.65, 0.63, 1), 0.72, 0.0),
        "holes": ((0.02, 0.02, 0.02, 1), 0.95, 0.0),
        "oil_stains": ((0.12, 0.08, 0.04, 1), 0.25, 0.0),
        "ice_buildup": ((0.85, 0.92, 0.98, 1), 0.15, 0.0),
        "trailing_edge_damage": ((0.18, 0.16, 0.14, 1), 0.90, 0.0),
        "structural_deformation": ((0.60, 0.62, 0.64, 1), 0.50, 0.05),
    }
    for defect_id, (color, roughness, metallic) in specs.items():
        rgb[defect_id] = principled_material(f"RGB_{defect_id}", color, roughness, metallic)
        mask[defect_id] = emission_material(f"MASK_{defect_id}", DEFECT_MASK_COLORS[defect_id])
        if defect_id not in {"oil_stains", "ice_buildup", "scratches", "surface_crack"}:
            add_micro_surface(
                rgb[defect_id],
                scale=8.0 if defect_id in {"corrosion", "rust_staining", "dirt_buildup"} else 20.0,
                strength=0.16 if defect_id in {"corrosion", "leading_edge_erosion"} else 0.08,
                distance=0.045 if defect_id in {"corrosion", "leading_edge_erosion"} else 0.018,
            )
    ice_shader = rgb["ice_buildup"].node_tree.nodes.get("Principled BSDF")
    if ice_shader is not None:
        if "Transmission Weight" in ice_shader.inputs:
            ice_shader.inputs["Transmission Weight"].default_value = 0.45
        if "Coat Weight" in ice_shader.inputs:
            ice_shader.inputs["Coat Weight"].default_value = 0.6
    return {"defect_rgb": rgb, "defect_mask": mask}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


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
    config = dict(job.get("config") or {})
    gemini_edit = config.get("image_edit_backend") == "gemini"

    lighting_environment = {
        "overcast": "OVERCAST_DAY_V1",
        "cloudy": "CLOUDY_DAY_V1",
        "golden_hour": "GOLDEN_HOUR_V1",
        "midday": "CLEAR_DAY_V1",
    }
    environment_id = config.get("environment_id") or lighting_environment.get(
        str(config.get("lighting_preset") or "overcast"), "OVERCAST_DAY_V1"
    )
    weather_intensity = float(config["weather_intensity"]) if config.get("weather_intensity") is not None else 0.5
    turbine_part_id = str(config.get("turbine_part_id") or "all")
    camera_view = config.get("camera_view")
    camera_views = list(config.get("camera_views") or [])
    generate_all_angles = bool(config.get("generate_all_angles"))
    region_document = config.get("region_document")
    crop_policy = config.get("crop_policy") or "full_frame"
    model_asset_key = config.get("model_asset_key")
    hdri_asset_key = config.get("hdri_asset_key")
    camera_fov_default = float(config.get("camera_fov") or 45)

    defect_layers = resolve_defect_layers(job, config)
    # Per-sample severity still varies within job range for the primary layer.
    defect_types_used = sorted({str(layer["defect_id"]) for layer in defect_layers})

    clean_scene()
    engine_name = configure_render(width, height, int(config.get("compression_quality") or 92))

    # -----------------------------------------------------------------------
    # Realistic PBR materials — real turbine gelcoat is smooth gloss paint,
    # roughness ~0.15-0.22, with a clear lacquer coat layer on top.
    # Tower is epoxy-painted steel, roughness ~0.28.
    # -----------------------------------------------------------------------
    gelcoat = principled_material("WeatheredGelcoatOffWhite", (0.88, 0.89, 0.87, 1.0), 0.16, 0.0)
    metal = principled_material("TowerPaintedSteelGrey", (0.72, 0.73, 0.72, 1.0), 0.28, 0.0)
    nacelle_shell = principled_material("NacelleCompositeShell", (0.86, 0.87, 0.85, 1.0), 0.18, 0.0)
    hub_shell = principled_material("HubCompositeShell", (0.87, 0.88, 0.86, 1.0), 0.17, 0.0)
    concrete = principled_material("FoundationConcrete", (0.52, 0.50, 0.47, 1.0), 0.82, 0.0)

    # Add clearcoat layer to gelcoat/nacelle/hub (critical for photorealism)
    for _mat in (gelcoat, nacelle_shell, hub_shell):
        _sh = _mat.node_tree.nodes.get("Principled BSDF")
        if _sh is not None:
            if "Coat Weight" in _sh.inputs:
                _sh.inputs["Coat Weight"].default_value = 0.75
            if "Coat Roughness" in _sh.inputs:
                _sh.inputs["Coat Roughness"].default_value = 0.05
            if "Specular IOR Level" in _sh.inputs:
                _sh.inputs["Specular IOR Level"].default_value = 0.50
            if "IOR" in _sh.inputs:
                _sh.inputs["IOR"].default_value = 1.50

    # Subtle aging variation — low-amplitude so it reads as weathering, not plastic
    add_material_variation(
        gelcoat,
        base=(0.83, 0.85, 0.82, 1.0),
        secondary=(0.93, 0.94, 0.91, 1.0),
        noise_scale=22.0,
        bump_strength=0.012,
        bump_distance=0.008,
    )
    add_material_variation(
        metal,
        base=(0.62, 0.64, 0.63, 1.0),
        secondary=(0.78, 0.79, 0.77, 1.0),
        noise_scale=14.0,
        bump_strength=0.022,
        bump_distance=0.016,
    )
    add_material_variation(
        nacelle_shell,
        base=(0.80, 0.82, 0.80, 1.0),
        secondary=(0.92, 0.93, 0.90, 1.0),
        noise_scale=16.0,
        bump_strength=0.010,
        bump_distance=0.008,
    )
    add_material_variation(
        hub_shell,
        base=(0.82, 0.83, 0.81, 1.0),
        secondary=(0.93, 0.94, 0.91, 1.0),
        noise_scale=18.0,
        bump_strength=0.010,
        bump_distance=0.008,
    )
    materials: dict[str, Any] = {
        "gelcoat": gelcoat,
        "metal": metal,
        "tower_shell": metal,
        "nacelle_shell": nacelle_shell,
        "hub_shell": hub_shell,
        "concrete": concrete,
        "mask_black": emission_material("MaskBlack", (0, 0, 0, 1)),
        "erosion": principled_material("ErodedComposite", (0.72, 0.70, 0.64, 1), 0.78),
        "rain": principled_material("WeatherRain", (0.30, 0.46, 0.62, 1), 0.12),
        "snow": principled_material("WeatherSnow", (0.96, 0.98, 1.0, 1), 0.35),
        "lightning": emission_material("WeatherLightning", (0.70, 0.84, 1.0, 1)),
    }
    materials.update(build_defect_materials())

    repository_root = Path(__file__).resolve().parents[2]
    explicit_model_path = config.get("model_asset_path")
    model_path = (
        Path(str(explicit_model_path)).resolve()
        if explicit_model_path
        else repository_root / "public" / "assets" / "models" / "wind-turbine.fbx"
    )
    model_source = "uploaded" if explicit_model_path else "default"
    try:
        parts = import_turbine_model(model_path, gelcoat, metal, concrete)
    except Exception:
        if explicit_model_path:
            raise
        parts = build_turbine(gelcoat, metal, concrete)
        model_source = "procedural_fallback"
    apply_realistic_turbine_materials(parts, materials, force=model_source in {"default", "procedural_fallback"})
    apply_part_visibility(parts, turbine_part_id)

    bpy.ops.object.camera_add(location=(120, -120, 60))
    camera = bpy.context.object
    camera.data.type = "PERSP"
    bpy.context.scene.camera = camera

    bpy.ops.object.light_add(type="SUN", location=(50, -80, 120))
    sun = bpy.context.object
    sun.data.energy = 5.0
    sun.rotation_euler = (math.radians(45), math.radians(15), math.radians(30))

    world, background, sky = setup_world_nodes()
    hdri_path = selected_hdri_path(config, environment_id)
    hdri_loaded = connect_hdri(world, background, hdri_path)
    if hdri_loaded:
        sky = None
    env_meta = configure_environment(
        environment_id, weather_intensity, world, background, sky, sun, materials
    )

    target_base = part_target_point(parts, turbine_part_id)
    base_framing = framing_for_part(parts, turbine_part_id, camera_fov_default)
    if generate_all_angles:
        angle_plan = camera_views or all_angle_views(
            image_count, base_framing["distance_m"], target_base.z
        )
        if len(angle_plan) != image_count:
            raise RuntimeError("The all-angle camera plan must contain exactly one pose per image.")
    else:
        angle_plan = None

    samples: list[dict[str, Any]] = []
    started = time.monotonic()
    emit(
        1,
        "rendering",
        "Blender v2 scene initialized.",
        renderer="bladeforge_cycles_v2",
        engine=engine_name,
        environment_id=env_meta["environment_id"],
    )

    for sample_index in range(image_count):
        seed = base_seed + sample_index
        rng = random.Random(seed)

        # The primary requested class varies inside the requested job range. Other
        # layers retain the explicit severity selected in the region editor.
        active_layers: list[dict[str, Any]] = []
        for layer in defect_layers:
            layer_copy = dict(layer)
            if str(layer_copy.get("defect_id")) == str(job["defect_type"]):
                layer_copy["severity"] = rng.uniform(severity_min, severity_max)
            if crop_policy == "defect_crop":
                layer_copy["size_scale"] = max(float(layer_copy.get("size_scale") or 1.0), 2.4)
                layer_copy["coverage"] = max(float(layer_copy.get("coverage") or 0.0), 35.0)
                layer_copy["spread"] = min(float(layer_copy.get("spread") or 40.0), 18.0)
            active_layers.append(layer_copy)

        instances: list[dict[str, Any]] = []
        for layer_index, layer in enumerate(active_layers):
            instances.extend(
                gemini_guidance.spawn_regions(
                    layer, parts, region_document, rng, sample_index, layer_index, sys.modules[__name__]
                ) if gemini_edit else spawn_defects_for_layer(
                    layer, parts, materials, region_document, rng, sample_index
                )
            )
        if not instances:
            raise RuntimeError(
                "No defect geometry was created. Check the selected part and painted region; "
                "the renderer will not deliver an empty, falsely successful dataset."
            )

        # For defect-crop jobs, the delivered dataset must actually show the
        # defect. A pinned preview camera is useful for full-frame renders, but
        # if it misses the generated damage, annotation export becomes empty.
        use_inspection_framing = (
            crop_policy == "defect_crop"
            and not generate_all_angles
        )
        inspection_pose = inspection_camera_from_instances(instances, rng, camera_fov_default) if use_inspection_framing else None

        # Camera
        if inspection_pose is not None:
            target = inspection_pose["target"]
            camera.location = inspection_pose["location"]
            roll = float(inspection_pose["roll_deg"])
            fov = float(inspection_pose["fov_deg"])
            az = 0.0
            el = 0.0
            dist = float((camera.location - target).length)
            camera.data.lens = fov_to_lens(fov)
            point_at(camera, target, roll_deg=roll)
        elif camera_view and not generate_all_angles:
            view = camera_view
            target = Vector(
                (
                    float(view.get("target_x_m", 0.0)),
                    float(view.get("target_y_m", 0.0)),
                    float(view.get("target_z_m", target_base.z)),
                )
            )
            az = float(view["azimuth_deg"])
            el = float(view["elevation_deg"])
            dist = float(view["distance_m"])
            roll = float(view.get("roll_deg") or 0.0)
            fov = float(view.get("fov_deg") or camera_fov_default)
        elif generate_all_angles and angle_plan is not None:
            plan = angle_plan[sample_index]
            target = Vector(
                (
                    float(plan.get("target_x_m", target_base.x)),
                    float(plan.get("target_y_m", target_base.y)),
                    float(plan.get("target_z_m", target_base.z)),
                )
            )
            az = float(plan["azimuth_deg"])
            el = float(plan["elevation_deg"])
            dist = float(plan["distance_m"])
            roll = float(plan.get("roll_deg") or 0.0)
            fov = float(plan.get("fov_deg") or camera_fov_default)
        else:
            target = target_base + Vector(
                (rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-1, 3))
            )
            az = base_framing["azimuth_deg"] + rng.uniform(-12, 12)
            el = base_framing["elevation_deg"] + rng.uniform(-6, 6)
            dist = base_framing["distance_m"] * rng.uniform(0.9, 1.15)
            roll = rng.uniform(-2, 2)
            fov = camera_fov_default

        if inspection_pose is None:
            camera.location = orbit_camera_location(target, az, el, dist)
            camera.data.lens = fov_to_lens(fov)
            point_at(camera, target, roll_deg=roll)

        if gemini_edit:
            bpy.context.view_layer.update()
            instances = gemini_guidance.frame_unpainted_regions(
                instances, active_layers, parts, camera, rng, sample_index, sys.modules[__name__]
            )

        # Mild sun jitter per sample
        sun.rotation_euler[2] = math.radians(30) + rng.uniform(-0.3, 0.3)
        env_meta = configure_environment(
            environment_id, weather_intensity, world, background, sky, sun, materials
        )
        weather_effects = create_weather_effects(
            env_meta, target, camera, materials, rng, bool(config.get("weather", False))
        )

        file_stem = f"sample_{sample_index:06d}"
        image_relative = f"images/{file_stem}.png"
        mask_relative = f"masks/{file_stem}.png"
        instance_mask_relative = f"masks/{file_stem}_instances.png"
        metadata_relative = f"metadata/{file_stem}.json"

        render_objects = list(parts.values()) + [item["object"] for item in instances]
        original_materials = capture_materials(render_objects)
        original_hide_render = {obj.name: bool(obj.hide_render) for obj in render_objects}
        sun.hide_render = False
        render_still(output / image_relative)

        # Mask passes: exact emission colours, black world, no fog/weather/lights.
        original_bg = tuple(background.inputs["Color"].default_value)
        original_strength = background.inputs["Strength"].default_value
        original_exposure = getattr(bpy.context.scene.view_settings, "exposure", 0.0)
        original_transform = getattr(bpy.context.scene.view_settings, "view_transform", None)
        fog = world.node_tree.nodes.get("BladeForgeFog")
        original_fog_density = fog.inputs["Density"].default_value if fog is not None else 0.0
        background.inputs["Color"].default_value = (0, 0, 0, 1)
        background.inputs["Strength"].default_value = 0.0
        if fog is not None:
            fog.inputs["Density"].default_value = 0.0
        sun.hide_render = True
        for effect in weather_effects:
            effect.hide_render = True
        if hasattr(bpy.context.scene.view_settings, "exposure"):
            bpy.context.scene.view_settings.exposure = 0.0
        if original_transform is not None:
            try:
                bpy.context.scene.view_settings.view_transform = "Standard"
            except (TypeError, ValueError):
                pass

        for obj in render_objects:
            if bool(obj.get("bladeforge_mask_only", False)):
                obj.hide_render = False
        set_mask_mode(parts, instances, materials, enabled=True, original_materials=original_materials)
        render_still(output / mask_relative)

        instance_ids = list(dict.fromkeys(str(item["instance_id"]) for item in instances))
        palette, palette_lookup = instance_palette(instance_ids)
        instance_materials = set_instance_mask_mode(parts, instances, materials, palette)
        render_still(output / instance_mask_relative)

        restore_materials(render_objects, original_materials)
        for obj in render_objects:
            if obj.name in original_hide_render:
                obj.hide_render = original_hide_render[obj.name]
        sun.hide_render = False
        for effect in weather_effects:
            effect.hide_render = False
        background.inputs["Color"].default_value = original_bg
        background.inputs["Strength"].default_value = original_strength
        if fog is not None:
            fog.inputs["Density"].default_value = original_fog_density
        if hasattr(bpy.context.scene.view_settings, "exposure"):
            bpy.context.scene.view_settings.exposure = original_exposure
        if original_transform is not None:
            try:
                bpy.context.scene.view_settings.view_transform = original_transform
            except (TypeError, ValueError):
                pass
        for material in instance_materials:
            bpy.data.materials.remove(material)

        visible_instances = extract_instance_annotations(
            output / instance_mask_relative, width, height, instances, palette_lookup
        )
        if not visible_instances:
            raise RuntimeError("No selected defect region is visible in this camera view. Adjust the camera or paint; no artificial annotations were created.")
        bboxes = bboxes_by_class(visible_instances)
        combined_bbox = None
        if bboxes:
            xs = []
            ys = []
            x2s = []
            y2s = []
            for box in bboxes.values():
                xs.append(box[0])
                ys.append(box[1])
                x2s.append(box[0] + box[2])
                y2s.append(box[1] + box[3])
            combined_bbox = [min(xs), min(ys), max(x2s) - min(xs), max(y2s) - min(ys)]

        crop_record = None
        if crop_policy == "full_and_crop" and combined_bbox is not None:
            crop_box = padded_crop_box(
                combined_bbox,
                width,
                height,
                float(config.get("crop_padding_fraction") or 0.15),
            )
            crop_image_relative = f"images/{file_stem}_crop.png"
            crop_mask_relative = f"masks/{file_stem}_crop.png"
            crop_instance_relative = f"masks/{file_stem}_crop_instances.png"
            crop_width, crop_height = save_crop(
                output / image_relative, output / crop_image_relative, crop_box
            )
            save_crop(output / mask_relative, output / crop_mask_relative, crop_box)
            save_crop(
                output / instance_mask_relative,
                output / crop_instance_relative,
                crop_box,
            )
            crop_instances = extract_instance_annotations(
                output / crop_instance_relative,
                crop_width,
                crop_height,
                instances,
                palette_lookup,
            )
            crop_record = {
                "image": crop_image_relative,
                "mask": crop_mask_relative,
                "instance_mask": crop_instance_relative,
                "width": crop_width,
                "height": crop_height,
                "bbox": [0, 0, crop_width, crop_height],
                "bboxes": bboxes_by_class(crop_instances),
                "instances": crop_instances,
                "source_crop_box": crop_box,
            }

        primary_layer = next(
            (
                layer
                for layer in active_layers
                if str(layer.get("defect_id")) == str(job["defect_type"])
            ),
            active_layers[0],
        )
        primary_severity = float(primary_layer.get("severity", 50))
        parameters = {
            "seed": seed,
            "severity": round(primary_severity, 4),
            "severity_label": (
                "early" if primary_severity < 34 else "moderate" if primary_severity < 67 else "severe"
            ),
            "defect_layers": [
                {k: v for k, v in layer.items() if k != "object"} for layer in active_layers
            ],
            "defect_instance_count": len(instances),
            "visible_defect_instance_count": len(visible_instances),
            "instances": visible_instances,
            "bboxes": bboxes,
            "bbox": combined_bbox,
            "camera": {
                "target": list(target),
                "azimuth_deg": az,
                "elevation_deg": el,
                "distance_m": dist,
                "roll_deg": roll,
                "fov_deg": fov,
                "location": list(camera.location),
            },
            "camera_fov": fov,
            "lighting_preset": config.get("lighting_preset"),
            "environment_id": env_meta["environment_id"],
            "weather_intensity": weather_intensity,
            "weather_enabled": bool(config.get("weather", False)),
            "weather": env_meta,
            "turbine_part_id": turbine_part_id,
            "generate_all_angles": generate_all_angles,
            "crop_policy": crop_policy,
            "model_asset_key": model_asset_key,
            "model_source": model_source,
            "model_path_name": model_path.name,
            "hdri_asset_key": hdri_asset_key,
            "hdri_loaded": hdri_loaded,
            "hdri_path_name": hdri_path.name if hdri_path else None,
            "render_engine": "v2",
            "blender_engine": engine_name,
            "region_document_present": region_document is not None,
            "image_edit_backend": "gemini" if gemini_edit else None,
            "output_settings": {key: config[key] for key in ("image_width", "image_height", "compression_quality", "crop_policy", "crop_padding_fraction") if key in config},
            "annotation_semantics": "edit_region_guidance_unverified" if gemini_edit else "rendered_defect",
        }
        (output / metadata_relative).write_text(json.dumps(parameters, indent=2), encoding="utf-8")
        full_record = {
            "image": image_relative,
            "mask": mask_relative,
            "instance_mask": instance_mask_relative,
            "metadata": metadata_relative,
            "width": width,
            "height": height,
            "bbox": combined_bbox,
            "bboxes": bboxes,
            "instances": visible_instances,
            "seed": seed,
            "severity": round(primary_severity, 4),
        }
        if crop_policy == "full_and_crop" and crop_record is not None:
            full_record["crop"] = crop_record
        samples.append(full_record)

        remove_weather_effects(weather_effects)
        remove_defect_objects(instances)
        # Clear host displace modifiers added by structural_deformation
        for obj in parts.values():
            for mod in list(obj.modifiers):
                if mod.name.startswith("DEF_structural_deformation") and mod.name.endswith("_host"):
                    obj.modifiers.remove(mod)

        progress = max(2, min(88, round((sample_index + 1) / image_count * 88)))
        emit(progress, "rendering", f"Rendered sample {sample_index + 1} of {image_count}.")

    emit(90, "processing_annotations", "Deriving annotation exports from rendered masks.")
    # Global ordering keeps class ids stable when customers merge multiple datasets.
    write_annotations(
        output,
        samples,
        width,
        height,
        job["annotation_format"],
        DEFECT_CATEGORY_ORDER,
    )

    manifest = {
        "schema_version": "2.0",
        "job_id": job["id"],
        "dataset_name": job["dataset_name"],
        "defect_type": defect_types_used[0] if len(defect_types_used) == 1 else "multi",
        "defect_types": defect_types_used,
        "blade_material": "gelcoat_composite_v2",
        "annotation_format": job["annotation_format"],
        "image_width": width,
        "image_height": height,
        "sample_count": len(samples),
        "renderer": "bladeforge_cycles_v2",
        "engine": engine_name,
        "environment_id": env_meta["environment_id"],
        "weather_intensity": weather_intensity,
        "turbine_part_id": turbine_part_id,
        "crop_policy": crop_policy,
        "model_asset_key": model_asset_key,
        "model_source": model_source,
        "hdri_asset_key": hdri_asset_key,
        "hdri_loaded": hdri_loaded,
        "generate_all_angles": generate_all_angles,
        "samples": samples,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "README.md").write_text(
        "# BladeForge v2 dataset\n\n"
        f"Full-turbine dataset rendered from the {model_source} model with {engine_name}.\n"
        "RGB images, class masks, instance masks, per-sample metadata, and per-instance "
        "COCO/YOLO annotations are included.\n",
        encoding="utf-8",
    )
    package(output, job["dataset_name"])
    emit(
        99,
        "processing_annotations",
        "Dataset package validated locally.",
        elapsed_seconds=round(time.monotonic() - started, 3),
        renderer="bladeforge_cycles_v2",
        engine=engine_name,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
