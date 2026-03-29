"""Parse un fichier .flow-meta.xml en FlowDefinition."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

from .flow_nodes import (
    FlowDefinition, FlowStart, FlowConnector, FlowVariable, FlowFormula,
    FlowConstant, FlowTextTemplate, FlowAssignment, FlowAssignmentItem,
    FlowDecision, FlowDecisionRule, FlowCondition, FlowRecordUpdate,
    FlowRecordLookup, FlowRecordCreate, FlowRecordDelete, FlowLoop,
)

# Namespace Salesforce Flow metadata
NS = "http://soap.sforce.com/2006/04/metadata"
_NS_PREFIX = "{" + NS + "}"


def _tag(local: str) -> str:
    """Retourne le tag qualifié avec le namespace."""
    return _NS_PREFIX + local


def _text(elem: ET.Element, child: str) -> str | None:
    """Extrait le texte d'un sous-élément."""
    ch = elem.find(_tag(child))
    if ch is not None and ch.text:
        return ch.text.strip()
    return None


def _bool(elem: ET.Element, child: str, default: bool = False) -> bool:
    """Extrait un booléen d'un sous-élément."""
    val = _text(elem, child)
    if val is None:
        return default
    return val.lower() == "true"


def _connector(elem: ET.Element, child: str = "connector") -> FlowConnector | None:
    """Parse un <connector> ou <defaultConnector>."""
    conn_elem = elem.find(_tag(child))
    if conn_elem is None:
        return None
    target = _text(conn_elem, "targetReference")
    if target:
        return FlowConnector(target_reference=target)
    return None


def _parse_condition(elem: ET.Element) -> FlowCondition:
    """Parse un <conditions> ou <filters>."""
    return FlowCondition(
        left_reference=_text(elem, "leftValueReference") or _text(elem, "field") or "",
        operator=_text(elem, "operator") or "EqualTo",
        right_value=_text(elem, "rightValue")
               or _text_nested(elem, "rightValue", "stringValue")
               or _text_nested(elem, "rightValue", "numberValue")
               or _text_nested(elem, "rightValue", "booleanValue")
               or _text_nested(elem, "value", "stringValue")
               or _text_nested(elem, "value", "numberValue"),
        right_reference=_text_nested(elem, "rightValue", "elementReference")
                     or _text_nested(elem, "value", "elementReference"),
    )


def _text_nested(elem: ET.Element, parent: str, child: str) -> str | None:
    """Extrait un texte imbriqué: <parent><child>text</child></parent>."""
    p = elem.find(_tag(parent))
    if p is not None:
        return _text(p, child)
    return None


def _parse_assignment_item(elem: ET.Element) -> FlowAssignmentItem:
    """Parse un <assignmentItems> ou <inputAssignments>."""
    return FlowAssignmentItem(
        assign_to_reference=_text(elem, "assignToReference") or _text(elem, "field") or "",
        operator=_text(elem, "operator") or "Assign",
        value=_text_nested(elem, "value", "stringValue")
            or _text_nested(elem, "value", "numberValue")
            or _text_nested(elem, "value", "dateValue")
            or _text_nested(elem, "value", "dateTimeValue")
            or _text_nested(elem, "value", "booleanValue"),
        element_reference=_text_nested(elem, "value", "elementReference"),
    )


def _parse_start(elem: ET.Element) -> FlowStart:
    """Parse l'élément <start>."""
    filters = [
        _parse_condition(f)
        for f in elem.findall(_tag("filters"))
    ]
    return FlowStart(
        connector=_connector(elem),
        object=_text(elem, "object"),
        record_trigger_type=_text(elem, "recordTriggerType"),
        trigger_type=_text(elem, "triggerType"),
        filters=filters,
        filter_logic=_text(elem, "filterLogic"),
    )


def _parse_variable(elem: ET.Element) -> FlowVariable:
    """Parse un <variables>."""
    default_val = (_text_nested(elem, "value", "stringValue")
                   or _text_nested(elem, "value", "numberValue")
                   or _text_nested(elem, "value", "booleanValue"))
    return FlowVariable(
        name=_text(elem, "name") or "",
        data_type=_text(elem, "dataType") or "String",
        value=default_val,
        is_input=_bool(elem, "isInput"),
        is_output=_bool(elem, "isOutput"),
        object_type=_text(elem, "objectType"),
    )


def _parse_formula(elem: ET.Element) -> FlowFormula:
    """Parse un <formulas>."""
    return FlowFormula(
        name=_text(elem, "name") or "",
        data_type=_text(elem, "dataType") or "String",
        expression=_text(elem, "expression") or "",
    )


def _parse_assignment(elem: ET.Element) -> FlowAssignment:
    """Parse un <assignments>."""
    items = [
        _parse_assignment_item(ai)
        for ai in elem.findall(_tag("assignmentItems"))
    ]
    return FlowAssignment(
        name=_text(elem, "name") or "",
        label=_text(elem, "label") or "",
        items=items,
        connector=_connector(elem),
    )


def _parse_decision(elem: ET.Element) -> FlowDecision:
    """Parse un <decisions>."""
    rules = []
    for rule_elem in elem.findall(_tag("rules")):
        conditions = [
            _parse_condition(c) for c in rule_elem.findall(_tag("conditions"))
        ]
        rules.append(FlowDecisionRule(
            name=_text(rule_elem, "name") or "",
            label=_text(rule_elem, "label") or "",
            condition_logic=_text(rule_elem, "conditionLogic") or "and",
            conditions=conditions,
            connector=_connector(rule_elem),
        ))
    return FlowDecision(
        name=_text(elem, "name") or "",
        label=_text(elem, "label") or "",
        rules=rules,
        default_connector=_connector(elem, "defaultConnector"),
    )


def _parse_record_update(elem: ET.Element) -> FlowRecordUpdate:
    """Parse un <recordUpdates>."""
    filters = [_parse_condition(f) for f in elem.findall(_tag("filters"))]
    assignments = [
        _parse_assignment_item(ai)
        for ai in elem.findall(_tag("inputAssignments"))
    ]
    return FlowRecordUpdate(
        name=_text(elem, "name") or "",
        label=_text(elem, "label") or "",
        object=_text(elem, "object"),
        input_reference=_text(elem, "inputReference"),
        filters=filters,
        input_assignments=assignments,
        connector=_connector(elem),
    )


def _parse_record_lookup(elem: ET.Element) -> FlowRecordLookup:
    """Parse un <recordLookups>."""
    filters = [_parse_condition(f) for f in elem.findall(_tag("filters"))]
    output_assignments = [
        _parse_assignment_item(ai)
        for ai in elem.findall(_tag("outputAssignments"))
    ]
    return FlowRecordLookup(
        name=_text(elem, "name") or "",
        label=_text(elem, "label") or "",
        object=_text(elem, "object") or "",
        filters=filters,
        output_reference=_text(elem, "outputReference"),
        output_assignments=output_assignments,
        sort_field=_text(elem, "sortField"),
        sort_order=_text(elem, "sortOrder"),
        limit=int(_text(elem, "limit")) if _text(elem, "limit") else None,
        get_first_record_only=_bool(elem, "getFirstRecordOnly", default=True),
        connector=_connector(elem),
    )


def _parse_record_create(elem: ET.Element) -> FlowRecordCreate:
    """Parse un <recordCreates>."""
    assignments = [
        _parse_assignment_item(ai)
        for ai in elem.findall(_tag("inputAssignments"))
    ]
    return FlowRecordCreate(
        name=_text(elem, "name") or "",
        label=_text(elem, "label") or "",
        object=_text(elem, "object") or "",
        input_assignments=assignments,
        input_reference=_text(elem, "inputReference"),
        store_output_automatically=_bool(elem, "storeOutputAutomatically"),
        output_reference=_text(elem, "assignRecordIdToReference"),
        connector=_connector(elem),
    )


def _parse_record_delete(elem: ET.Element) -> FlowRecordDelete:
    """Parse un <recordDeletes>."""
    filters = [_parse_condition(f) for f in elem.findall(_tag("filters"))]
    return FlowRecordDelete(
        name=_text(elem, "name") or "",
        label=_text(elem, "label") or "",
        object=_text(elem, "object"),
        input_reference=_text(elem, "inputReference"),
        filters=filters,
        connector=_connector(elem),
    )


def _parse_loop(elem: ET.Element) -> FlowLoop:
    """Parse un <loops>."""
    return FlowLoop(
        name=_text(elem, "name") or "",
        label=_text(elem, "label") or "",
        collection_reference=_text(elem, "collectionReference") or "",
        iteration_order=_text(elem, "iterationOrder") or "Asc",
        next_value_connector=_connector(elem, "nextValueConnector"),
        no_more_values_connector=_connector(elem, "noMoreValuesConnector"),
        iterator_variable=_text(elem, "iteratorVariable"),
    )


def parse_flow(source: str, api_name: str = "UnknownFlow") -> FlowDefinition:
    """
    Parse le XML d'un flow Salesforce en FlowDefinition.
    source: contenu XML du fichier .flow-meta.xml
    api_name: nom API du flow (généralement le nom de fichier)
    """
    root = ET.fromstring(source)

    flow = FlowDefinition(
        label=_text(root, "label") or api_name,
        api_name=api_name,
        process_type=_text(root, "processType") or "AutoLaunchedFlow",
    )

    # Start
    start_elem = root.find(_tag("start"))
    if start_elem is not None:
        flow.start = _parse_start(start_elem)

    # Variables
    for elem in root.findall(_tag("variables")):
        var = _parse_variable(elem)
        flow.variables[var.name] = var

    # Formules
    for elem in root.findall(_tag("formulas")):
        formula = _parse_formula(elem)
        flow.formulas[formula.name] = formula

    # Constantes
    for elem in root.findall(_tag("constants")):
        c = FlowConstant(
            name=_text(elem, "name") or "",
            data_type=_text(elem, "dataType") or "String",
            value=_text_nested(elem, "value", "stringValue")
                  or _text_nested(elem, "value", "numberValue") or "",
        )
        flow.constants[c.name] = c

    # Text templates
    for elem in root.findall(_tag("textTemplates")):
        tt = FlowTextTemplate(
            name=_text(elem, "name") or "",
            text=_text(elem, "text") or "",
        )
        flow.text_templates[tt.name] = tt

    # Assignments
    for elem in root.findall(_tag("assignments")):
        a = _parse_assignment(elem)
        flow.assignments[a.name] = a

    # Decisions
    for elem in root.findall(_tag("decisions")):
        d = _parse_decision(elem)
        flow.decisions[d.name] = d

    # Record Updates
    for elem in root.findall(_tag("recordUpdates")):
        ru = _parse_record_update(elem)
        flow.record_updates[ru.name] = ru

    # Record Lookups
    for elem in root.findall(_tag("recordLookups")):
        rl = _parse_record_lookup(elem)
        flow.record_lookups[rl.name] = rl

    # Record Creates
    for elem in root.findall(_tag("recordCreates")):
        rc = _parse_record_create(elem)
        flow.record_creates[rc.name] = rc

    # Record Deletes
    for elem in root.findall(_tag("recordDeletes")):
        rd = _parse_record_delete(elem)
        flow.record_deletes[rd.name] = rd

    # Loops
    for elem in root.findall(_tag("loops")):
        lp = _parse_loop(elem)
        flow.loops[lp.name] = lp

    return flow


def load_flow(path: str) -> FlowDefinition:
    """Charge un flow depuis un fichier .flow-meta.xml."""
    with open(path) as f:
        source = f.read()
    # Déduire le nom API depuis le nom de fichier
    basename = os.path.basename(path)
    api_name = basename.replace(".flow-meta.xml", "").replace(".flow", "")
    return parse_flow(source, api_name=api_name)
