"""Extrait le référentiel du jeu (prix de base, quartiers, bâtiments, types de commerce, ...).

    .venv/Scripts/python extract_gamedata.py              # dossier du jeu détecté via Steam
    .venv/Scripts/python extract_gamedata.py --game "E:/Games/Steam/steamapps/common/Big Ambitions"

Produit out/gamedata/ :
    <bundle>.json   tous les ScriptableObjects (MonoBehaviour) du bundle Addressables
    locale_en.json  textes anglais du jeu (noms affichés + encyclopédie)
    version.json    version du jeu au moment de l'extraction (à refaire après chaque mise à jour)

Nécessite UnityPy (requirements.txt).
"""

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import UnityPy

BUNDLES = [
    "items", "businesstypes", "businessrequirements", "neighborhoods", "buildings", "buildingsizes",
    "buildingtypes", "aibusinessdefaults", "rivals", "skills", "jobdemands", "vehicletypes",
    "personalgoals", "seasons", "contactpresets",
    "factories/recipes",  # sous-dossier : defaultlocalgroup_assets_factories/recipes_*.bundle
]
STEAM_LIBRARIES = [Path("C:/Program Files (x86)/Steam"), Path("E:/SteamLibrary"), Path("E:/Games/Steam"), Path("D:/SteamLibrary")]
# Références Unity internes sans intérêt pour l'analyse.
DROPPED_KEYS = {"m_GameObject", "m_Script", "m_Enabled"}


def find_game() -> Path:
    for library in STEAM_LIBRARIES:
        path = library / "steamapps/common/Big Ambitions"
        if (path / "Big Ambitions_Data").exists():
            return path
    raise SystemExit("Big Ambitions introuvable, utiliser --game")


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in DROPPED_KEYS}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


def extract_bundle(path: Path) -> list[dict]:
    rows = []
    for obj in UnityPy.load(str(path)).objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
            script = obj.read().m_Script.read().m_ClassName
        except Exception:
            continue
        # $pathId : identifiant Unity de l'objet, cible des références {m_FileID, m_PathID} des autres objets.
        rows.append({"$script": script, "$pathId": obj.path_id, **_clean(tree)})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("out/gamedata"))
    args = parser.parse_args()

    game = args.game or find_game()
    data = game / "Big Ambitions_Data"
    aa = data / "StreamingAssets/aa/StandaloneWindows64"
    args.output.mkdir(parents=True, exist_ok=True)

    for name in BUNDLES:
        matches = list(aa.glob(f"defaultlocalgroup_assets_{name}_*.bundle"))
        if not matches:
            print(f"  {name:22} introuvable")
            continue
        rows = extract_bundle(matches[0])
        (args.output / f"{name.replace('/', '_')}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {name:22} {len(rows):5} objets")

    shutil.copyfile(data / "StreamingAssets/locale/en.json", args.output / "locale_en.json")
    dll = data / "Managed/BigAmbitions.dll"
    version = {
        "extractedAt": datetime.now().isoformat(timespec="seconds"),
        "gamePath": str(game),
        "bigAmbitionsDllModified": datetime.fromtimestamp(dll.stat().st_mtime).isoformat(timespec="seconds"),
        "bundlesCatalog": re.sub(r"\s+", " ", (data / "StreamingAssets/aa/settings.json").read_text(encoding="utf-8"))[:200],
    }
    (args.output / "version.json").write_text(json.dumps(version, indent=2), encoding="utf-8")
    print(f"-> {args.output}")


if __name__ == "__main__":
    main()
