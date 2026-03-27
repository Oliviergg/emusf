"""Exécute un fichier Apex via l'émulateur."""

import sys

from emusf import FakeOrg, ApexInterpreter

# --- Setup org avec des données ---
org = FakeOrg()
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

# --- Exécuter le fichier Apex ---
apex_file = sys.argv[1] if len(sys.argv) > 1 else "apex/AccountDemo.cls"
method = sys.argv[2] if len(sys.argv) > 2 else "run"

print("=== Exécution: {} → {}() ===\n".format(apex_file, method))

interpreter = ApexInterpreter(org)
interpreter.execute_file(apex_file, method)
