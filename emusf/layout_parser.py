"""Parse les fichiers layout SFDX (.layout-meta.xml) en structures exploitables."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

NS = "{http://soap.sforce.com/2006/04/metadata}"


def _tag(name: str) -> str:
    return NS + name


def _text(el, tag_name: str) -> Optional[str]:
    child = el.find(_tag(tag_name))
    if child is not None and child.text:
        return child.text.strip()
    return None


@dataclass
class LayoutItem:
    field: Optional[str] = None
    behavior: Optional[str] = None  # Required, Edit, Readonly
    empty_space: bool = False


@dataclass
class LayoutColumn:
    items: list[LayoutItem] = field(default_factory=list)


@dataclass
class LayoutSection:
    label: str = ""
    style: str = "TwoColumnsLeftToRight"
    columns: list[LayoutColumn] = field(default_factory=list)
    detail_heading: bool = True
    custom_label: bool = False


@dataclass
class RelatedListDef:
    related_list: str = ""
    fields: list[str] = field(default_factory=list)
    sort_field: Optional[str] = None
    sort_order: Optional[str] = None


@dataclass
class PageLayout:
    name: str = ""
    sobject: str = ""
    sections: list[LayoutSection] = field(default_factory=list)
    related_lists: list[RelatedListDef] = field(default_factory=list)

    def all_fields(self) -> list[str]:
        """Retourne tous les noms de champs référencés dans le layout."""
        fields = []
        for section in self.sections:
            for col in section.columns:
                for item in col.items:
                    if item.field and not item.empty_space:
                        fields.append(item.field)
        return fields


def parse_layout(path: str) -> PageLayout:
    """Parse un fichier .layout-meta.xml en PageLayout."""
    tree = ET.parse(path)
    root = tree.getroot()

    layout = PageLayout()

    # Extraire le nom depuis le fichier
    basename = os.path.basename(path).replace(".layout-meta.xml", "")
    if "-" in basename:
        layout.sobject = basename.split("-")[0]
        layout.name = basename.split("-", 1)[1]
    else:
        layout.name = basename

    # Sections
    for section_el in root.findall(_tag("layoutSections")):
        section = LayoutSection()
        section.label = _text(section_el, "label") or ""
        section.style = _text(section_el, "style") or "TwoColumnsLeftToRight"
        section.detail_heading = _text(section_el, "detailHeading") == "true"
        section.custom_label = _text(section_el, "customLabel") == "true"

        # Skip CustomLinks / empty sections
        if section.style == "CustomLinks":
            continue

        for col_el in section_el.findall(_tag("layoutColumns")):
            col = LayoutColumn()
            for item_el in col_el.findall(_tag("layoutItems")):
                item = LayoutItem()
                if _text(item_el, "emptySpace") == "true":
                    item.empty_space = True
                else:
                    item.field = _text(item_el, "field")
                    item.behavior = _text(item_el, "behavior")
                # Skip report chart components
                if item_el.find(_tag("reportChartComponent")) is not None:
                    continue
                if item.field or item.empty_space:
                    col.items.append(item)
            section.columns.append(col)

        # Ne pas ajouter de sections vides
        has_fields = any(item.field for col in section.columns for item in col.items)
        if has_fields:
            layout.sections.append(section)

    # Related lists
    for rl_el in root.findall(_tag("relatedLists")):
        rl = RelatedListDef()
        rl.related_list = _text(rl_el, "relatedList") or ""
        rl.fields = [f.text.strip() for f in rl_el.findall(_tag("fields")) if f.text]
        rl.sort_field = _text(rl_el, "sortField")
        rl.sort_order = _text(rl_el, "sortOrder")
        layout.related_lists.append(rl)

    return layout


def load_field_labels(objects_dir: str, sobject_name: str) -> dict[str, dict]:
    """
    Charge les métadonnées de tous les champs d'un SObject.
    Retourne un dict { api_name: { label, type, required, ... } }
    """
    fields_dir = os.path.join(objects_dir, sobject_name, "fields")
    result = {}

    # Champs standard courants
    standard_labels = {
        "Name": {"label": "Nom", "type": "Text"},
        "Id": {"label": "ID", "type": "Text"},
        "OwnerId": {"label": "Propriétaire", "type": "Lookup"},
        "CreatedById": {"label": "Créé par", "type": "Lookup"},
        "LastModifiedById": {"label": "Dernière modification par", "type": "Lookup"},
        "CreatedDate": {"label": "Date de création", "type": "DateTime"},
        "LastModifiedDate": {"label": "Dernière modification", "type": "DateTime"},
        "AccountNumber": {"label": "Numéro de compte", "type": "Text"},
        "Phone": {"label": "Téléphone", "type": "Phone"},
        "Fax": {"label": "Fax", "type": "Phone"},
        "Website": {"label": "Site Web", "type": "Url"},
        "Description": {"label": "Description", "type": "TextArea"},
        "Industry": {"label": "Secteur d'activité", "type": "Picklist"},
        "Type": {"label": "Type", "type": "Picklist"},
        "AnnualRevenue": {"label": "Chiffre d'affaires annuel", "type": "Currency"},
        "NumberOfEmployees": {"label": "Nombre d'employés", "type": "Number"},
        "Ownership": {"label": "Propriété", "type": "Picklist"},
        "ParentId": {"label": "Compte parent", "type": "Lookup"},
        "BillingAddress": {"label": "Adresse de facturation", "type": "Address"},
        "BillingStreet": {"label": "Rue (facturation)", "type": "Text"},
        "BillingCity": {"label": "Ville (facturation)", "type": "Text"},
        "BillingState": {"label": "État (facturation)", "type": "Text"},
        "BillingPostalCode": {"label": "Code postal (facturation)", "type": "Text"},
        "BillingCountry": {"label": "Pays (facturation)", "type": "Text"},
        "ShippingAddress": {"label": "Adresse de livraison", "type": "Address"},
        # Contract standard fields
        "ContractNumber": {"label": "Numéro de contrat", "type": "Text"},
        "AccountId": {"label": "Compte", "type": "Lookup"},
        "Status": {"label": "Statut", "type": "Picklist"},
        "StartDate": {"label": "Date de début", "type": "Date"},
        "EndDate": {"label": "Date de fin", "type": "Date"},
        "ContractTerm": {"label": "Durée du contrat (mois)", "type": "Number"},
        "CustomerSignedId": {"label": "Signataire client", "type": "Lookup"},
        "CustomerSignedDate": {"label": "Date signature client", "type": "Date"},
        "CompanySignedId": {"label": "Signataire société", "type": "Lookup"},
        "CompanySignedDate": {"label": "Date signature société", "type": "Date"},
        "SpecialTerms": {"label": "Conditions particulières", "type": "TextArea"},
        "Pricebook2Id": {"label": "Catalogue de prix", "type": "Lookup"},
        "RecordTypeId": {"label": "Type d'enregistrement", "type": "Lookup"},
    }
    result.update(standard_labels)

    if not os.path.isdir(fields_dir):
        return result

    for fname in os.listdir(fields_dir):
        if not fname.endswith(".field-meta.xml"):
            continue
        fpath = os.path.join(fields_dir, fname)
        try:
            tree = ET.parse(fpath)
            root = tree.getroot()
            api_name = _text(root, "fullName") or fname.replace(".field-meta.xml", "")
            label = _text(root, "label") or api_name
            ftype = _text(root, "type") or "Text"
            result[api_name] = {
                "label": label,
                "type": ftype,
                "required": _text(root, "required") == "true",
                "referenceTo": _text(root, "referenceTo"),
            }
        except ET.ParseError:
            continue

    return result


def find_layouts(layouts_dir: str, sobject_name: str) -> list[str]:
    """Trouve tous les fichiers layout pour un SObject donné."""
    results = []
    if not os.path.isdir(layouts_dir):
        return results
    prefix = sobject_name + "-"
    for fname in sorted(os.listdir(layouts_dir)):
        if fname.startswith(prefix) and fname.endswith(".layout-meta.xml"):
            results.append(os.path.join(layouts_dir, fname))
    return results


def get_default_layout(layouts_dir: str, sobject_name: str) -> Optional[PageLayout]:
    """Charge le premier layout disponible pour un SObject."""
    paths = find_layouts(layouts_dir, sobject_name)
    if not paths:
        return None
    return parse_layout(paths[0])


# ============================================================
# ListView parsing
# ============================================================

# Mapping des noms de colonnes SFDX listView → champ PG
# Les listViews utilisent OBJECT.FIELD ou des noms spéciaux
LISTVIEW_COLUMN_MAP = {
    # Account
    "ACCOUNT.NAME": "name",
    "ACCOUNT.PHONE1": "phone",
    "ACCOUNT.TYPE": "type",
    "ACCOUNT.ADDRESS1_CITY": "billingcity",
    "ACCOUNT.ADDRESS1_STATE": "billingstate",
    "ACCOUNT.ADDRESS1_ZIP": "billingpostalcode",
    "ACCOUNT.CREATED_DATE": "createddate",
    "ACCOUNT.LAST_UPDATE": "lastmodifieddate",
    "ACCOUNT.ACCOUNT_NUMBER": "accountnumber",
    "ACCOUNT.INDUSTRY": "industry",
    "ACCOUNT.SITE": "site",
    # Contact
    "FULL_NAME": "name",
    "CONTACT.FIRST_NAME": "firstname",
    "CONTACT.LAST_NAME": "lastname",
    "CONTACT.TITLE": "title",
    "CONTACT.PHONE1": "phone",
    "CONTACT.PHONE3": "mobilephone",
    "CONTACT.EMAIL": "email",
    "CONTACT.CREATED_DATE": "createddate",
    "CONTACT.BIRTHDATE": "birthdate",
    "CONTACT.ACCOUNT_NAME": "accountid",
    # Contract
    "CONTRACT.CONTRACT_NUMBER": "contractnumber",
    "CONTRACT.NAME": "name",
    "CONTRACT.STATUS": "status",
    "CONTRACT.START_DATE": "startdate",
    "CONTRACT.END_DATE": "enddate",
    "CONTRACT.CREATED_DATE": "createddate",
    "CUSTOMER_SIGNED_DATE": "customersigneddate",
    # Opportunity
    "OPPORTUNITY.NAME": "name",
    "OPPORTUNITY.STAGE_NAME": "stagename",
    "OPPORTUNITY.AMOUNT": "amount",
    "OPPORTUNITY.CLOSE_DATE": "closedate",
    "OPPORTUNITY.CREATED_DATE": "createddate",
    "OPPORTUNITY.TYPE": "type",
    "OPPORTUNITY.RECORDTYPE": "recordtypeid",
    # Common
    "SALES.ACCOUNT.NAME": "accountid",
    "CORE.USERS.ALIAS": "ownerid",
    "CORE.USERS.FULL_NAME": "ownerid",
    "RECORDTYPE": "recordtypeid",
    "CREATED_DATE": "createddate",
    "LAST_UPDATE": "lastmodifieddate",
}


@dataclass
class ListViewFilter:
    field: str = ""
    operation: str = ""
    value: str = ""


@dataclass
class ListViewDef:
    name: str = ""
    label: str = ""
    columns: list[str] = field(default_factory=list)
    pg_columns: list[str] = field(default_factory=list)
    column_labels: dict[str, str] = field(default_factory=dict)
    filter_scope: str = "Everything"
    filters: list[ListViewFilter] = field(default_factory=list)
    boolean_filter: Optional[str] = None


def _resolve_column(col_name: str) -> str:
    """Convertit un nom de colonne listView en nom de colonne PG."""
    if col_name in LISTVIEW_COLUMN_MAP:
        return LISTVIEW_COLUMN_MAP[col_name]
    # Custom fields: juste lowercase
    return col_name.lower()


def _column_label(col_name: str) -> str:
    """Génère un label lisible depuis un nom de colonne listView."""
    if col_name in LISTVIEW_COLUMN_MAP:
        # Utiliser la partie après le dernier point
        parts = col_name.split(".")
        return parts[-1].replace("_", " ").title()
    return col_name.replace("__c", "").replace("_", " ")


def parse_listview(path: str) -> ListViewDef:
    """Parse un fichier .listView-meta.xml."""
    tree = ET.parse(path)
    root = tree.getroot()

    lv = ListViewDef()
    lv.name = _text(root, "fullName") or ""
    lv.label = _text(root, "label") or lv.name
    lv.filter_scope = _text(root, "filterScope") or "Everything"
    lv.boolean_filter = _text(root, "booleanFilter")

    # Colonnes (dédupliquées)
    seen_pg = set()
    for col_el in root.findall(_tag("columns")):
        if col_el.text:
            col_name = col_el.text.strip()
            pg_col = _resolve_column(col_name)
            if pg_col not in seen_pg:
                seen_pg.add(pg_col)
                lv.columns.append(col_name)
                lv.pg_columns.append(pg_col)
                lv.column_labels[pg_col] = _column_label(col_name)

    # Filtres
    for f_el in root.findall(_tag("filters")):
        filt = ListViewFilter()
        filt.field = _text(f_el, "field") or ""
        filt.operation = _text(f_el, "operation") or ""
        filt.value = _text(f_el, "value") or ""
        lv.filters.append(filt)

    return lv


def load_listviews(objects_dir: str, sobject_name: str) -> list[ListViewDef]:
    """Charge toutes les listViews d'un SObject."""
    lv_dir = os.path.join(objects_dir, sobject_name, "listViews")
    results = []
    if not os.path.isdir(lv_dir):
        return results
    for fname in sorted(os.listdir(lv_dir)):
        if fname.endswith(".listView-meta.xml"):
            try:
                lv = parse_listview(os.path.join(lv_dir, fname))
                results.append(lv)
            except ET.ParseError:
                continue
    return results


def get_default_listview(objects_dir: str, sobject_name: str) -> Optional[ListViewDef]:
    """Retourne la listView par défaut (All*, Tous*, ou la plus complète)."""
    lvs = load_listviews(objects_dir, sobject_name)
    if not lvs:
        return None
    # Chercher "All*" ou "Tous *" d'abord
    for lv in lvs:
        if lv.name.startswith("All") or lv.label.lower().startswith("tous"):
            if lv.pg_columns:  # Skip les vues sans colonnes
                return lv
    # Sinon la vue avec le plus de colonnes
    best = max(lvs, key=lambda lv: len(lv.pg_columns))
    return best if best.pg_columns else lvs[0]
