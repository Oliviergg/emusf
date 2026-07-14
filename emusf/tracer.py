"""Traceur d'exécution de l'interpréteur Apex.

Instrumente ApexInterpreter et PgOrg par monkey-patching pour afficher, à
l'exécution, chaque appel de méthode, statement, requête SOQL et opération DML,
indentés par profondeur d'appel. N'altère aucun comportement : chaque wrapper
délègue à la méthode d'origine.

Activation : `run.py --trace`. Réversible via uninstall().
"""

from __future__ import annotations

from . import interpreter as _interp
from .pg_org import PgOrg

DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
RESET = "\033[0m"

# Expressions dignes d'être tracées (les littéraux/variables seraient du bruit)
_EVAL_INTEREST = {"MethodCall", "ChainedCall", "SOQLAssign"}

_state = {"installed": False, "depth": 0, "orig": {}, "level": "normal"}


def _pad():
    return DIM + "│ " * _state["depth"] + RESET


def _short(value, n=70):
    text = repr(value)
    return text if len(text) <= n else text[:n] + "…"


def install(level: str = "normal"):
    """Active la trace. level='normal' (méthodes+statements+SOQL+DML) ou
    'verbose' (ajoute chaque expression évaluée)."""
    if _state["installed"]:
        return
    _state["level"] = level
    orig = _state["orig"]

    orig["exec"] = _interp.ApexInterpreter._exec_stmt
    orig["invoke"] = _interp.ApexInterpreter._invoke_method
    orig["invoke_inst"] = _interp.ApexInterpreter._invoke_instance_method
    orig["eval"] = _interp.ApexInterpreter._eval
    orig["soql"] = PgOrg.execute_soql

    def traced_exec(self, stmt):
        kind = type(stmt).__name__
        if kind not in ("Block",):  # Block n'est qu'un conteneur
            line = getattr(stmt, "line", None)
            cls = self._current_class.name if self._current_class else "?"
            loc = "{}{}:{}{} ".format(DIM, cls, line, RESET) if line else ""
            print("{}{}{}▸{} {}".format(_pad(), loc, CYAN, RESET, kind))
        return orig["exec"](self, stmt)

    def _traced_call(orig_fn, label_of):
        def wrapper(self, *a):
            label = label_of(*a)
            print("{}{}→ {}{}".format(_pad(), GREEN, label, RESET))
            _state["depth"] += 1
            try:
                result = orig_fn(self, *a)
            finally:
                _state["depth"] -= 1
            print("{}{}← {} = {}{}".format(
                _pad(), DIM, label, _short(result), RESET))
            return result
        return wrapper

    def _method_label(class_def, method_def, args):
        return "{}.{}({})".format(class_def.name, method_def.name,
                                  ", ".join(_short(x, 24) for x in args))

    def _inst_label(instance, method_def, args):
        cls = instance.get("_type", "?") if isinstance(instance, dict) else "?"
        return "{}#{}({})".format(cls, method_def.name,
                                  ", ".join(_short(x, 24) for x in args))

    def traced_eval(self, expr):
        result = orig["eval"](self, expr)
        if _state["level"] == "verbose" or type(expr).__name__ in _EVAL_INTEREST:
            kind = type(expr).__name__
            if kind in _EVAL_INTEREST or _state["level"] == "verbose":
                print("{}{}  ={} {} {}{}".format(
                    _pad(), MAGENTA, RESET, kind, _short(result), ""))
        return result

    def traced_soql(self, soql, context=None):
        rows = orig["soql"](self, soql, context)
        q = " ".join(str(soql).split())
        print("{}{}⛁ SOQL{} {} {}→ {} ligne(s){}".format(
            _pad(), BLUE, RESET, q[:90], DIM, len(rows), RESET))
        return rows

    _interp.ApexInterpreter._exec_stmt = traced_exec
    _interp.ApexInterpreter._invoke_method = _traced_call(orig["invoke"], _method_label)
    _interp.ApexInterpreter._invoke_instance_method = _traced_call(
        orig["invoke_inst"], _inst_label)
    _interp.ApexInterpreter._eval = traced_eval
    PgOrg.execute_soql = traced_soql

    _state["installed"] = True
    print("{}[trace activée — niveau {}]{}".format(YELLOW, level, RESET))


def uninstall():
    """Restaure les méthodes d'origine."""
    if not _state["installed"]:
        return
    orig = _state["orig"]
    _interp.ApexInterpreter._exec_stmt = orig["exec"]
    _interp.ApexInterpreter._invoke_method = orig["invoke"]
    _interp.ApexInterpreter._invoke_instance_method = orig["invoke_inst"]
    _interp.ApexInterpreter._eval = orig["eval"]
    PgOrg.execute_soql = orig["soql"]
    _state["installed"] = False
    _state["depth"] = 0
