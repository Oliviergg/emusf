"""Flask app — Affichage d'objets Salesforce avec SLDS."""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal

import re
import xml.etree.ElementTree as ET

from flask import Flask, render_template, request, abort, redirect, url_for
from markupsafe import Markup

from emusf.pg_org import PgOrg
from emusf.sfdx_loader import load_sobject_meta
from emusf.layout_parser import (
    parse_layout,
    load_field_labels,
    find_layouts,
    get_default_layout,
    load_listviews,
    get_default_listview,
    ListViewDef,
    PageLayout,
)

# --- Config ---
DSN = "host=localhost port=6000 user=postgres password=dcc948df3501919f709cb976fa2cb24000be8b12 dbname=biup"
SFDX_BASE = "/Users/olivier/Dev/btp/sf-btp/force-app/main/default"
OBJECTS_DIR = os.path.join(SFDX_BASE, "objects")
LAYOUTS_DIR = os.path.join(SFDX_BASE, "layouts")

# SObjects supportés avec leur layout par défaut
SOBJECT_CONFIG = {
    "Account": {
        "layout": "Account-Client.layout-meta.xml",
        "label": "Compte",
        "icon": "standard:account",
        "name_field": "Name",
    },
    "Contract": {
        "layout": "Contract-Présentation du contrat.layout-meta.xml",
        "label": "Contrat",
        "icon": "standard:contract",
        "name_field": "Name",
    },
    "Contact": {
        "layout": None,  # auto-detect
        "label": "Contact",
        "icon": "standard:contact",
        "name_field": "Name",
    },
    "Opportunity": {
        "layout": None,
        "label": "Opportunité",
        "icon": "standard:opportunity",
        "name_field": "Name",
    },
}

# --- App ---
app = Flask(__name__)
org = PgOrg(DSN, schema="data")

# Cache: field labels par SObject
_field_labels_cache: dict[str, dict] = {}
_layout_cache: dict[str, PageLayout] = {}


def get_field_labels(sobject: str) -> dict:
    """Retourne les labels, indexés aussi en lowercase pour le matching PG."""
    if sobject not in _field_labels_cache:
        raw = load_field_labels(OBJECTS_DIR, sobject)
        # Ajouter les entrées lowercase pour matcher les colonnes PG
        merged = {}
        for k, v in raw.items():
            merged[k] = v
            merged[k.lower()] = v
        _field_labels_cache[sobject] = merged
    return _field_labels_cache[sobject]


def get_layout(sobject: str) -> PageLayout | None:
    if sobject in _layout_cache:
        return _layout_cache[sobject]

    config = SOBJECT_CONFIG.get(sobject, {})
    layout_file = config.get("layout")

    if layout_file:
        path = os.path.join(LAYOUTS_DIR, layout_file)
        if os.path.exists(path):
            layout = parse_layout(path)
        else:
            layout = get_default_layout(LAYOUTS_DIR, sobject)
    else:
        layout = get_default_layout(LAYOUTS_DIR, sobject)

    if layout:
        _layout_cache[sobject] = layout
    return layout


def fetch_record(sobject: str, record_id: str) -> dict | None:
    """Récupère un enregistrement par son Id."""
    import psycopg2.extras
    pg_table = sobject.lower()
    pg_cols = org.get_columns(pg_table)
    if not pg_cols:
        return None

    select = ", ".join(pg_cols)
    cur = org.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            "SELECT {} FROM data.{} WHERE id = %s".format(select, pg_table),
            [record_id],
        )
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception:
        return None
    finally:
        cur.close()


def fetch_list(sobject: str, limit: int = 50, offset: int = 0,
               order_by: str = "id", search: str = "") -> tuple[list[dict], int]:
    """Récupère une liste d'enregistrements."""
    pg_cols = org.get_columns(sobject)
    if not pg_cols:
        return [], 0

    # Sélectionner un sous-ensemble utile de colonnes
    select_cols = pg_cols[:20]  # limiter pour la perf

    where = ""
    if search:
        # Recherche sur name
        where = " WHERE name ILIKE '%{}%'".format(search.replace("'", "''"))

    # Count
    count_sql = "SELECT count(*) FROM data.{}{}"
    cur = org.conn.cursor()
    cur.execute(count_sql.format(sobject.lower(), where))
    total = cur.fetchone()[0]
    cur.close()

    soql = "SELECT {} FROM {}{} ORDER BY {} LIMIT {} OFFSET {}".format(
        ", ".join(select_cols), sobject.lower(), where,
        order_by.lower(), limit, offset
    )
    cur = org.conn.cursor()
    try:
        import psycopg2.extras
        cur = org.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT {} FROM data.{}{} ORDER BY {} LIMIT {} OFFSET {}".format(
            ", ".join(select_cols), sobject.lower(), where,
            order_by.lower(), limit, offset
        ))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception:
        rows = []

    return rows, total


def format_value(value, field_type: str = "Text") -> str:
    """Formate une valeur pour l'affichage HTML."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, Decimal):
        if field_type in ("Currency",):
            return "{:,.2f} €".format(value)
        return str(value)
    if isinstance(value, float):
        if field_type in ("Currency",):
            return "{:,.2f} €".format(value)
        return str(value)
    return str(value)


# --- SVG icon helper ---
SLDS_DIR = os.path.join(os.path.dirname(__file__), "static", "slds")
_svg_cache: dict[str, str] = {}


def _extract_symbol(sprite_path: str, symbol_id: str) -> str:
    """Extrait un <symbol> du sprite SVG et le retourne comme <svg> inline."""
    cache_key = "{}#{}".format(sprite_path, symbol_id)
    if cache_key in _svg_cache:
        return _svg_cache[cache_key]

    try:
        tree = ET.parse(sprite_path)
        root = tree.getroot()
        ns = {"svg": "http://www.w3.org/2000/svg"}
        for sym in root.iter("{http://www.w3.org/2000/svg}symbol"):
            if sym.get("id") == symbol_id:
                vb = sym.get("viewBox", "0 0 100 100")
                inner = "".join(
                    ET.tostring(child, encoding="unicode") for child in sym
                )
                svg = '<svg viewBox="{}" aria-hidden="true">{}</svg>'.format(vb, inner)
                _svg_cache[cache_key] = svg
                return svg
        # Also check without namespace
        for sym in root.iter("symbol"):
            if sym.get("id") == symbol_id:
                vb = sym.get("viewBox", "0 0 100 100")
                inner = "".join(
                    ET.tostring(child, encoding="unicode") for child in sym
                )
                svg = '<svg viewBox="{}" aria-hidden="true">{}</svg>'.format(vb, inner)
                _svg_cache[cache_key] = svg
                return svg
    except Exception:
        pass
    _svg_cache[cache_key] = ""
    return ""


def slds_icon(category: str, name: str, size: str = "", extra_class: str = "") -> Markup:
    """
    Génère le markup SLDS complet pour une icône.
    category: standard, utility, action, custom, doctype
    name: account, contract, check, close, etc.
    size: x-small, small, medium, large (vide = default)
    """
    sprite_path = os.path.join(SLDS_DIR, "icons", category + "-sprite", "svg", "symbols.svg")
    svg_content = _extract_symbol(sprite_path, name)

    size_class = " slds-icon_{}".format(size) if size else ""
    icon_classes = "slds-icon{}{}".format(size_class, " " + extra_class if extra_class else "")

    if category == "utility":
        container_class = "slds-icon_container slds-icon-utility-{}".format(name.replace("_", "-"))
    else:
        container_class = "slds-icon_container slds-icon-{}-{}".format(
            category, name.replace("_", "-")
        )

    svg_with_class = svg_content.replace("<svg ", '<svg class="{}" '.format(icon_classes), 1)

    html = '<span class="{}">{}</span>'.format(container_class, svg_with_class)
    return Markup(html)


# --- Jinja helpers ---
@app.template_filter("sfvalue")
def sf_value_filter(value, field_type="Text"):
    return format_value(value, field_type)


@app.context_processor
def inject_globals():
    return {
        "sobject_config": SOBJECT_CONFIG,
        "slds_icon": slds_icon,
    }


# --- Routes ---

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/account/<record_id>")
def account_detail(record_id):
    return record_detail_view("Account", record_id)


@app.route("/contract/<record_id>")
def contract_detail(record_id):
    return record_detail_view("Contract", record_id)


@app.route("/contact/<record_id>")
def contact_detail(record_id):
    return record_detail_view("Contact", record_id)


@app.route("/opportunity/<record_id>")
def opportunity_detail(record_id):
    return record_detail_view("Opportunity", record_id)


@app.route("/sobject/<sobject>/<record_id>")
def generic_detail(sobject, record_id):
    sobject = _normalize_sobject(sobject)
    return record_detail_view(sobject, record_id)


@app.route("/account")
def account_list():
    return list_view("Account")


@app.route("/contract")
def contract_list():
    return list_view("Contract")


@app.route("/contact")
def contact_list():
    return list_view("Contact")


@app.route("/opportunity")
def opportunity_list():
    return list_view("Opportunity")


@app.route("/sobject/<sobject>")
def generic_list(sobject):
    sobject = _normalize_sobject(sobject)
    return list_view(sobject)


@app.route("/search")
def global_search():
    """Recherche globale sur plusieurs SObjects."""
    q = request.args.get("q", "").strip()
    results = {}
    if q:
        for sobj in ["Account", "Contact", "Contract", "Opportunity"]:
            pg_cols = org.get_columns(sobj)
            if not pg_cols or "name" not in pg_cols:
                continue
            import psycopg2.extras
            cur = org.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cur.execute(
                    "SELECT id, name FROM data.{} WHERE name ILIKE %s LIMIT 5".format(
                        sobj.lower()
                    ),
                    ["%{}%".format(q)],
                )
                rows = [dict(r) for r in cur.fetchall()]
                if rows:
                    results[sobj] = rows
            except Exception:
                pass
            finally:
                cur.close()

    return render_template("search.html", q=q, results=results)


@app.route("/objects")
def objects_index():
    """Liste tous les SObjects disponibles en PG."""
    tables = sorted(org._tables.keys())
    table_info = []
    for t in tables:
        if t.startswith("_"):
            continue
        table_info.append({
            "name": t,
            "col_count": len(org._tables[t]),
            "has_layout": bool(find_layouts(LAYOUTS_DIR, t.capitalize()) or
                              find_layouts(LAYOUTS_DIR, t)),
        })
    return render_template("objects_index.html", tables=table_info)


@app.route("/account/<record_id>/edit")
def account_edit(record_id):
    return record_edit_view("Account", record_id)


@app.route("/contract/<record_id>/edit")
def contract_edit(record_id):
    return record_edit_view("Contract", record_id)


@app.route("/contact/<record_id>/edit")
def contact_edit(record_id):
    return record_edit_view("Contact", record_id)


@app.route("/opportunity/<record_id>/edit")
def opportunity_edit(record_id):
    return record_edit_view("Opportunity", record_id)


@app.route("/sobject/<sobject>/<record_id>/edit")
def generic_edit(sobject, record_id):
    sobject = _normalize_sobject(sobject)
    return record_edit_view(sobject, record_id)


@app.route("/save/<sobject>/<record_id>", methods=["POST"])
def save_record(sobject, record_id):
    """Sauvegarde les modifications d'un enregistrement."""
    import psycopg2.extras
    sobject = _normalize_sobject(sobject)
    pg_table = sobject.lower()
    pg_cols = set(org.get_columns(pg_table))

    # Collecter les champs modifiés depuis le formulaire
    updates = {}
    for key, val in request.form.items():
        if key.startswith("_"):
            continue
        col = key.lower()
        if col in pg_cols and col != "id":
            # Convertir les valeurs vides en None
            updates[col] = val if val.strip() != "" else None

    if updates:
        set_clause = ", ".join("{} = %s".format(k) for k in updates.keys())
        values = list(updates.values()) + [record_id]
        cur = org.conn.cursor()
        try:
            cur.execute(
                "UPDATE data.{} SET {} WHERE id = %s".format(pg_table, set_clause),
                values,
            )
            org.conn.commit()
        except Exception as e:
            org.conn.rollback()
            abort(500, description=str(e))
        finally:
            cur.close()

    # Rediriger vers le détail
    config = SOBJECT_CONFIG.get(sobject)
    if config:
        return redirect("/{}/{}".format(sobject.lower(), record_id))
    return redirect("/sobject/{}/{}".format(sobject, record_id))


def record_edit_view(sobject: str, record_id: str):
    """Vue édition d'un enregistrement."""
    record = fetch_record(sobject, record_id)
    if not record:
        abort(404)

    layout = get_layout(sobject)
    field_labels = get_field_labels(sobject)
    config = SOBJECT_CONFIG.get(sobject, {
        "label": sobject, "icon": "standard:record", "name_field": "Name",
    })

    name_field = config.get("name_field", "Name")
    record_name = record.get(name_field) or record.get(name_field.lower()) or record_id

    if not layout:
        layout = _build_fallback_layout(sobject, record)

    layout_param = request.args.get("layout")
    if layout_param:
        path = os.path.join(LAYOUTS_DIR, layout_param)
        if os.path.exists(path):
            layout = parse_layout(path)

    return render_template(
        "record_edit.html",
        sobject=sobject,
        config=config,
        record=record,
        record_name=record_name,
        record_id=record_id,
        layout=layout,
        field_labels=field_labels,
    )


def _normalize_sobject(name: str) -> str:
    """Normalise le nom d'un SObject (Account, Contract, etc.)."""
    low = name.lower()
    # Match exact dans les tables PG
    if low in org._tables:
        for sobj in SOBJECT_CONFIG:
            if sobj.lower() == low:
                return sobj
        # Custom objects: garder le nom tel que PG le connaît
        return low
    return name.capitalize()


def record_detail_view(sobject: str, record_id: str):
    """Vue détail d'un enregistrement."""
    record = fetch_record(sobject, record_id)
    if not record:
        abort(404)

    layout = get_layout(sobject)
    field_labels = get_field_labels(sobject)
    config = SOBJECT_CONFIG.get(sobject, {
        "label": sobject, "icon": "standard:record", "name_field": "Name",
    })

    # Nom de l'enregistrement
    name_field = config.get("name_field", "Name")
    record_name = record.get(name_field) or record.get(name_field.lower()) or record_id

    # Construire un layout par défaut si aucun n'est trouvé
    if not layout:
        layout = _build_fallback_layout(sobject, record)

    # Layouts disponibles pour ce SObject
    available_layouts = []
    for path in find_layouts(LAYOUTS_DIR, sobject):
        l = parse_layout(path)
        available_layouts.append({"name": l.name, "path": os.path.basename(path)})

    # Layout override via query param
    layout_param = request.args.get("layout")
    if layout_param:
        path = os.path.join(LAYOUTS_DIR, layout_param)
        if os.path.exists(path):
            layout = parse_layout(path)

    # Charger les données des related lists
    related_data = _fetch_related_lists(layout, record_id, sobject)

    return render_template(
        "record_detail.html",
        sobject=sobject,
        config=config,
        record=record,
        record_name=record_name,
        record_id=record_id,
        layout=layout,
        field_labels=field_labels,
        available_layouts=available_layouts,
        related_data=related_data,
    )


def list_view(sobject: str):
    """Vue liste d'un SObject."""
    import psycopg2.extras

    config = SOBJECT_CONFIG.get(sobject, {
        "label": sobject, "icon": "standard:record", "name_field": "Name",
    })

    # Charger les listViews SFDX
    # Normaliser le nom pour chercher dans SFDX (Account, Contract...)
    sfdx_name = sobject
    for s in SOBJECT_CONFIG:
        if s.lower() == sobject.lower():
            sfdx_name = s
            break
    all_listviews = load_listviews(OBJECTS_DIR, sfdx_name)

    # Sélectionner la listView courante
    lv_param = request.args.get("view")
    current_lv = None
    if lv_param:
        for lv in all_listviews:
            if lv.name == lv_param:
                current_lv = lv
                break
    if not current_lv:
        current_lv = get_default_listview(OBJECTS_DIR, sfdx_name)

    page = int(request.args.get("page", 1))
    per_page = 25
    search = request.args.get("q", "")
    offset = (page - 1) * per_page

    pg_table = sobject.lower()
    pg_cols = org.get_columns(pg_table)
    if not pg_cols:
        pg_cols = []
    pg_cols_set = set(pg_cols)

    # Déterminer les colonnes à afficher
    if current_lv and current_lv.pg_columns:
        # Utiliser les colonnes de la listView, filtrées par ce qui existe en PG
        display_cols = []
        col_labels = {}
        for i, pg_col in enumerate(current_lv.pg_columns):
            if pg_col in pg_cols_set:
                display_cols.append(pg_col)
                col_labels[pg_col] = current_lv.column_labels.get(pg_col, pg_col)
        # Toujours inclure id en premier si absent
        if "id" not in display_cols and "id" in pg_cols_set:
            display_cols.insert(0, "id")
            col_labels["id"] = "ID"
    else:
        display_cols = _get_list_columns_fallback(sobject, pg_cols)
        col_labels = {}

    # Colonnes à SELECT (display + id pour les liens)
    select_cols = list(dict.fromkeys(["id"] + display_cols))
    select_cols = [c for c in select_cols if c in pg_cols_set]

    # WHERE
    where_clause = ""
    where_params = []
    if search:
        if "name" in pg_cols_set:
            where_clause = " WHERE name ILIKE %s"
            where_params = ["%{}%".format(search)]

    # Count
    cur = org.conn.cursor()
    cur.execute("SELECT count(*) FROM data.{}{}".format(pg_table, where_clause), where_params)
    total = cur.fetchone()[0]
    cur.close()
    total_pages = (total + per_page - 1) // per_page

    # Fetch rows
    order_col = "id"
    if "name" in pg_cols_set:
        order_col = "name"
    elif "createddate" in pg_cols_set:
        order_col = "createddate DESC"

    cur = org.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql = "SELECT {} FROM data.{}{} ORDER BY {} LIMIT {} OFFSET {}".format(
        ", ".join(select_cols), pg_table, where_clause,
        order_col, per_page, offset,
    )
    try:
        cur.execute(sql, where_params)
        rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        rows = []
    finally:
        cur.close()

    field_labels = get_field_labels(sfdx_name)
    # Merge listView labels (plus spécifiques)
    if col_labels:
        for k, v in col_labels.items():
            if k not in field_labels:
                field_labels[k] = {"label": v, "type": "Text"}

    return render_template(
        "list_view.html",
        sobject=sobject,
        config=config,
        rows=rows,
        total=total,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        search=search,
        display_cols=display_cols,
        field_labels=field_labels,
        all_listviews=all_listviews,
        current_lv=current_lv,
    )


def _get_list_columns_fallback(sobject: str, pg_cols: list) -> list[str]:
    """Colonnes par défaut quand aucune listView n'est disponible."""
    priority = ["id", "name", "status", "accountid", "type", "phone",
                "email", "website", "createddate", "lastmodifieddate"]
    available = set(pg_cols)
    cols = [c for c in priority if c in available]
    for c in pg_cols:
        if c not in cols and len(cols) < 8:
            cols.append(c)
    return cols


def _build_fallback_layout(sobject: str, record: dict) -> PageLayout:
    """Construit un layout par défaut à partir des colonnes du record."""
    from emusf.layout_parser import PageLayout, LayoutSection, LayoutColumn, LayoutItem

    layout = PageLayout(name="Default", sobject=sobject)
    section = LayoutSection(label="Informations", style="TwoColumnsLeftToRight")
    col1 = LayoutColumn()
    col2 = LayoutColumn()

    keys = [k for k in record.keys() if not k.startswith("_")]
    mid = len(keys) // 2
    for i, k in enumerate(keys):
        item = LayoutItem(field=k, behavior="Readonly")
        if i < mid:
            col1.items.append(item)
        else:
            col2.items.append(item)

    section.columns = [col1, col2]
    layout.sections = [section]
    return layout


def _fetch_related_lists(layout: PageLayout, record_id: str, sobject: str) -> dict:
    """Charge les données des related lists depuis PG."""
    import psycopg2.extras

    related_data = {}
    if not layout.related_lists:
        return related_data

    # Mapping des related lists standard → table PG et FK
    STANDARD_RELATED = {
        "RelatedContactList": ("contact", "accountid"),
        "RelatedContractList": ("contract", "accountid"),
        "RelatedOpportunityList": ("opportunity", "accountid"),
        "RelatedActivityList": None,  # skip
        "RelatedHistoryList": None,
        "RelatedNoteList": None,
        "RelatedContentNoteList": None,
        "RelatedEntityHistoryList": None,
        "RelatedFileList": None,
        "RelatedContractContactRoleList": None,
    }

    for rl in layout.related_lists:
        rl_key = rl.related_list
        rows = []

        try:
            if rl_key in STANDARD_RELATED:
                info = STANDARD_RELATED[rl_key]
                if info is None:
                    continue
                table, fk = info
                pg_cols = org.get_columns(table)
                if not pg_cols:
                    continue
                select = ", ".join(pg_cols[:10])
                cur = org.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    "SELECT {} FROM data.{} WHERE {} = %s LIMIT 10".format(
                        select, table, fk
                    ),
                    [record_id],
                )
                rows = [dict(r) for r in cur.fetchall()]
                cur.close()
            elif "." in rl_key:
                # Custom related list: SObject__c.LookupField__c
                parts = rl_key.split(".")
                child_obj = parts[0].lower()
                fk_field = parts[1].lower()
                pg_cols = org.get_columns(child_obj)
                if not pg_cols:
                    continue
                select = ", ".join(pg_cols[:10])
                cur = org.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    "SELECT {} FROM data.{} WHERE {} = %s LIMIT 10".format(
                        select, child_obj, fk_field
                    ),
                    [record_id],
                )
                rows = [dict(r) for r in cur.fetchall()]
                cur.close()
        except Exception:
            continue

        if rows:
            related_data[rl_key] = rows

    return related_data


# --- Main ---
if __name__ == "__main__":
    app.run(debug=True, port=5001)
