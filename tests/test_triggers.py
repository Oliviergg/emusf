"""Tests pour les triggers Apex."""

from emusf.trigger_parser import load_trigger


def setup_org(org):
    org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0"})


def test_before_insert_trigger_modifies_record(org):
    setup_org(org)
    load_trigger(org, "apex/AccountTrigger.trigger")

    result = org.insert("Account", [{"Name": "Test", "Active__c": 0}])

    rows = org.execute_soql(
        "SELECT Active__c FROM Account WHERE Id = '{}'".format(result.record_ids[0])
    )
    assert len(rows) == 1
    assert rows[0]["Active__c"] == 1


def test_before_update_trigger_modifies_record(org):
    setup_org(org)
    load_trigger(org, "apex/AccountTrigger.trigger")

    result = org.insert("Account", [{"Name": "Corp", "Active__c": 1}])
    record_id = result.record_ids[0]

    org.update("Account", [{"Id": record_id, "Active__c": 0}])

    rows = org.execute_soql(
        "SELECT Active__c FROM Account WHERE Id = '{}'".format(record_id)
    )
    assert len(rows) == 1
    assert rows[0]["Active__c"] == 1


def test_trigger_no_change_when_active(org):
    setup_org(org)
    load_trigger(org, "apex/AccountTrigger.trigger")

    result = org.insert("Account", [{"Name": "OK Corp", "Active__c": 1}])

    rows = org.execute_soql(
        "SELECT Active__c FROM Account WHERE Id = '{}'".format(result.record_ids[0])
    )
    assert len(rows) == 1
    assert rows[0]["Active__c"] == 1
