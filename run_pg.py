"""Exécute un fichier Apex contre les données Salesforce exportées
(schema `data`, lecture seule via PgOrg)."""

import sys

from emusf import ApexParser, ApexInterpreter
from emusf.config import DSN
from emusf.pg_org import PgOrg
from emusf.ast_printer import print_ast

org = PgOrg(DSN, schema="data")

# --- Exécuter le fichier Apex ---
apex_file = sys.argv[1] if len(sys.argv) > 1 else "apex/AccountPgDemo.cls"
method = sys.argv[2] if len(sys.argv) > 2 else "run"

print("=== PG Exécution: {} -> {}() ===\n".format(apex_file, method))

# --- Parser: Apex → AST ---
with open(apex_file) as f:
    source = f.read()

parser = ApexParser()
ast = parser.parse_class(source, method)

print("--- AST ---")
print_ast(ast)
print()

# --- Interpréteur: AST → exécution contre PG ---
print("--- Exécution ---")
interpreter = ApexInterpreter(org)
interpreter._exec_block(ast)
