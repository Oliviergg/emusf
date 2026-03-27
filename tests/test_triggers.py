"""Tests pour les triggers Apex."""

from emusf import FakeOrg, ApexInterpreter
from emusf.trigger_parser import TriggerParser, load_trigger


def make_org():
    org = FakeOrg()
    org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0"})
    return org


def test_before_insert_trigger_modifies_record():
    org = make_org()

    # Charger le trigger depuis le fichier
    load_trigger(org, "apex/AccountTrigger.trigger")

    # Insert un compte inactif
    result = org.insert("Account", [{"Name": "Test", "Active__c": 0}])

    # Le trigger devrait avoir forcé Active__c = 1
    cursor = org.conn.execute(
        "SELECT Active__c FROM Account WHERE Id = ?", [result.record_ids[0]]
    )
    row = dict(cursor.fetchone())
    assert row["Active__c"] == 1


def test_before_update_trigger_modifies_record():
    org = make_org()
    load_trigger(org, "apex/AccountTrigger.trigger")

    # Insert actif (pas de changement)
    result = org.insert("Account", [{"Name": "Corp", "Active__c": 1}])
    record_id = result.record_ids[0]

    # Update vers inactif → le trigger re-force
    org.update("Account", [{"Id": record_id, "Active__c": 0}])

    cursor = org.conn.execute(
        "SELECT Active__c FROM Account WHERE Id = ?", [record_id]
    )
    row = dict(cursor.fetchone())
    assert row["Active__c"] == 1


def test_trigger_no_change_when_active():
    org = make_org()
    load_trigger(org, "apex/AccountTrigger.trigger")

    # Insert déjà actif
    result = org.insert("Account", [{"Name": "OK Corp", "Active__c": 1}])

    cursor = org.conn.execute(
        "SELECT Active__c FROM Account WHERE Id = ?", [result.record_ids[0]]
    )
    row = dict(cursor.fetchone())
    assert row["Active__c"] == 1
