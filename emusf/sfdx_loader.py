"""Charge les métadonnées SFDX (.object-meta.xml, .field-meta.xml) dans une PgOrg."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Optional

NS = "{http://soap.sforce.com/2006/04/metadata}"


def _tag(name: str) -> str:
    return NS + name


def parse_field(path: str) -> dict:
    """Parse un .field-meta.xml et retourne un dict de métadonnées."""
    tree = ET.parse(path)
    root = tree.getroot()

    field = {
        "fullName": _text(root, "fullName"),
        "label": _text(root, "label"),
        "type": _text(root, "type"),
        "required": _text(root, "required") == "true",
        "referenceTo": _text(root, "referenceTo"),
        "relationshipName": _text(root, "relationshipName"),
        "relationshipLabel": _text(root, "relationshipLabel"),
        "formula": _text(root, "formula"),
    }
    return field


def parse_validation_rule(path: str) -> dict:
    """Parse un .validationRule-meta.xml."""
    tree = ET.parse(path)
    root = tree.getroot()

    return {
        "fullName": _text(root, "fullName"),
        "active": _text(root, "active") == "true",
        "errorConditionFormula": _text(root, "errorConditionFormula"),
        "errorMessage": _text(root, "errorMessage"),
        "errorDisplayField": _text(root, "errorDisplayField"),
    }


def load_sobject_meta(objects_dir: str, sobject_name: str) -> dict:
    """
    Charge toutes les métadonnées d'un SObject depuis le répertoire SFDX.
    Retourne { 'fields': [...], 'validationRules': [...], 'lookups': [...] }
    """
    obj_dir = os.path.join(objects_dir, sobject_name)
    result = {
        "name": sobject_name,
        "fields": [],
        "validationRules": [],
        "lookups": [],
    }

    # Champs
    fields_dir = os.path.join(obj_dir, "fields")
    if os.path.isdir(fields_dir):
        for fname in sorted(os.listdir(fields_dir)):
            if fname.endswith(".field-meta.xml"):
                fpath = os.path.join(fields_dir, fname)
                field = parse_field(fpath)
                result["fields"].append(field)
                if field["type"] == "Lookup" and field["referenceTo"]:
                    result["lookups"].append(field)

    # Validation rules
    vr_dir = os.path.join(obj_dir, "validationRules")
    if os.path.isdir(vr_dir):
        for fname in sorted(os.listdir(vr_dir)):
            if fname.endswith(".validationRule-meta.xml"):
                fpath = os.path.join(vr_dir, fname)
                vr = parse_validation_rule(fpath)
                result["validationRules"].append(vr)

    return result


def configure_pg_org(org, objects_dir: str, sobject_names: list, verbose: bool = False):
    """
    Configure une PgOrg avec les métadonnées SFDX.
    Enregistre les relations (lookups) dans le schema registry.
    Retourne les validation rules par SObject.
    """
    all_validation_rules = {}

    for name in sobject_names:
        meta = load_sobject_meta(objects_dir, name)

        # Enregistrer les relations lookup
        for lookup in meta["lookups"]:
            if lookup["relationshipName"] and lookup["referenceTo"]:
                org.sf_schema.register(
                    __import__("emusf.schema", fromlist=["RelationshipMeta"]).RelationshipMeta(
                        plural_name=lookup["relationshipName"],
                        sobject_name=name,
                        fk_column=lookup["fullName"],
                        parent_sobject=lookup["referenceTo"],
                    )
                )

        # Collecter les validation rules actives
        active_rules = [vr for vr in meta["validationRules"] if vr["active"]]
        if active_rules:
            all_validation_rules[name] = active_rules

        if verbose:
            field_count = len(meta["fields"])
            lookup_count = len(meta["lookups"])
            vr_count = len(active_rules)
            print("SFDX: {} — {} champs, {} lookups, {} validation rules".format(
                name, field_count, lookup_count, vr_count
            ))

    return all_validation_rules


def _text(root, tag_name: str) -> Optional[str]:
    el = root.find(_tag(tag_name))
    if el is not None and el.text:
        return el.text.strip()
    return None
