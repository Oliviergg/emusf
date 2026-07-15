"""Parser de triggers Apex → callbacks Python enregistrés sur l'org."""

from __future__ import annotations


class TriggerParser:
    """Parse un fichier .trigger (délègue à la chaîne ANTLR)."""

    def parse_trigger(self, source: str):
        """Parse 'trigger Name on SObject (events) { body }'.
        Retourne (name, sobject, events, body_stmts)."""
        from . import antlr
        return antlr.parse_trigger(source)


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
                        interp.variables["{}.{}".format(cls_name, cname)] = (
                        interp._eval(expr) if expr is not None else None)
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
