"""Build the generated simulation assets: textures, ground/road meshes, and the drone model.

Everything lands in ``sim/generated/`` (gitignored) so the repo only carries source.
The drone model is derived from the ardupilot_gazebo checkout at setup time rather than
vendored, because that repo is LGPL and we only need a few edits to it:

* ``nadir_gimbal``  - gimbal_small_3d with a higher resolution, narrower camera, a fixed
  topic name and no GStreamer/zoom plugins (we read frames over gz-transport instead).
* ``search_drone``  - iris_with_gimbal with that gimbal swapped in.

Run:  python sim/build_assets.py [--ardupilot-gazebo /opt/sim/ardupilot_gazebo]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
GEN = HERE / "generated"

# Camera spec shared with the vision projection code through sim/camera.json.
CAMERA = {"width": 1280, "height": 960, "hfov_rad": 1.2, "rate_hz": 5.0}


def _noise(rng: np.random.Generator, size: int, octaves: int = 5) -> np.ndarray:
    """Tileable multi-octave value noise in [0, 1]."""
    out = np.zeros((size, size), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = 4 * 2**o
        grid = rng.random((cells, cells)).astype(np.float32)
        # wrap-pad trick: resizing a tiled 3x3 copy keeps edges continuous
        tiled = np.tile(grid, (3, 3))
        img = Image.fromarray((tiled * 255).astype(np.uint8)).resize((size * 3, size * 3), Image.BICUBIC)
        layer = np.asarray(img, np.float32)[size : 2 * size, size : 2 * size] / 255.0
        out += amp * layer
        total += amp
        amp *= 0.55
    return out / total


def grass_texture(seed: int, tint: tuple[float, float, float], size: int = 1024) -> Image.Image:
    rng = np.random.default_rng(seed)
    n = _noise(rng, size)
    speck = rng.random((size, size)).astype(np.float32)
    base = np.array(tint, np.float32)
    shade = 0.75 + 0.5 * n[..., None] + 0.12 * (speck[..., None] - 0.5)
    rgb = np.clip(base * shade, 0, 255).astype(np.uint8)
    return Image.fromarray(rgb, "RGB")


def asphalt_texture(seed: int, size: int = 1024, lane_line: bool = True) -> Image.Image:
    rng = np.random.default_rng(seed)
    n = _noise(rng, size, octaves=4)
    speck = rng.random((size, size)).astype(np.float32)
    g = 70 + 25 * n + 30 * (speck - 0.5)
    rgb = np.repeat(np.clip(g, 0, 255)[..., None], 3, axis=2).astype(np.uint8)
    img = Image.fromarray(rgb, "RGB")
    if lane_line:
        d = ImageDraw.Draw(img)
        w = size // 70  # ~0.1 m dashed line at the texture centre (u axis = across road)
        c = size // 2
        for v in range(0, size, size // 2):
            d.rectangle([c - w, v, c + w, v + size // 4], fill=(220, 210, 160))
    return img


def dirt_texture(seed: int, size: int = 512) -> Image.Image:
    rng = np.random.default_rng(seed)
    n = _noise(rng, size, octaves=4)
    speck = rng.random((size, size)).astype(np.float32)
    base = np.array([120, 98, 70], np.float32)
    rgb = np.clip(base * (0.8 + 0.4 * n[..., None] + 0.1 * (speck[..., None] - 0.5)), 0, 255)
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def write_quad_obj(path: Path, quads: list[tuple[list[tuple[float, float]], str, float]], mtl: str) -> None:
    """Write a set of textured quads. Each quad: (4 xy corners CCW, material, uv_scale_m)."""
    lines = [f"mtllib {mtl}"]
    vi = 1
    for corners, material, uv_m in quads:
        lines.append(f"usemtl {material}")
        x0, y0 = corners[0]
        # u along first edge, v along last edge, both in metres / uv_m
        ex = np.subtract(corners[1], corners[0])
        ey = np.subtract(corners[3], corners[0])
        lx, ly = float(np.hypot(*ex)), float(np.hypot(*ey))
        uvs = [(0, 0), (lx / uv_m, 0), (lx / uv_m, ly / uv_m), (0, ly / uv_m)]
        for x, y in corners:
            lines.append(f"v {x:.3f} {y:.3f} 0")
        for u, v in uvs:
            lines.append(f"vt {u:.4f} {v:.4f}")
        lines.append("vn 0 0 1")
        n = vi // 4 + 1
        lines.append(f"f {vi}/{vi}/{n} {vi + 1}/{vi + 1}/{n} {vi + 2}/{vi + 2}/{n} {vi + 3}/{vi + 3}/{n}")
        vi += 4
    path.write_text("\n".join(lines) + "\n")


def write_mtl(path: Path, materials: dict[str, str]) -> None:
    out = []
    for name, tex in materials.items():
        out += [
            f"newmtl {name}",
            "Ka 1 1 1",
            "Kd 1 1 1",
            "Ks 0 0 0",
            "d 1",
            f"map_Kd {tex}",
            "",
        ]
    path.write_text("\n".join(out))


def build_field(field: dict) -> None:
    media = GEN / "field" / "meshes"
    media.mkdir(parents=True, exist_ok=True)
    tints = [(70, 120, 45), (85, 125, 50), (95, 120, 55), (65, 105, 45)]
    mats = {}
    for i, t in enumerate(tints):
        grass_texture(100 + i, t).save(media / f"grass{i}.png")
        mats[f"grass{i}"] = f"grass{i}.png"
    asphalt_texture(7).save(media / "asphalt.png")
    dirt_texture(9).save(media / "dirt.png")
    mats["asphalt"] = "asphalt.png"
    mats["dirt"] = "dirt.png"
    write_mtl(media / "field.mtl", mats)

    half, tile = field["half_size_m"], 50.0
    rng = np.random.default_rng(field["seed"])
    quads: list[tuple[list[tuple[float, float]], str, float]] = []
    edges = np.arange(-half, half, tile)
    for x in edges:
        for y in edges:
            m = f"grass{int(rng.integers(0, len(tints)))}"
            quads.append(([(x, y), (x + tile, y), (x + tile, y + tile), (x, y + tile)], m, 10.0))
    write_quad_obj(media / "ground.obj", quads, "field.mtl")

    road_quads: list[tuple[list[tuple[float, float]], str, float]] = []
    for r in field["roads"]:
        (x0, y0), (x1, y1), w = r["a"], r["b"], r["width_m"]
        d = np.array([x1 - x0, y1 - y0], float)
        d /= np.linalg.norm(d)
        nrm = np.array([-d[1], d[0]]) * w / 2
        a, b = np.array([x0, y0]), np.array([x1, y1])
        # first edge across the road so the texture's u axis (with the lane line) spans it
        corners = [tuple(a - nrm), tuple(a + nrm), tuple(b + nrm), tuple(b - nrm)]
        road_quads.append(([(float(p[0]), float(p[1])) for p in corners], r["material"], w))
    write_quad_obj(media / "roads.obj", road_quads, "field.mtl")


def derive_models(apg: Path) -> None:
    src_models = apg / "models"
    gim_dst = GEN / "models" / "nadir_gimbal"
    if gim_dst.exists():
        shutil.rmtree(gim_dst)
    shutil.copytree(src_models / "gimbal_small_3d", gim_dst)
    sdf = (gim_dst / "model.sdf").read_text()
    sdf = sdf.replace('<model name="gimbal_small_3d">', '<model name="nadir_gimbal">')
    # keep the zoom plugin (real search drones carry zoom cameras); faster slew, 6x optical
    # relative to our 1.2 rad base FOV (the plugin measures zoom against a fixed 2.0 rad)
    sdf = re.sub(r"<max_zoom>.*?</max_zoom>", "<max_zoom>10.0</max_zoom>", sdf)
    sdf = re.sub(r"<slew_rate>.*?</slew_rate>", "<slew_rate>3.0</slew_rate>", sdf)
    sdf = re.sub(r"<plugin name=\"GstCameraPlugin\".*?</plugin>", "", sdf, flags=re.S)
    sdf = sdf.replace("<horizontal_fov>2.0</horizontal_fov>", f"<horizontal_fov>{CAMERA['hfov_rad']}</horizontal_fov>")
    sdf = sdf.replace("<width>640</width>", f"<width>{CAMERA['width']}</width>")
    sdf = sdf.replace("<height>480</height>", f"<height>{CAMERA['height']}</height>")
    sdf = sdf.replace("<update_rate>10</update_rate>", f"<update_rate>{CAMERA['rate_hz']}</update_rate>")
    sdf = sdf.replace("<visualize>1</visualize>", "<visualize>0</visualize><topic>/search_drone/camera</topic>")
    (gim_dst / "model.sdf").write_text(sdf)
    (gim_dst / "model.config").write_text(
        (gim_dst / "model.config").read_text().replace("Gimbal Small 3D", "nadir_gimbal")
    )

    # airframe copy whose links take part in gz-sim's WindEffects (link-level flag)
    frame_dst = GEN / "models" / "iris_windy"
    if frame_dst.exists():
        shutil.rmtree(frame_dst)
    shutil.copytree(src_models / "iris_with_standoffs", frame_dst)
    f = (frame_dst / "model.sdf").read_text()
    f = re.sub(r"""(<link name=['"]base_link['"]>)""", r"\1\n      <enable_wind>true</enable_wind>", f, count=1)
    f = f.replace("model://iris_with_standoffs/", "model://iris_windy/")
    (frame_dst / "model.sdf").write_text(f)
    cfg_f = frame_dst / "model.config"
    cfg_f.write_text(re.sub(r"<name>.*?</name>", "<name>iris_windy</name>", cfg_f.read_text(), count=1))

    drone_dst = GEN / "models" / "search_drone"
    if drone_dst.exists():
        shutil.rmtree(drone_dst)
    shutil.copytree(src_models / "iris_with_gimbal", drone_dst)
    d = (drone_dst / "model.sdf").read_text()
    d = d.replace('<model name="iris_with_gimbal">', '<model name="search_drone">')
    d = d.replace("<uri>model://gimbal_small_3d</uri>", "<uri>model://nadir_gimbal</uri>")
    d = d.replace("<uri>model://iris_with_standoffs</uri>", "<uri>model://iris_windy</uri>")
    # let gz-sim's WindEffects push the airframe (model-level flag covers nested links)
    d = d.replace('<model name="search_drone">', '<model name="search_drone">\n    <enable_wind>true</enable_wind>', 1)
    (drone_dst / "model.sdf").write_text(d)
    cfg = drone_dst / "model.config"
    cfg.write_text(re.sub(r"<name>.*?</name>", "<name>search_drone</name>", cfg.read_text(), count=1))


# Fuel models we use, localised to model://<slug> so worlds never hit the network and so we
# can fix asset bugs (e.g. "Hatchback blue" ships an .mtl that points at the white texture).
FUEL_MODELS = {
    "red_backpack": ("OpenRobotics", "JanSport Backpack Red"),
    "red_backpack_2": ("OpenRobotics", "Backpack"),
    "blue_backpack": ("GoogleResearch", "Jansport_School_Backpack_Blue_Streak"),
    "blue_car": ("OpenRobotics", "Hatchback blue"),
    "red_car": ("OpenRobotics", "Hatchback red"),
    "white_car": ("OpenRobotics", "Hatchback"),
    "suv": ("OpenRobotics", "SUV"),
    "pickup": ("OpenRobotics", "Pickup"),
    "person_standing": ("OpenRobotics", "Standing person"),
    "person_visitor": ("OpenRobotics", "Male visitor"),
    "person_casual": ("OpenRobotics", "Casual female"),
    "cardboard_box": ("OpenRobotics", "Cardboard box"),
    "suitcase": ("OpenRobotics", "Suitcase1"),
    "grey_box": ("OpenRobotics", "Large Grey Box"),
    "postbox": ("OpenRobotics", "Postbox"),
    "oak_tree": ("OpenRobotics", "Oak tree"),
    "pine_tree": ("OpenRobotics", "Pine Tree"),
    "house_1": ("OpenRobotics", "House 1"),
    "house_2": ("OpenRobotics", "House 2"),
    "house_3": ("OpenRobotics", "House 3"),
}
FUEL_CACHE = Path.home() / ".gz" / "fuel" / "fuel.gazebosim.org"


def _fuel_dir(owner: str, name: str) -> Path | None:
    root = FUEL_CACHE / owner.lower() / "models"
    # gz caches some models under the raw name and some URL-encoded, depending on version
    base = next((b for b in (root / name.lower(), root / name.lower().replace(" ", "%20")) if b.exists()), None)
    if base is None:
        return None
    versions = sorted((d for d in base.iterdir() if d.name.isdigit()), key=lambda d: int(d.name))
    return versions[-1] if versions else None


def _add_pbr(sdf: str, model_dir: Path, slug: str) -> str:
    """ogre2 ignores OGRE-1 material scripts (houses render black); add a PBR albedo map."""
    diffuse = sorted((model_dir / "materials" / "textures").glob("*Diffuse*.png"))
    if not diffuse:
        return sdf
    pbr = (
        "<ambient>0.8 0.8 0.8 1</ambient><diffuse>1 1 1 1</diffuse>"
        f"<pbr><metal><albedo_map>model://{slug}/materials/textures/{diffuse[0].name}"
        "</albedo_map></metal></pbr>"
    )
    return re.sub(r"<script>.*?</script>", pbr, sdf, flags=re.S)


def localise_fuel_models() -> None:
    import subprocess

    for slug, (owner, name) in FUEL_MODELS.items():
        src = _fuel_dir(owner, name)
        if src is None:
            url = f"https://fuel.gazebosim.org/1.0/{owner}/models/{name.replace(' ', '%20')}"
            subprocess.run(["gz", "fuel", "download", "-u", url], check=True, timeout=600)
            src = _fuel_dir(owner, name)
            if src is None:
                raise RuntimeError(f"fuel download of {owner}/{name} did not land in {FUEL_CACHE}")
        dst = GEN / "models" / slug
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        prefix = re.compile(r"https://fuel\.gazebosim\.org/1\.0/[^/]+/models/[^/]+/(?:tip|\d+)/files/", re.I)
        for f in dst.rglob("*"):
            if f.suffix.lower() in (".sdf", ".config", ".mtl", ".dae"):
                txt = f.read_text(errors="ignore")
                if f.suffix.lower() == ".mtl":
                    # textures relative to the mesh, and always this model's own copy
                    txt = re.sub(r"(map_\w+\s+)\S*/materials/textures/", r"\1../materials/textures/", txt)
                txt = prefix.sub(f"model://{slug}/", txt)
                if f.suffix.lower() == ".sdf" and "<pbr>" not in txt:
                    txt = _add_pbr(txt, dst, slug)
                if f.name == "model.config":
                    txt = re.sub(r"<name>.*?</name>", f"<name>{slug}</name>", txt, count=1)
                f.write_text(txt)


def fix_texture_refs() -> None:
    """Point every .mtl texture at a file that exists, borrowing from sibling models.

    Several Fuel meshes reference textures by bare name or via another model's URL
    (the hatchbacks share wheels3.png), which only works when the network is up.
    """
    models = GEN / "models"
    index: dict[str, Path] = {}
    for f in models.rglob("*.png"):
        index.setdefault(f.name, f)
    for mtl in models.rglob("*.mtl"):
        lines = []
        for line in mtl.read_text(errors="ignore").splitlines():
            m = re.match(r"(\s*map_\w+\s+)(\S+)\s*$", line)
            if m and not (mtl.parent / m.group(2)).exists():
                name = Path(m.group(2)).name
                own = next(mtl.parents[1].rglob(name), None)
                src = own or index.get(name)
                if src is not None:
                    if own is None:  # copy a borrowed texture into this model
                        dst = mtl.parent / name
                        shutil.copy(src, dst)
                        src = dst
                    line = m.group(1) + Path(os.path.relpath(src, mtl.parent)).as_posix()
            lines.append(line)
        mtl.write_text("\n".join(lines) + "\n")


def uniquify_materials() -> None:
    """Make every material and texture name unique per model.

    Ogre caches materials and textures by *name*. The three Fuel hatchbacks all define a
    material "Hatchback" with texture "hatchback.png", so in a scene with several of them
    every car rendered with whichever loaded first: the white "distractor" was a second blue
    car (found when an agent reported it, run hard-3005). Prefix names with the model slug.
    """
    for model in (GEN / "models").iterdir():
        slug = model.name
        for mtl in model.rglob("*.mtl"):
            txt = mtl.read_text(errors="ignore")
            names = re.findall(r"^\s*newmtl\s+(\S+)", txt, flags=re.M)
            for n in names:
                if n.startswith(f"{slug}__"):
                    continue
                txt = re.sub(rf"^(\s*newmtl\s+){re.escape(n)}\s*$", rf"\g<1>{slug}__{n}", txt, flags=re.M)
                for obj in mtl.parent.glob("*.obj"):
                    o = obj.read_text(errors="ignore")
                    o = re.sub(rf"^(usemtl\s+){re.escape(n)}\s*$", rf"\g<1>{slug}__{n}", o, flags=re.M)
                    obj.write_text(o)
            lines = []
            for line in txt.splitlines():
                m = re.match(r"(\s*map_\w+\s+)(\S+)\s*$", line)
                if m:
                    src = (mtl.parent / m.group(2)).resolve()
                    if src.exists() and not src.name.startswith(f"{slug}__"):
                        dst = src.with_name(f"{slug}__{src.name}")
                        if not dst.exists():
                            shutil.copy(src, dst)
                        line = m.group(1) + os.path.relpath(dst, mtl.parent)
                lines.append(line)
            mtl.write_text("\n".join(lines) + "\n")


def main() -> None:
    import json

    p = argparse.ArgumentParser()
    p.add_argument("--ardupilot-gazebo", default="/opt/sim/ardupilot_gazebo", type=Path)
    a = p.parse_args()
    field = json.loads((HERE / "field.json").read_text())
    build_field(field)
    derive_models(a.ardupilot_gazebo)
    localise_fuel_models()
    fix_texture_refs()
    uniquify_materials()
    (GEN / "camera.json").write_text(json.dumps(CAMERA, indent=2))
    print(f"assets written to {GEN}")


if __name__ == "__main__":
    main()
