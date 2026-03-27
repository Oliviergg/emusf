"""Tests pour l'émulateur Salesforce."""

from emusf import FakeOrg, ApexContext


def make_org() -> FakeOrg:
    """Crée une org de test avec Account, Contact, Opportunity."""
    org = FakeOrg()

    org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0"})
    org.create_sobject(
        "Contact", {"LastName": "TEXT", "AccountId": "TEXT"}
    )
    org.create_sobject(
        "Opportunity", {"Name": "TEXT", "Amount": "REAL", "AccountId": "TEXT"}
    )

    org.register_relationship("Contacts", "Contact", "AccountId", "Account")
    org.register_relationship("Opportunities", "Opportunity", "AccountId", "Account")

    return org


def test_simple_soql():
    org = make_org()
    org.insert("Account", [
        {"Id": "001001", "Name": "Acme", "Active__c": 1},
        {"Id": "001002", "Name": "Boring Corp", "Active__c": 0},
    ])

    results = org.execute_soql(
        "SELECT Id, Name FROM Account WHERE Name = 'Acme'"
    )
    assert len(results) == 1
    assert results[0]["Name"] == "Acme"


def test_bind_variables():
    org = make_org()
    ctx = ApexContext(org)

    org.insert("Account", [
        {"Id": "001001", "Name": "Acme", "Active__c": 1},
    ])

    ctx.set("accountId", "001001")
    results = ctx.soql("[SELECT Id, Active__c FROM Account WHERE Id = :accountId]")
    assert len(results) == 1
    assert results[0]["Active__c"] == 1


def test_status_function():
    """Simule AccountUtil.status(accountId)."""
    org = make_org()
    ctx = ApexContext(org)

    org.insert("Account", [
        {"Id": "001001", "Name": "Acme", "Active__c": 1},
        {"Id": "001002", "Name": "Boring Corp", "Active__c": 0},
    ])

    def apex_status(account_id: str) -> str:
        ctx.set("accountId", account_id)
        results = ctx.soql("[SELECT Id, Active__c FROM Account WHERE Id = :accountId]")
        if not results:
            return "Not Found"
        return "Active" if results[0]["Active__c"] else "Inactive"

    assert apex_status("001001") == "Active"
    assert apex_status("001002") == "Inactive"
    assert apex_status("001099") == "Not Found"


def test_subquery_contacts():
    org = make_org()
    ctx = ApexContext(org)

    org.insert("Account", [{"Id": "001001", "Name": "Acme"}])
    org.insert("Contact", [
        {"Id": "003001", "LastName": "Dupont", "AccountId": "001001"},
        {"Id": "003002", "LastName": "Martin", "AccountId": "001001"},
    ])

    results = ctx.soql("""
        [SELECT Id, Name,
            (SELECT Id, LastName FROM Contacts)
        FROM Account WHERE Name = 'Acme']
    """)

    assert len(results) == 1
    assert results[0]["Name"] == "Acme"
    assert len(results[0]["Contacts"]) == 2
    last_names = {c["LastName"] for c in results[0]["Contacts"]}
    assert last_names == {"Dupont", "Martin"}


def test_multiple_subqueries():
    org = make_org()
    ctx = ApexContext(org)

    org.insert("Account", [{"Id": "001001", "Name": "Acme"}])
    org.insert("Contact", [
        {"Id": "003001", "LastName": "Dupont", "AccountId": "001001"},
    ])
    org.insert("Opportunity", [
        {"Id": "006001", "Name": "Deal 1", "Amount": 50000, "AccountId": "001001"},
    ])

    results = ctx.soql("""
        [SELECT Id, Name,
            (SELECT Id, LastName FROM Contacts),
            (SELECT Id, Name, Amount FROM Opportunities)
        FROM Account WHERE Name = 'Acme']
    """)

    assert len(results) == 1
    assert len(results[0]["Contacts"]) == 1
    assert len(results[0]["Opportunities"]) == 1
    assert results[0]["Opportunities"][0]["Amount"] == 50000


def test_subquery_no_results():
    """Account sans contacts."""
    org = make_org()
    ctx = ApexContext(org)

    org.insert("Account", [{"Id": "001001", "Name": "Lonely Corp"}])

    results = ctx.soql("""
        [SELECT Id, Name,
            (SELECT Id, LastName FROM Contacts)
        FROM Account WHERE Name = 'Lonely Corp']
    """)

    assert len(results) == 1
    assert results[0]["Contacts"] == []
