"""SOQL parser with subquery support."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SOQLQuery:
    fields: list
    sobject: str
    where: Optional[str] = None
    subqueries: dict = field(default_factory=dict)
    limit: Optional[int] = None
    order_by: Optional[str] = None


def extract_subqueries(select_clause: str) -> tuple:
    """
    Sépare les champs normaux des sous-requêtes.
    'Id, Name, (SELECT Id, LastName FROM Contacts)'
    → fields: ['Id', 'Name']
    → subqueries: {'Contacts': SOQLQuery(...)}
    """
    fields = []
    subqueries = {}

    depth = 0
    current = ""

    for char in select_clause:
        if char == "(":
            depth += 1
            current += char
        elif char == ")":
            depth -= 1
            current += char
            if depth == 0:
                inner = current.strip()[1:-1]
                sub = parse_soql(inner)
                subqueries[sub.sobject] = sub
                current = ""
        elif char == "," and depth == 0:
            f = current.strip()
            if f:
                fields.append(f)
            current = ""
        else:
            current += char

    if current.strip():
        fields.append(current.strip())

    return fields, subqueries


def _find_top_level_from(soql: str) -> int:
    """Trouve la position du FROM de niveau supérieur (hors parenthèses)."""
    depth = 0
    upper = soql.upper()
    for i, char in enumerate(soql):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and upper[i:i + 5] == "FROM ":
            return i
    return -1


def parse_soql(soql: str, context: Optional[dict] = None) -> SOQLQuery:
    """
    Parse un SOQL simple ou avec sous-requêtes.
    Supporte les bind variables (:varName) résolues depuis context.
    """
    if context is None:
        context = {}

    soql = soql.strip().lstrip("[").rstrip("]").strip()

    # Strip Salesforce-specific clauses not supported by PG
    soql = re.sub(r'\bWITH\s+(?:SYSTEM_MODE|USER_MODE|SECURITY_ENFORCED)\b', '', soql, flags=re.IGNORECASE).strip()

    # Handle SELECT COUNT() FROM ... — special aggregate
    count_match = re.match(r'SELECT\s+COUNT\(\)\s+FROM\s+', soql, re.IGNORECASE)
    is_count_query = count_match is not None

    # Trouver le FROM principal (hors parenthèses)
    from_pos = _find_top_level_from(soql)
    raw_select = soql[len("SELECT "):from_pos].strip()
    if is_count_query:
        fields = ["COUNT()"]
        subqueries = {}
    else:
        fields, subqueries = extract_subqueries(raw_select)

    # Le reste après FROM
    after_from = soql[from_pos + 5:].strip()
    from_match = re.match(r"(\w+)", after_from)
    sobject = from_match.group(1)

    # Parse le reste : WHERE ... ORDER BY ... LIMIT ...
    remainder = after_from[from_match.end():].strip()

    # Extraire LIMIT
    limit_val = None
    limit_match = re.search(r'\bLIMIT\s+(\d+)\s*$', remainder, re.IGNORECASE)
    if limit_match:
        limit_val = int(limit_match.group(1))
        remainder = remainder[:limit_match.start()].strip()

    # Extraire ORDER BY
    order_by = None
    order_match = re.search(r'\bORDER\s+BY\s+(.+)$', remainder, re.IGNORECASE)
    if order_match:
        order_by = order_match.group(1).strip()
        remainder = remainder[:order_match.start()].strip()

    # WHERE
    where_clause = None
    where_match = re.match(r"WHERE\s+(.+)$", remainder, re.IGNORECASE | re.DOTALL)
    if where_match:
        where_clause = where_match.group(1)

        def resolve_bind(match):
            path = match.group(1)
            # Try full dotted path first (e.g., ClassName.CONSTANT)
            if path in context:
                value = context[path]
            else:
                parts = path.split(".")
                value = context.get(parts[0])
                for part in parts[1:]:
                    if isinstance(value, dict):
                        # Case-insensitive lookup
                        found = value.get(part)
                        if found is None:
                            for k, v in value.items():
                                if k.lower() == part.lower():
                                    found = v
                                    break
                        value = found
                    else:
                        value = None
                        break
            if value is None:
                return "NULL"
            if isinstance(value, str):
                return "'{}'".format(value.replace("'", "''"))
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, (int, float)):
                return str(value)
            if isinstance(value, dict):
                # Date dict → 'YYYY-MM-DD'
                if value.get("_type") == "Date":
                    return "'{}-{:02d}-{:02d}'".format(value["year"], value["month"], value["day"])
                # SObject with Id
                if "Id" in value or "id" in value:
                    return "'{}'".format(value.get("Id", value.get("id", "")))
            if isinstance(value, (list, set)):
                # IN clause: convert to ('val1', 'val2')
                vals = ", ".join("'{}'".format(v) for v in value)
                return "({})".format(vals) if vals else "('')"
            return "'{}'".format(str(value))

        where_clause = re.sub(r":([\w.]+)", resolve_bind, where_clause)

    return SOQLQuery(
        fields=fields,
        sobject=sobject,
        where=where_clause,
        subqueries=subqueries,
        limit=limit_val,
        order_by=order_by,
    )
