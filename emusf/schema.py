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
        self._parent_lookups: dict = {}  # child.fk_stem → RelationshipMeta

    def register(self, meta: RelationshipMeta):
        key = "{}.{}".format(meta.parent_sobject, meta.plural_name).lower()
        self._relationships[key] = meta
        # Index inverse pour les parent relationship traversals (__r)
        # Le __r en SOQL correspond au nom du champ FK sans __c
        # Ex: champ FK "LLM_Prompt__c" → accès parent via "LLM_Prompt__r"
        fk_stem = meta.fk_column
        if fk_stem.lower().endswith("__c"):
            fk_stem = fk_stem[:-3]  # "LLM_Prompt__c" → "LLM_Prompt"
        elif fk_stem.lower().endswith("id"):
            fk_stem = fk_stem[:-2]  # "AccountId" → "Account"
        child_key = "{}.{}".format(meta.sobject_name, fk_stem).lower()
        self._parent_lookups[child_key] = meta

    def resolve(
        self, plural_name: str, parent_sobject: str
    ) -> Optional[RelationshipMeta]:
        key = "{}.{}".format(parent_sobject, plural_name).lower()
        return self._relationships.get(key)

    def resolve_parent(
        self, rel_name: str, child_sobject: str
    ) -> Optional[RelationshipMeta]:
        """Résout une relation parent (__r) depuis un SObject enfant.
        rel_name est le nom sans le suffixe __r (ex: 'LLM_Prompt').
        """
        key = "{}.{}".format(child_sobject, rel_name).lower()
        return self._parent_lookups.get(key)
