"""Démo de l'émulateur Salesforce."""

from emusf import PgTestOrg, ApexContext
from emusf.config import DSN


# --- Setup org ---
org = PgTestOrg(DSN, schema="test")
org.truncate_all()
org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0"})
org.create_sobject("Contact", {"LastName": "TEXT", "AccountId": "TEXT"})
org.create_sobject("Opportunity", {"Name": "TEXT", "Amount": "DOUBLE PRECISION", "AccountId": "TEXT"})

org.register_relationship("Contacts", "Contact", "AccountId", "Account")
org.register_relationship("Opportunities", "Opportunity", "AccountId", "Account")

# --- Données ---
org.insert("Account", [
    {"Id": "001001", "Name": "Acme", "Active__c": 1},
    {"Id": "001002", "Name": "Boring Corp", "Active__c": 0},
])
org.insert("Contact", [
    {"Id": "003001", "LastName": "Dupont", "AccountId": "001001"},
    {"Id": "003002", "LastName": "Martin", "AccountId": "001001"},
    {"Id": "003003", "LastName": "Bernard", "AccountId": "001002"},
])
org.insert("Opportunity", [
    {"Id": "006001", "Name": "Deal 1", "Amount": 50000, "AccountId": "001001"},
])

ctx = ApexContext(org)

# --- 1. Simuler AccountUtil.status(accountId) ---
print("=== AccountUtil.status() ===")


def apex_status(account_id: str) -> str:
    ctx.set("accountId", account_id)
    results = ctx.soql("[SELECT Id, Active__c FROM Account WHERE Id = :accountId]")
    if not results:
        return "Not Found"
    return "Active" if results[0]["Active__c"] else "Inactive"


print(f"001001 → {apex_status('001001')}")  # Active
print(f"001002 → {apex_status('001002')}")  # Inactive
print(f"001099 → {apex_status('001099')}")  # Not Found

# --- 2. SOQL avec sous-requêtes ---
print("\n=== SOQL avec sous-requêtes ===")

results = ctx.soql("""
    [SELECT Id, Name,
        (SELECT Id, LastName FROM Contacts),
        (SELECT Id, Name, Amount FROM Opportunities)
    FROM Account WHERE Name = 'Acme']
""")

for acc in results:
    print(f"Account: {acc['Name']}")
    for c in acc.get("Contacts", []):
        print(f"  └ Contact: {c['LastName']}")
    for o in acc.get("Opportunities", []):
        print(f"  └ Opportunity: {o['Name']} ({o['Amount']}€)")

# Cleanup
org.truncate_all()
org.conn.close()
