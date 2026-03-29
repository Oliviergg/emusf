"""Tests pour le simulateur de Flows Salesforce."""

import os
from emusf.flow_parser import parse_flow, load_flow
from emusf.flow_interpreter import FlowInterpreter, register_flow, load_and_register_flow

FLOWS_DIR = os.path.join(os.path.dirname(__file__), "..", "flows")


# === Parsing ===


def test_parse_fl_update_date():
    flow = load_flow(os.path.join(FLOWS_DIR, "FL_updateDate.flow-meta.xml"))
    assert flow.api_name == "FL_updateDate"
    assert flow.label == "FL_updateDate"
    assert flow.process_type == "AutoLaunchedFlow"
    assert flow.start.object == "Account"
    assert flow.start.trigger_type == "RecordBeforeSave"
    assert flow.start.record_trigger_type == "CreateAndUpdate"
    assert flow.start.connector.target_reference == "Set_Date"
    assert "Set_Date" in flow.assignments
    assert "Set_Description" in flow.assignments
    assert "fml_Now" in flow.formulas


def test_parse_fl_set_status():
    flow = load_flow(os.path.join(FLOWS_DIR, "FL_setStatus.flow-meta.xml"))
    assert flow.api_name == "FL_setStatus"
    assert flow.start.object == "Opportunity"
    assert "Check_Amount" in flow.decisions
    decision = flow.decisions["Check_Amount"]
    assert len(decision.rules) == 2
    assert decision.rules[0].name == "High_Value"
    assert decision.rules[1].name == "Medium_Value"
    assert decision.default_connector is not None


def test_parse_assignment_chain():
    flow = load_flow(os.path.join(FLOWS_DIR, "FL_updateDate.flow-meta.xml"))
    set_date = flow.assignments["Set_Date"]
    assert set_date.connector is not None
    assert set_date.connector.target_reference == "Set_Description"
    set_desc = flow.assignments["Set_Description"]
    assert set_desc.connector is None  # fin du flow


# === Interprétation — FL_updateDate ===


def test_run_fl_update_date(org):
    """Le flow doit mettre à jour LastModifiedDate__c et Description."""
    flow = load_flow(os.path.join(FLOWS_DIR, "FL_updateDate.flow-meta.xml"))
    record = {"Id": "001000000000001", "Name": "Test Corp"}

    interp = FlowInterpreter(org, flow)
    interp.run(record=record)

    # Le flow a assigné LastModifiedDate__c (via NOW())
    assert record.get("LastModifiedDate__c") is not None
    assert "T" in record["LastModifiedDate__c"]  # format DateTime
    # Le flow a assigné Description
    assert record["Description"] == "Updated by flow"


def test_fl_update_date_debug_log(org):
    """Vérifie que le debug log trace les éléments traversés."""
    flow = load_flow(os.path.join(FLOWS_DIR, "FL_updateDate.flow-meta.xml"))
    record = {"Id": "001000000000001", "Name": "Test"}

    interp = FlowInterpreter(org, flow)
    interp.run(record=record)

    assert any("Set_Date" in entry for entry in interp.debug_log)
    assert any("Set_Description" in entry for entry in interp.debug_log)


# === Interprétation — FL_setStatus (décisions) ===


def test_decision_high_value(org):
    flow = load_flow(os.path.join(FLOWS_DIR, "FL_setStatus.flow-meta.xml"))
    record = {"Id": "006000000000001", "Name": "Big Deal", "Amount": 200000}

    interp = FlowInterpreter(org, flow)
    interp.run(record=record)

    assert record["Priority__c"] == "High"


def test_decision_medium_value(org):
    flow = load_flow(os.path.join(FLOWS_DIR, "FL_setStatus.flow-meta.xml"))
    record = {"Id": "006000000000002", "Name": "Medium Deal", "Amount": 50000}

    interp = FlowInterpreter(org, flow)
    interp.run(record=record)

    assert record["Priority__c"] == "Medium"


def test_decision_low_value(org):
    flow = load_flow(os.path.join(FLOWS_DIR, "FL_setStatus.flow-meta.xml"))
    record = {"Id": "006000000000003", "Name": "Small Deal", "Amount": 500}

    interp = FlowInterpreter(org, flow)
    interp.run(record=record)

    assert record["Priority__c"] == "Low"


# === Intégration avec PgTestOrg (flow enregistré comme trigger) ===


def test_flow_registered_on_insert(org):
    """Le flow before-save doit se déclencher sur un insert."""
    org.create_sobject("Account", {
        "Name": "TEXT",
        "LastModifiedDate__c": "TEXT",
        "Description": "TEXT",
    })
    load_and_register_flow(org, os.path.join(FLOWS_DIR, "FL_updateDate.flow-meta.xml"))

    result = org.insert("Account", [{"Name": "FlowTest Corp"}])
    rid = result.record_ids[0]

    # Vérifier que le flow a modifié le record en base
    rows = org.execute_soql(
        "SELECT LastModifiedDate__c, Description FROM Account WHERE Id = '{}'".format(rid)
    )
    assert len(rows) == 1
    assert rows[0]["LastModifiedDate__c"] is not None
    assert rows[0]["Description"] == "Updated by flow"


def test_flow_registered_on_update(org):
    """Le flow before-save doit aussi se déclencher sur un update."""
    org.create_sobject("Account", {
        "Name": "TEXT",
        "LastModifiedDate__c": "TEXT",
        "Description": "TEXT",
    })
    load_and_register_flow(org, os.path.join(FLOWS_DIR, "FL_updateDate.flow-meta.xml"))

    result = org.insert("Account", [{"Name": "Corp"}])
    rid = result.record_ids[0]

    # Update
    org.update("Account", [{"Id": rid, "Name": "Corp Updated"}])

    rows = org.execute_soql(
        "SELECT Description FROM Account WHERE Id = '{}'".format(rid)
    )
    assert rows[0]["Description"] == "Updated by flow"


def test_decision_flow_registered_as_trigger(org):
    """FL_setStatus doit fonctionner comme trigger before-save sur Opportunity."""
    org.create_sobject("Opportunity", {
        "Name": "TEXT",
        "Amount": "REAL",
        "Priority__c": "TEXT",
    })
    load_and_register_flow(org, os.path.join(FLOWS_DIR, "FL_setStatus.flow-meta.xml"))

    org.insert("Opportunity", [{"Name": "Big", "Amount": 150000}])
    org.insert("Opportunity", [{"Name": "Small", "Amount": 100}])

    rows = org.execute_soql("SELECT Name, Priority__c FROM Opportunity ORDER BY Name")
    by_name = {r["Name"]: r["Priority__c"] for r in rows}
    assert by_name["Big"] == "High"
    assert by_name["Small"] == "Low"


# === Parsing inline ===


def test_parse_flow_from_string(org):
    """Parse un flow minimal depuis un string XML."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
        <label>TestFlow</label>
        <processType>AutoLaunchedFlow</processType>
        <start>
            <connector>
                <targetReference>Assign1</targetReference>
            </connector>
            <object>Contact</object>
            <recordTriggerType>Create</recordTriggerType>
            <triggerType>RecordBeforeSave</triggerType>
        </start>
        <assignments>
            <name>Assign1</name>
            <label>Assign 1</label>
            <assignmentItems>
                <assignToReference>$Record.Title</assignToReference>
                <operator>Assign</operator>
                <value>
                    <stringValue>Nouveau</stringValue>
                </value>
            </assignmentItems>
        </assignments>
    </Flow>"""
    flow = parse_flow(xml, api_name="TestFlow")
    assert flow.label == "TestFlow"
    assert flow.start.object == "Contact"

    # Exécuter
    record = {"Id": "003000000000001", "FirstName": "Jean"}
    interp = FlowInterpreter(org, flow)
    interp.run(record=record)
    assert record["Title"] == "Nouveau"


# === Variables et formules ===


def test_flow_with_variables(org):
    """Flow qui utilise des variables internes."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
        <label>VarFlow</label>
        <processType>AutoLaunchedFlow</processType>
        <variables>
            <name>counter</name>
            <dataType>Number</dataType>
            <value><numberValue>0</numberValue></value>
        </variables>
        <start>
            <connector>
                <targetReference>Increment</targetReference>
            </connector>
            <object>Account</object>
            <recordTriggerType>Create</recordTriggerType>
            <triggerType>RecordBeforeSave</triggerType>
        </start>
        <assignments>
            <name>Increment</name>
            <label>Increment counter</label>
            <assignmentItems>
                <assignToReference>counter</assignToReference>
                <operator>Add</operator>
                <value>
                    <numberValue>5</numberValue>
                </value>
            </assignmentItems>
            <connector>
                <targetReference>SetField</targetReference>
            </connector>
        </assignments>
        <assignments>
            <name>SetField</name>
            <label>Set Field</label>
            <assignmentItems>
                <assignToReference>$Record.Score__c</assignToReference>
                <operator>Assign</operator>
                <value>
                    <elementReference>counter</elementReference>
                </value>
            </assignmentItems>
        </assignments>
    </Flow>"""
    flow = parse_flow(xml, api_name="VarFlow")
    record = {"Id": "001000000000001", "Name": "Test"}
    interp = FlowInterpreter(org, flow)
    interp.run(record=record)
    assert record["Score__c"] == 5.0


def test_flow_today_formula(org):
    """Flow avec formule TODAY()."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
        <label>DateFlow</label>
        <processType>AutoLaunchedFlow</processType>
        <formulas>
            <name>fml_Today</name>
            <dataType>Date</dataType>
            <expression>TODAY()</expression>
        </formulas>
        <start>
            <connector>
                <targetReference>SetDate</targetReference>
            </connector>
            <object>Account</object>
            <recordTriggerType>Create</recordTriggerType>
            <triggerType>RecordBeforeSave</triggerType>
        </start>
        <assignments>
            <name>SetDate</name>
            <label>Set Date</label>
            <assignmentItems>
                <assignToReference>$Record.CreatedDate__c</assignToReference>
                <operator>Assign</operator>
                <value>
                    <elementReference>fml_Today</elementReference>
                </value>
            </assignmentItems>
        </assignments>
    </Flow>"""
    flow = parse_flow(xml, api_name="DateFlow")
    record = {"Id": "001000000000001"}
    interp = FlowInterpreter(org, flow)
    interp.run(record=record)

    from datetime import date
    assert record["CreatedDate__c"] == date.today().strftime("%Y-%m-%d")


# === Entry conditions ===


def test_flow_entry_conditions_pass(org):
    """Flow avec des conditions d'entrée qui passent."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
        <label>FilteredFlow</label>
        <processType>AutoLaunchedFlow</processType>
        <start>
            <connector>
                <targetReference>SetTag</targetReference>
            </connector>
            <object>Account</object>
            <recordTriggerType>Create</recordTriggerType>
            <triggerType>RecordBeforeSave</triggerType>
            <filters>
                <leftValueReference>$Record.Type</leftValueReference>
                <operator>EqualTo</operator>
                <rightValue>
                    <stringValue>Customer</stringValue>
                </rightValue>
            </filters>
        </start>
        <assignments>
            <name>SetTag</name>
            <label>Set Tag</label>
            <assignmentItems>
                <assignToReference>$Record.Tag__c</assignToReference>
                <operator>Assign</operator>
                <value>
                    <stringValue>VIP</stringValue>
                </value>
            </assignmentItems>
        </assignments>
    </Flow>"""
    flow = parse_flow(xml, api_name="FilteredFlow")

    # Record qui matche le filtre
    record = {"Id": "001000000000001", "Type": "Customer"}
    interp = FlowInterpreter(org, flow)
    interp.run(record=record)
    assert record["Tag__c"] == "VIP"


def test_flow_entry_conditions_fail(org):
    """Flow avec des conditions d'entrée qui échouent — pas d'exécution."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Flow xmlns="http://soap.sforce.com/2006/04/metadata">
        <label>FilteredFlow</label>
        <processType>AutoLaunchedFlow</processType>
        <start>
            <connector>
                <targetReference>SetTag</targetReference>
            </connector>
            <object>Account</object>
            <recordTriggerType>Create</recordTriggerType>
            <triggerType>RecordBeforeSave</triggerType>
            <filters>
                <leftValueReference>$Record.Type</leftValueReference>
                <operator>EqualTo</operator>
                <rightValue>
                    <stringValue>Customer</stringValue>
                </rightValue>
            </filters>
        </start>
        <assignments>
            <name>SetTag</name>
            <label>Set Tag</label>
            <assignmentItems>
                <assignToReference>$Record.Tag__c</assignToReference>
                <operator>Assign</operator>
                <value>
                    <stringValue>VIP</stringValue>
                </value>
            </assignmentItems>
        </assignments>
    </Flow>"""
    flow = parse_flow(xml, api_name="FilteredFlow")

    # Record qui ne matche PAS
    record = {"Id": "001000000000001", "Type": "Partner"}
    interp = FlowInterpreter(org, flow)
    interp.run(record=record)
    assert record.get("Tag__c") is None
