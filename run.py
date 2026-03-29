"""Exécute un fichier Apex via l'émulateur."""

import sys
import glob

from emusf import PgTestOrg, ApexParser, ApexInterpreter
from emusf.config import DSN
from emusf.ast_printer import print_ast
from emusf.trigger_parser import load_trigger

# --- Setup org avec des données ---
org = PgTestOrg(DSN, schema="test")
org.truncate_all()
org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0"})
org.create_sobject("Contact", {"LastName": "TEXT", "AccountId": "TEXT"})

org.register_relationship("Contacts", "Contact", "AccountId", "Account")

org.insert("Account", [
    {"Id": "001001", "Name": "Acme", "Active__c": 1},
    {"Id": "001002", "Name": "Boring Corp", "Active__c": 0},
])
org.insert("Contact", [
    {"Id": "003001", "LastName": "Dupont", "AccountId": "001001"},
    {"Id": "003002", "LastName": "Martin", "AccountId": "001001"},
])

# --- Charger tous les triggers ---
for trigger_file in sorted(glob.glob("apex/*.trigger")):
    load_trigger(org, trigger_file)

# --- Exécuter le fichier Apex ---
apex_file = sys.argv[1] if len(sys.argv) > 1 else "apex/AccountDemo.cls"
method = sys.argv[2] if len(sys.argv) > 2 else "run"

print("\n=== Exécution: {} -> {}() ===\n".format(apex_file, method))

# --- Parser: Apex → AST ---
with open(apex_file) as f:
    source = f.read()

parser = ApexParser()
ast = parser.parse_class(source, method)

print("--- AST ---")
print_ast(ast)
print()

# --- Interpréteur: AST → exécution ---
print("--- Exécution ---")
interpreter = ApexInterpreter(org)
interpreter._exec_block(ast)

# Cleanup
org.truncate_all()
org.conn.close()
