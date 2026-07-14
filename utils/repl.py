"""REPL Apex — exécute du SOQL et de l'Apex interactivement contre PostgreSQL."""

from __future__ import annotations

import os
import sys
import readline

# Permet `python utils/repl.py` depuis n'importe où (emusf est à la racine du repo)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emusf import ApexParser, ApexInterpreter
from emusf.pg_org import PgOrg
from emusf.sfdx_loader import configure_pg_org
from emusf.ast_printer import print_ast

# Couleurs
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

from emusf.config import DSN, SFDX_OBJECTS as SFDX_OBJECTS_DIR

# --- Setup ---
print(BOLD + "emusf REPL" + RESET + " — Émulateur Salesforce Apex/SOQL")
print(DIM + "Connexion PostgreSQL..." + RESET)

org = PgOrg(DSN, schema="data")

# Charger les métadonnées SFDX pour Account et Contact
print(DIM + "Chargement métadonnées SFDX..." + RESET)
configure_pg_org(org, SFDX_OBJECTS_DIR, ["Account", "Contact"])

parser = ApexParser()
interpreter = ApexInterpreter(org)

print()
print("Commandes :")
print("  " + GREEN + "SOQL" + RESET + "  → SELECT Id, Name FROM Account LIMIT 5")
print("  " + CYAN + "Apex" + RESET + "  → String x = 'hello'; System.debug(x);")
print("  " + YELLOW + "/ast" + RESET + "  → Afficher l'AST avant exécution")
print("  " + YELLOW + "/vars" + RESET + " → Afficher les variables")
print("  " + YELLOW + "/clear" + RESET + " → Reset les variables")
print("  " + RED + "/quit" + RESET + " → Quitter")
print()

show_ast = False


def execute_input(line: str):
    global show_ast

    line = line.strip()
    if not line:
        return

    # Commandes REPL
    if line == "/quit" or line == "/exit":
        print("Bye!")
        sys.exit(0)
    elif line == "/ast":
        show_ast = not show_ast
        print("AST: " + (GREEN + "ON" if show_ast else RED + "OFF") + RESET)
        return
    elif line == "/vars":
        for k, v in interpreter.variables.items():
            val_str = str(v)
            if len(val_str) > 80:
                val_str = val_str[:80] + "..."
            print("  {} = {}".format(k, val_str))
        if not interpreter.variables:
            print(DIM + "  (aucune variable)" + RESET)
        return
    elif line == "/clear":
        interpreter.variables.clear()
        print(DIM + "Variables effacées" + RESET)
        return

    # SOQL direct (commence par SELECT)
    if line.upper().startswith("SELECT"):
        try:
            results = org.execute_soql("[" + line + "]", context=interpreter.variables)
            if not results:
                print(DIM + "(0 résultats)" + RESET)
                return
            # Afficher comme tableau
            keys = [k for k in results[0].keys() if not k.startswith("_")]
            # Header
            print(DIM + " | ".join(str(k) for k in keys) + RESET)
            print(DIM + "-" * 80 + RESET)
            for row in results:
                vals = [str(row.get(k, "")) for k in keys]
                print(" | ".join(vals))
            print(DIM + "({} résultats)".format(len(results)) + RESET)
        except Exception as e:
            print(RED + "ERREUR SOQL: " + str(e) + RESET)
        return

    # Apex — wrapper dans une classe (parse_class passe par le frontend ANTLR)
    apex_source = "public class REPL {{ public static void run() {{ {} }} }}".format(line)
    try:
        ast = parser.parse_class(apex_source, "run")
        if show_ast:
            print_ast(ast)
        interpreter._exec_block(ast)
    except Exception as e:
        print(RED + "ERREUR: " + str(e) + RESET)


# --- Main loop ---
while True:
    try:
        line = input(CYAN + "apex> " + RESET)
        execute_input(line)
    except EOFError:
        print("\nBye!")
        break
    except KeyboardInterrupt:
        print()
        continue
