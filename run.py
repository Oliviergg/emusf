"""Point d'entrée unifié d'EMUSF — REPL, classe Apex ou scénario.

Le mode dépend de la cible :
    python3 run.py                                REPL interactif (bac à sable)
    python3 run.py --org data                     REPL sur les données exportées
    python3 run.py apex/Demo.cls [méthode]        exécute une méthode statique
    python3 run.py scenarios/account_trigger      exécute un scénario complet

Orgs :
    --org test (défaut) : bac à sable PostgreSQL (schéma test) — DML autorisé,
        données de démo (--no-seed pour désactiver), triggers d'apex/
        chargés (--no-triggers pour désactiver)
    --org data : données Salesforce exportées (schéma data) — lecture seule
"""

import argparse
import glob
import os
import sys

from emusf import PgTestOrg, ApexParser, ApexInterpreter
from emusf.config import DSN, SFDX_OBJECTS
from emusf.pg_org import PgOrg
from emusf.ast_printer import print_ast
from emusf.trigger_parser import load_trigger

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


# --------------------------------------------------------------------- #
# Orgs
# --------------------------------------------------------------------- #

def _seed_demo(org):
    """Tables et données de démo du bac à sable."""
    org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0",
                                   "Famille_de_compte__c": "TEXT"})
    org.create_sobject("Contact", {"LastName": "TEXT", "AccountId": "TEXT"})
    org.register_relationship("Contacts", "Contact", "AccountId", "Account")
    org.insert("Account", [
        {"Id": "001001", "Name": "Acme", "Active__c": 1, "Famille_de_compte__c": "Client"},
        {"Id": "001002", "Name": "Boring Corp", "Active__c": 0, "Famille_de_compte__c": "Prospect"},
    ])
    org.insert("Contact", [
        {"Id": "003001", "LastName": "Dupont", "AccountId": "001001"},
        {"Id": "003002", "LastName": "Martin", "AccountId": "001001"},
    ])


def make_org(kind: str, seed: bool = True, triggers: bool = True):
    """Construit l'org : bac à sable (test) ou données exportées (data)."""
    if kind == "data":
        org = PgOrg(DSN, schema="data")
        # Relations lookup pour les sous-requêtes SOQL, si le projet SFDX est là
        if os.path.isdir(SFDX_OBJECTS):
            from emusf.sfdx_loader import configure_pg_org
            try:
                configure_pg_org(org, SFDX_OBJECTS, ["Account", "Contact"])
            except Exception:
                pass
        return org

    org = PgTestOrg(DSN, schema="test")
    org.truncate_all()
    if seed:
        _seed_demo(org)
    if triggers:
        repo_root = os.path.dirname(os.path.abspath(__file__))
        for trigger_file in sorted(glob.glob(os.path.join(repo_root, "apex", "*.trigger"))):
            load_trigger(org, trigger_file)
    return org


# --------------------------------------------------------------------- #
# Mode classe : exécute une méthode statique d'un fichier .cls
# --------------------------------------------------------------------- #

def run_class(path: str, method: str, org, show_ast: bool) -> None:
    with open(path) as f:
        source = f.read()

    print("\n{}=== Exécution: {} -> {}() ==={}\n".format(BOLD, path, method, RESET))
    ast = ApexParser().parse_class(source, method)
    if show_ast:
        print("--- AST ---")
        print_ast(ast)
        print()
    ApexInterpreter(org)._exec_block(ast)


# --------------------------------------------------------------------- #
# Mode REPL
# --------------------------------------------------------------------- #

def run_repl(org, show_ast: bool) -> None:
    import readline  # noqa: F401 — historique et édition de ligne

    parser = ApexParser()
    interpreter = ApexInterpreter(org)

    read_only = not isinstance(org, PgTestOrg)
    print(BOLD + "emusf REPL" + RESET + " — org {}{}".format(
        org.schema_name, " (lecture seule)" if read_only else " (DML + triggers)"))
    print("Commandes :")
    print("  " + GREEN + "SOQL" + RESET + "  → SELECT Id, Name FROM Account LIMIT 5")
    print("  " + CYAN + "Apex" + RESET + "  → String x = 'hello'; System.debug(x);")
    print("  " + YELLOW + "/ast" + RESET + "  → Afficher l'AST avant exécution")
    print("  " + YELLOW + "/vars" + RESET + " → Afficher les variables")
    print("  " + YELLOW + "/clear" + RESET + " → Reset les variables")
    print("  " + RED + "/quit" + RESET + " → Quitter")
    print()

    def execute_input(line: str):
        nonlocal show_ast
        line = line.strip()
        if not line:
            return
        if line in ("/quit", "/exit"):
            print("Bye!")
            sys.exit(0)
        if line == "/ast":
            show_ast = not show_ast
            print("AST: " + (GREEN + "ON" if show_ast else RED + "OFF") + RESET)
            return
        if line == "/vars":
            for k, v in interpreter.variables.items():
                val_str = str(v)
                if len(val_str) > 80:
                    val_str = val_str[:80] + "..."
                print("  {} = {}".format(k, val_str))
            if not interpreter.variables:
                print(DIM + "  (aucune variable)" + RESET)
            return
        if line == "/clear":
            interpreter.variables.clear()
            print(DIM + "Variables effacées" + RESET)
            return

        # SOQL direct
        if line.upper().startswith("SELECT"):
            try:
                results = org.execute_soql("[" + line + "]", context=interpreter.variables)
                if not results:
                    print(DIM + "(0 résultats)" + RESET)
                    return
                keys = [k for k in results[0].keys() if not k.startswith("_")]
                print(DIM + " | ".join(str(k) for k in keys) + RESET)
                print(DIM + "-" * 80 + RESET)
                for row in results:
                    print(" | ".join(str(row.get(k, "")) for k in keys))
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

    while True:
        try:
            execute_input(input(CYAN + "apex> " + RESET))
        except EOFError:
            print("\nBye!")
            break
        except KeyboardInterrupt:
            print()
            continue


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(
        description="EMUSF — exécute de l'Apex localement (REPL, classe ou scénario)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Le mode dépend de la cible :")[1],
    )
    ap.add_argument("cible", nargs="?",
                    help="fichier .cls, répertoire de scénario, ou rien pour le REPL")
    ap.add_argument("methode", nargs="?", default="run",
                    help="méthode statique à exécuter (défaut: run)")
    ap.add_argument("--org", choices=["test", "data"], default="test",
                    help="test = bac à sable DML (défaut), data = export réel en lecture seule")
    ap.add_argument("--entry", default="Main.cls",
                    help="(scénario) fichier point d'entrée (défaut: Main.cls)")
    ap.add_argument("--ast", action="store_true", help="afficher l'AST avant exécution")
    ap.add_argument("--no-seed", action="store_true",
                    help="(org test) ne pas créer les données de démo")
    ap.add_argument("--no-triggers", action="store_true",
                    help="(org test) ne pas charger les triggers d'apex/")
    args = ap.parse_args()

    # Scénario : répertoire
    if args.cible and os.path.isdir(args.cible):
        from emusf.scenario_runner import load_scenario
        return 0 if load_scenario(args.cible, args.entry, args.methode) else 1

    org = make_org(args.org, seed=not args.no_seed, triggers=not args.no_triggers)

    # Classe : fichier .cls
    if args.cible:
        if not os.path.isfile(args.cible):
            print(RED + "Erreur: '{}' introuvable".format(args.cible) + RESET)
            return 1
        run_class(args.cible, args.methode, org, args.ast)
        return 0

    # REPL
    run_repl(org, args.ast)
    return 0


if __name__ == "__main__":
    sys.exit(main())
