"""Downloads the CC0 assets of the desk scene from Poly Haven (polyhaven.com) into source/assets/, once.

    python3 case/fetch_assets.py          (run by `make renders`; files already there are not downloaded again)

  * oak_veneer_01    - wood texture of the desk (2k: colour, roughness, normal)
  * potted_plant_04  - a succulent in a pot (glTF, 2k textures)
Everything on Poly Haven is CC0 (public domain): https://polyhaven.com/license
"""
import json
import urllib.request
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "polyhaven"
API = "https://api.polyhaven.com/files/"
TEXTURES = {"oak_veneer_01": ("Diffuse", "Rough", "nor_gl")}
MODELS = {"potted_plant_04": "2k"}


def get(url, dst):
    if dst.exists() and dst.stat().st_size:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "lira-render"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    dst.write_bytes(data)
    print("downloaded", dst.relative_to(ASSETS.parent.parent), "%.1f MB" % (len(data) / 1e6))


def files(asset):
    with urllib.request.urlopen(urllib.request.Request(API + asset, headers={"User-Agent": "lira-render"}),
                                timeout=60) as r:
        return json.load(r)


def main():
    for asset, maps in TEXTURES.items():
        if all((ASSETS / asset / ("%s_2k.jpg" % m)).exists() for m in maps):
            continue
        f = files(asset)
        for m in maps:
            get(f[m]["2k"]["jpg"]["url"], ASSETS / asset / ("%s_2k.jpg" % m))
    for asset, res in MODELS.items():
        gltf = ASSETS / asset / ("%s.gltf" % asset)
        if gltf.exists():
            continue
        g = files(asset)["gltf"][res]["gltf"]
        for rel, inc in g.get("include", {}).items():
            get(inc["url"], ASSETS / asset / rel)
        get(g["url"], gltf)
    (ASSETS / "LICENSE.txt").write_text("Assets from Poly Haven (https://polyhaven.com), CC0 1.0 (public domain): "
                                        + ", ".join(list(TEXTURES) + list(MODELS)) + "\n")


if __name__ == "__main__":
    main()
