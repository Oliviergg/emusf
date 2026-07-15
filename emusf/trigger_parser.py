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

    def make_callback(stmts, shared_classes, event):
        # event : 'before_insert', 'after_update', …
        timing, _, operation = event.partition("_")
        is_before = timing == "before"

        def callback(records, old_records=None):
            interp = ApexInterpreter(org)
            if shared_classes:
                for cls_name, cls_def in shared_classes.items():
                    interp.classes[cls_name] = cls_def
                    for cname, (ctype, expr) in cls_def.constants.items():
                        if cname in cls_def.instance_fields:
                            continue
                        # Une constante qui plante (méthode non émulée…) ne doit
                        # pas faire échouer tout DML : celle-là vaudra null.
                        try:
                            interp.variables["{}.{}".format(cls_name, cname)] = (
                                interp._eval(expr) if expr is not None else None)
                        except Exception:
                            interp.variables["{}.{}".format(cls_name, cname)] = None
            new_list = records or []
            old_list = old_records or []
            interp.variables["Trigger"] = {
                "new": new_list,
                "old": old_list,
                "newMap": {r.get("Id"): r for r in new_list
                           if isinstance(r, dict) and r.get("Id")},
                "oldMap": {r.get("Id"): r for r in old_list
                           if isinstance(r, dict) and r.get("Id")},
                "isExecuting": True,
                "isBefore": is_before,
                "isAfter": not is_before,
                "isInsert": operation == "insert",
                "isUpdate": operation == "update",
                "isDelete": operation == "delete",
                "isUndelete": operation == "undelete",
                "operationType": event.upper(),  # BEFORE_INSERT, …
                "size": len(new_list or old_list),
            }
            for stmt in stmts:
                interp._exec_stmt(stmt)
        return callback

    for event in events:
        org.add_trigger(event, sobject, make_callback(body_stmts, classes, event))

    print("TRIGGER: {} chargé sur {} ({})".format(name, sobject, ", ".join(events)))
