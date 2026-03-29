"""Parser de triggers Apex → callbacks Python enregistrés sur l'org."""

from __future__ import annotations

import re

from .apex_parser import ApexParser


EVENT_MAP = {
    "before insert": "before_insert",
    "before update": "before_update",
    "after insert": "after_insert",
    "after update": "after_update",
    "before delete": "before_delete",
    "after delete": "after_delete",
}


class TriggerParser:
    """Parse un fichier .trigger."""

    def __init__(self):
        self.apex_parser = ApexParser()

    def parse_trigger(self, source: str):
        """
        Parse: trigger Name on SObject (event1, event2) { body }
        Retourne (name, sobject, events, body_stmts)
        """
        header_match = re.match(
            r'trigger\s+(\w+)\s+on\s+(\w+)\s*\((.+?)\)\s*\{',
            source, re.DOTALL
        )
        if not header_match:
            raise Exception("Format de trigger invalide")

        name = header_match.group(1)
        sobject = header_match.group(2)
        events_str = header_match.group(3)

        events = []
        for e in events_str.split(","):
            e = e.strip().lower()
            if e in EVENT_MAP:
                events.append(EVENT_MAP[e])

        # Extraire le body
        start = header_match.end()
        depth = 1
        i = start
        while i < len(source) and depth > 0:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1
        body = source[start:i - 1]
        body_stmts = self.apex_parser._parse_block(body)

        return name, sobject, events, body_stmts


def load_trigger(org, path: str, classes: dict = None):
    """Charge un fichier .trigger et enregistre les callbacks sur l'org.

    Args:
        org: L'org (PgTestOrg, etc.)
        path: Chemin vers le fichier .trigger
        classes: Dict {name: ClassDef} de classes pré-chargées,
                 injectées dans l'interpréteur du trigger.
    """
    from .interpreter import ApexInterpreter

    with open(path) as f:
        source = f.read()

    parser = TriggerParser()
    name, sobject, events, body_stmts = parser.parse_trigger(source)

    def make_callback(stmts, shared_classes):
        def callback(records, old_records=None):
            interp = ApexInterpreter(org)
            if shared_classes:
                for cls_name, cls_def in shared_classes.items():
                    interp.classes[cls_name] = cls_def
                    for cname, (ctype, expr) in cls_def.constants.items():
                        interp.variables["{}.{}".format(cls_name, cname)] = interp._eval(expr)
            interp.variables["Trigger"] = {
                "new": records,
                "old": old_records or [],
            }
            for stmt in stmts:
                interp._exec_stmt(stmt)
        return callback

    cb = make_callback(body_stmts, classes)
    for event in events:
        org.add_trigger(event, sobject, cb)

    print("TRIGGER: {} chargé sur {} ({})".format(name, sobject, ", ".join(events)))
