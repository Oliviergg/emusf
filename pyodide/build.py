"""Construit le site statique GitHub Pages (REPL EMUSF sous Pyodide).

Produit pyodide/dist/ :
    index.html          — la page (copiée de pyodide/web/)
    emusf_bundle.zip    — le paquet décompressé dans le FS Pyodide :
        emusf/          — le package emusf du repo
        psycopg2/       — le shim SQLite (pyodide/shim/)
        antlr4/         — runtime ANTLR (téléchargé depuis PyPI, pur Python)
        apex/           — classes et triggers de démo
        scenarios/      — scénarios autonomes (classes + triggers + flows)
        emusf_web.py    — bootstrap REPL appelé par index.html

Usage : python3 pyodide/build.py [--dist DIR]
Nécessite un accès réseau à PyPI (téléchargement de la wheel antlr4).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile

# Doit correspondre au générateur du parser vendoré (cf. pyproject.toml)
ANTLR_RUNTIME = "antlr4-python3-runtime==4.13.2"

# Scénarios autonomes (pas de dépendance au projet SFDX externe, au schéma
# data ni au réseau) — les autres ne peuvent pas tourner dans le navigateur
BUNDLED_SCENARIOS = ("account_insert", "account_trigger")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

EXCLUDE_PATTERNS = ("__pycache__", "*.pyc", ".DS_Store")


def _excluded(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_PATTERNS)


def _add_tree(zf: zipfile.ZipFile, src_dir: str, arc_prefix: str):
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if not _excluded(d)]
        for f in sorted(files):
            if _excluded(f):
                continue
            path = os.path.join(root, f)
            arcname = os.path.join(arc_prefix,
                                   os.path.relpath(path, src_dir))
            zf.write(path, arcname)


def _download_antlr_runtime(tmp: str) -> str:
    """Télécharge la wheel antlr4 et retourne le dossier extrait."""
    subprocess.run(
        [sys.executable, "-m", "pip", "download", ANTLR_RUNTIME,
         "--no-deps", "--only-binary", ":all:", "-d", tmp, "--quiet"],
        check=True)
    wheels = [f for f in os.listdir(tmp) if f.endswith(".whl")]
    if not wheels:
        raise SystemExit("wheel antlr4 introuvable après pip download")
    extract_dir = os.path.join(tmp, "antlr_extracted")
    with zipfile.ZipFile(os.path.join(tmp, wheels[0])) as whl:
        whl.extractall(extract_dir)
    pkg = os.path.join(extract_dir, "antlr4")
    if not os.path.isdir(pkg):
        raise SystemExit("package antlr4 absent de la wheel")
    return pkg


def build(dist: str):
    os.makedirs(dist, exist_ok=True)

    bundle_path = os.path.join(dist, "emusf_bundle.zip")
    with tempfile.TemporaryDirectory() as tmp:
        antlr_pkg = _download_antlr_runtime(tmp)
        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            _add_tree(zf, os.path.join(REPO, "emusf"), "emusf")
            _add_tree(zf, os.path.join(HERE, "shim", "psycopg2"), "psycopg2")
            _add_tree(zf, antlr_pkg, "antlr4")
            _add_tree(zf, os.path.join(REPO, "apex"), "apex")
            for scenario in BUNDLED_SCENARIOS:
                _add_tree(zf, os.path.join(REPO, "scenarios", scenario),
                          os.path.join("scenarios", scenario))
            zf.write(os.path.join(HERE, "web", "emusf_web.py"), "emusf_web.py")

    # Cache-busting : l'URL du bundle porte le hash de son contenu, injecté
    # dans la page — sinon un navigateur peut combiner un index.html neuf
    # avec un bundle en cache (GitHub Pages: max-age=600) et planter au boot
    with open(bundle_path, "rb") as f:
        build_id = hashlib.sha256(f.read()).hexdigest()[:12]
    with open(os.path.join(HERE, "web", "index.html")) as f:
        html = f.read()
    html = html.replace("__EMUSF_BUILD__", build_id)
    with open(os.path.join(dist, "index.html"), "w") as f:
        f.write(html)

    size_mb = os.path.getsize(bundle_path) / 1e6
    print("OK  {}  ({:.1f} Mo)".format(bundle_path, size_mb))
    print("OK  {}  (build {})".format(os.path.join(dist, "index.html"),
                                      build_id))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", default=os.path.join(HERE, "dist"),
                    help="répertoire de sortie (défaut: pyodide/dist)")
    args = ap.parse_args()
    build(args.dist)
