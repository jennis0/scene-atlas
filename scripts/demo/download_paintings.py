"""Download CC0 paintings from the Cleveland Museum of Art for the demo library's scenes.

Each work's licence is checked against the museum's open-access API before it is saved,
and its title, artist and page are written to credits.json.

Usage:
    uv run python -m scripts.demo.download_paintings <out dir>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

API = "https://openaccess-api.clevelandart.org/api/artworks/"
HEADERS = {"User-Agent": "SceneAtlas-demo/1.0 (+https://github.com/jennis0/scene-atlas)"}

# Cleveland Museum of Art object ids, picked for fantasy-looking scenes and character portraits
PICKS = {
    "scenes": [
        150353,  # John Martin, Ruins of an Ancient City
        95263,  # J. M. W. Turner, Queen Mab's Cave
        149665,  # Arnold Böcklin, Ruin by the Sea
        135483,  # Salvator Rosa, Ruins in a Rocky Landscape
        141639,  # Frederic Edwin Church, Twilight in the Wilderness
        144732,  # Frederic Edwin Church, Storm in the Mountains
        127224,  # Albert Bierstadt, Mount Vesuvius at Midnight
        150968,  # Albert Bierstadt, Fir Trees and Storm Clouds
        172815,  # Albert Bierstadt, Mount Starr King, Yosemite
        125058,  # Jasper F. Cropsey, The Clove
        168352,  # Adrien Dauzats, Ruined Church
        147464,  # Salomon van Ruysdael, Castle on a River
        359246,  # J. C. Dahl, Feige Waterfall
    ],
    "portraits": [
        97168,  # Portrait of Roberto Castiglione
        149423,  # William Beechey, Portrait of a Man
        150053,  # Jean-Léon Gérôme, Head of an Italian Woman
        163044,  # Charles Meynier, Clio, Muse of History
    ],
}


def main() -> None:
    out = Path(sys.argv[1])
    credits = []
    with httpx.Client(headers=HEADERS, timeout=120, follow_redirects=True) as client:
        for kind, ids in PICKS.items():
            (out / kind).mkdir(parents=True, exist_ok=True)
            for object_id in ids:
                res = client.get(f"{API}{object_id}")
                res.raise_for_status()
                work = res.json()["data"]
                if work.get("share_license_status") != "CC0":
                    print(f"Skipping {object_id}: not CC0")
                    continue
                artist = (work.get("creators") or [{}])[0].get("description", "Unknown artist")
                dest = out / kind / (re.sub(r"[^\w\- ]+", "", work["title"])[:60].strip() + ".jpg")
                image = client.get(work["images"]["web"]["url"])
                image.raise_for_status()
                dest.write_bytes(image.content)
                credits.append(
                    {
                        "file": f"{kind}/{dest.name}",
                        "title": work["title"],
                        "artist": artist,
                        "licence": "CC0",
                        "page": work["url"],
                    }
                )
                print(f"{kind}/{dest.name}")
    (out / "credits.json").write_text(json.dumps(credits, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
