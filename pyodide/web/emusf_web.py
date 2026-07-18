"""Bootstrap EMUSF pour le navigateur (Pyodide).

Chargé par index.html après décompression du bundle. Reproduit le REPL de
run.py : SOQL direct, snippets Apex, commandes /vars /ast /clear, exécution
d'une méthode statique d'un fichier .cls du bundle.

L'org est un PgTestOrg ordinaire — psycopg2 est fourni par le shim SQLite
(pyodide/shim/psycopg2), la base vit en mémoire dans l'onglet.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import traceback
from contextlib import redirect_stdout

from emusf import PgTestOrg, ApexParser, ApexInterpreter
from emusf.ast_printer import print_ast
from emusf.trigger_parser import load_trigger

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

org = None
parser = None
interpreter = None
show_ast = False


def _seed_demo(o):
    """Tables et données de démo — mêmes valeurs que run.py."""
    o.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0",
                                 "Famille_de_compte__c": "TEXT"})
    o.create_sobject("Contact", {"LastName": "TEXT", "AccountId": "TEXT"})
    o.register_relationship("Contacts", "Contact", "AccountId", "Account")
    o.insert("Account", [
        {"Id": "001001", "Name": "Acme", "Active__c": 1,
         "Famille_de_compte__c": "Client"},
        {"Id": "001002", "Name": "Boring Corp", "Active__c": 0,
         "Famille_de_compte__c": "Prospect"},
    ])
    o.insert("Contact", [
        {"Id": "003001", "LastName": "Dupont", "AccountId": "001001"},
        {"Id": "003002", "LastName": "Martin", "AccountId": "001001"},
    ])


def init(seed: bool = True, triggers: bool = True) -> str:
    """Crée l'org bac à sable en mémoire ; retourne la bannière du REPL."""
    global org, parser, interpreter
    org = PgTestOrg("pyodide-in-memory", schema="test")
    if seed:
        _seed_demo(org)
    loaded_triggers = []
    if triggers:
        for trigger_file in sorted(glob.glob(os.path.join(_APP_DIR, "apex",
                                                          "*.trigger"))):
            load_trigger(org, trigger_file)
            loaded_triggers.append(
                os.path.basename(trigger_file).replace(".trigger", ""))
    parser = ApexParser()
    interpreter = ApexInterpreter(org)

    lines = ["org test (DML + triggers) — SQLite en mémoire, tout reste dans "
             "votre navigateur"]
    if seed:
        lines.append("Données de démo : 2 Accounts, 2 Contacts")
    if loaded_triggers:
        lines.append("Triggers chargés : " + ", ".join(loaded_triggers))
    return "\n".join(lines)


def list_demo_classes() -> list:
    """Fichiers .cls du bundle, pour le sélecteur d'exemples."""
    return sorted(os.path.basename(p)
                  for p in glob.glob(os.path.join(_APP_DIR, "apex", "*.cls")))


# --- Explorateur / éditeur de fichiers ---

def _safe_path(rel: str) -> str:
    """Résout un chemin relatif au bundle, en refusant d'en sortir."""
    path = os.path.realpath(os.path.join(_APP_DIR, rel))
    if not path.startswith(os.path.realpath(_APP_DIR) + os.sep):
        raise ValueError("chemin hors du bundle: {}".format(rel))
    return path


def list_tree() -> str:
    """Arborescence du bundle (JSON) : classes apex/ et scénarios."""
    tree = {"apex": [], "scenarios": {}}
    for path in sorted(glob.glob(os.path.join(_APP_DIR, "apex", "*"))):
        if os.path.isfile(path):
            tree["apex"].append("apex/" + os.path.basename(path))
    scen_root = os.path.join(_APP_DIR, "scenarios")
    if os.path.isdir(scen_root):
        for name in sorted(os.listdir(scen_root)):
            d = os.path.join(scen_root, name)
            if os.path.isdir(d):
                tree["scenarios"][name] = sorted(
                    "scenarios/{}/{}".format(name, f)
                    for f in os.listdir(d)
                    if os.path.isfile(os.path.join(d, f))
                    and not f.startswith("."))
    return json.dumps(tree)


_KIND_LABELS = [
    ("Main.cls", "Point d'entrée — Main.run()"),
    (".trigger", "Trigger"),
    (".flow-meta.xml", "Flow"),
    (".cls", "Classe Apex"),
    (".md", "Documentation"),
]


def scenario_info(name: str) -> str:
    """Fiche de présentation d'un scénario (JSON) : description (README.md)
    et fichiers avec leur rôle."""
    scenario_dir = _safe_path(os.path.join("scenarios", os.path.basename(name)))
    description = ""
    readme = os.path.join(scenario_dir, "README.md")
    if os.path.isfile(readme):
        with open(readme) as f:
            description = f.read().strip()
    files = []
    for fname in sorted(os.listdir(scenario_dir)):
        path = os.path.join(scenario_dir, fname)
        if not os.path.isfile(path) or fname.startswith("."):
            continue
        kind = "Fichier"
        for suffix, label in _KIND_LABELS:
            if fname == suffix or fname.endswith(suffix):
                kind = label
                break
        files.append({"path": "scenarios/{}/{}".format(name, fname),
                      "name": fname, "kind": kind})
    # Point d'entrée en premier, doc en dernier
    files.sort(key=lambda f: (f["kind"] == "Documentation",
                              f["name"] != "Main.cls", f["name"]))
    return json.dumps({"name": name, "description": description,
                       "files": files})


def read_file(rel: str) -> str:
    with open(_safe_path(rel)) as f:
        return f.read()


def write_file(rel: str, content: str) -> str:
    """Sauvegarde une modification. Un .trigger d'apex/ est rechargé dans
    l'org du REPL ; les .cls sont relus du disque à chaque exécution."""
    path = _safe_path(rel)
    with open(path, "w") as f:
        f.write(content)
    if rel.startswith("apex/") and rel.endswith(".trigger"):
        return reload_triggers()
    return "Sauvegardé : {}".format(rel)


def reload_triggers() -> str:
    """Reconstruit le registre de triggers de l'org REPL depuis apex/."""
    org._triggers = {}
    names, errors = [], []
    buf = io.StringIO()
    for trigger_file in sorted(glob.glob(os.path.join(_APP_DIR, "apex",
                                                      "*.trigger"))):
        try:
            with redirect_stdout(buf):
                load_trigger(org, trigger_file)
            names.append(os.path.basename(trigger_file).replace(".trigger", ""))
        except Exception as e:
            errors.append("{} : {}".format(os.path.basename(trigger_file),
                                           _format_error(e)))
    out = "Triggers rechargés : {}".format(", ".join(names) or "(aucun)")
    if errors:
        out += "\nERREUR: " + "\n".join(errors)
    return out


def run_scenario(name: str, entry: str = "Main.cls", method: str = "run") -> str:
    """Exécute un scénario du bundle (org bac à sable dédiée, comme run.py).

    Nécessite les packages pyyaml/requests (chargés par la page avant le
    premier appel — emusf.callout les importe au niveau module).
    """
    scenario_dir = _safe_path(os.path.join("scenarios", os.path.basename(name)))
    if not os.path.isdir(scenario_dir):
        return "Erreur: scénario '{}' introuvable".format(name)
    from emusf.scenario_runner import load_scenario
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            ok = load_scenario(scenario_dir, entry, method)
    except SystemExit:
        ok = False
    except Exception as e:
        return _ANSI.sub("", buf.getvalue()) + "\nERREUR: " + _format_error(e)
    out = _ANSI.sub("", buf.getvalue()).rstrip("\n")
    return out + ("\n\nScénario OK" if ok else "\n\nScénario en ÉCHEC")


def run_class(name: str, method: str = "run") -> str:
    """Exécute une méthode statique d'un .cls du bundle (comme run.py).

    name : chemin relatif au bundle ('apex/AccountDemo.cls') ou simple nom de
    fichier (cherché dans apex/). Le fichier est relu du disque à chaque
    appel — les modifications sauvegardées dans l'éditeur sont prises en compte.
    """
    rel = name if "/" in name else "apex/" + os.path.basename(name)
    path = _safe_path(rel)
    if not os.path.isfile(path):
        return "Erreur: '{}' introuvable".format(name)
    with open(path) as f:
        source = f.read()
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            ast = parser.parse_class(source, method)
            if show_ast:
                print_ast(ast)
            ApexInterpreter(org)._exec_block(ast)
    except Exception as e:
        return buf.getvalue() + "ERREUR: {}".format(_format_error(e))
    return buf.getvalue() or "(exécuté — aucune sortie)"


def _format_error(e: Exception) -> str:
    msg = str(e)
    return "{}: {}".format(type(e).__name__, msg) if msg else type(e).__name__


def _format_soql_result(results: list) -> str:
    if not results:
        return "(0 résultats)"
    keys = [k for k in results[0].keys() if not k.startswith("_")]
    if not keys:  # COUNT() → liste de N dicts vides (convention PgOrg)
        return "COUNT() = {}".format(len(results))
    widths = {k: len(str(k)) for k in keys}
    str_rows = []
    for row in results:
        str_row = {}
        for k in keys:
            v = row.get(k, "")
            s = "" if v is None else str(v)
            str_row[k] = s
            widths[k] = max(widths[k], len(s))
        str_rows.append(str_row)
    out = [" | ".join(str(k).ljust(widths[k]) for k in keys),
           "-+-".join("-" * widths[k] for k in keys)]
    for r in str_rows:
        out.append(" | ".join(r[k].ljust(widths[k]) for k in keys))
    out.append("({} résultat{})".format(len(results),
                                        "s" if len(results) > 1 else ""))
    return "\n".join(out)


def run_line(line: str) -> str:
    """Exécute une entrée REPL, retourne la sortie texte."""
    global show_ast
    line = (line or "").strip()
    if not line:
        return ""

    if line == "/ast":
        show_ast = not show_ast
        return "AST: " + ("ON" if show_ast else "OFF")
    if line == "/vars":
        if not interpreter.variables:
            return "(aucune variable)"
        out = []
        for k, v in interpreter.variables.items():
            val_str = str(v)
            if len(val_str) > 120:
                val_str = val_str[:120] + "..."
            out.append("  {} = {}".format(k, val_str))
        return "\n".join(out)
    if line == "/clear":
        interpreter.variables.clear()
        return "Variables effacées"
    if line == "/help":
        return ("SOQL   → SELECT Id, Name FROM Account LIMIT 5\n"
                "Apex   → String x = 'hello'; System.debug(x);\n"
                "/ast   → afficher l'AST avant exécution\n"
                "/vars  → afficher les variables\n"
                "/clear → réinitialiser les variables\n"
                "/help  → cette aide")

    # SOQL direct
    if line.upper().startswith("SELECT"):
        try:
            results = org.execute_soql("[" + line.rstrip(";") + "]",
                                       context=interpreter.variables)
            return _format_soql_result(results)
        except Exception as e:
            return "ERREUR SOQL: {}".format(_format_error(e))

    # Apex — wrapper dans une classe (comme le REPL de run.py)
    apex_source = ("public class REPL {{ public static void run() {{ {} }} }}"
                   .format(line))
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            ast = parser.parse_class(apex_source, "run")
            if show_ast:
                print_ast(ast)
            interpreter._exec_block(ast)
    except Exception as e:
        return buf.getvalue() + "ERREUR: {}".format(_format_error(e))
    return buf.getvalue().rstrip("\n")


def reset() -> str:
    """Réinitialise l'org et les variables (nouvelle base en mémoire)."""
    if org is not None:
        try:
            org.conn.close()
        except Exception:
            pass
    return init()


def _self_test() -> str:  # utilisé par les tests Node/Playwright
    out = []
    out.append(run_line("SELECT Id, Name FROM Account"))
    out.append(run_line("List<Account> accs = [SELECT Id, Name FROM Account];"
                        " System.debug(accs.size());"))
    out.append(run_line("insert new Account(Name='Pyodide Corp');"))
    out.append(run_line("SELECT COUNT() FROM Account"))
    return "\n---\n".join(out)
