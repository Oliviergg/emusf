"""Schema registry - simule le DescribeSObjectResult de Salesforce."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RelationshipMeta:
    plural_name: str
    sobject_name: str
    fk_column: str
    parent_sobject: str


class SchemaRegistry:
    """
    Simule le Schema de Salesforce.
    En vrai : Salesforce le charge depuis ses métadonnées internes.
    """

    def __init__(self):
        self._relationships: dict = {}

    def register(self, meta: RelationshipMeta):
        key = "{}.{}".format(meta.parent_sobject, meta.plural_name).lower()
        self._relationships[key] = meta

    def resolve(
        self, plural_name: str, parent_sobject: str
    ) -> Optional[RelationshipMeta]:
        key = "{}.{}".format(parent_sobject, plural_name).lower()
        return self._relationships.get(key)
