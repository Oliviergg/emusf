"""Configuration centralisée pour emusf.

Les valeurs sont résolues dans cet ordre :
1. variables d'environnement (EMUSF_DSN, EMUSF_SFDX_OBJECTS, EMUSF_SF_CLASSES)
2. fichier .env à la racine du repo (gitignoré — copier .env.example)
3. défauts ci-dessous (sans secret)
"""

import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(path=os.path.join(_REPO_ROOT, ".env")) -> dict:
    """Mini-parseur .env (KEY=VALUE, commentaires #, quotes optionnelles)."""
    values = {}
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
    return values


_dotenv = _load_dotenv()


def _get(name: str, default: str) -> str:
    return os.environ.get(name) or _dotenv.get(name) or default


DSN = _get("EMUSF_DSN",
           "host=127.0.0.1 port=6002 user=postgres dbname=biup")
SFDX_OBJECTS = _get("EMUSF_SFDX_OBJECTS",
                    "/Users/olivier/Dev/btp/sf-btp/force-app/main/default/objects")
SF_CLASSES = _get("EMUSF_SF_CLASSES",
                  "/Users/olivier/Dev/btp/sf-btp/force-app/main/default/classes")
