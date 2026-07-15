"""Registre de triggers DML partagé entre les orgs (PgTestOrg, PgDataOrg)."""

from typing import Callable


class TriggerMixin:
    """Enregistrement et déclenchement des triggers before/after par SObject.

    L'org hôte doit initialiser `self._triggers = {}` dans son __init__.
    """

    def add_trigger(self, event: str, sobject: str, callback: Callable):
        if event not in self._triggers:
            self._triggers[event] = {}
        if sobject not in self._triggers[event]:
            self._triggers[event][sobject] = []
        self._triggers[event][sobject].append(callback)

    def _fire_triggers(self, event: str, sobject: str, records: list,
                       old_records: list = None):
        callbacks = self._triggers.get(event, {}).get(sobject, [])
        for cb in callbacks:
            cb(records, old_records=old_records)
