"""Test runner pour fichiers Apex avec assertions formalisées.

Convention : les fichiers .cls de test utilisent System.assert() et System.assertEquals().
Le runner exécute et vérifie les assertions automatiquement.
"""

from __future__ import annotations

import os
import glob
import sys

from .apex_parser import ApexParser
from .interpreter import ApexInterpreter, ReturnException
from .ast_nodes import MethodCall, MethodCallStmt


# Couleurs
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class AssertionError(Exception):
    pass


class ApexTestInterpreter(ApexInterpreter):
    """Interpréteur étendu avec support de System.assert / System.assertEquals."""

    def __init__(self, org):
        super().__init__(org)
        self.assertions_passed = 0
        self.assertions_failed = 0
        self.failures = []

    def _exec_method_call(self, call: MethodCall):
        args = [self._eval(a) for a in call.args]

        # System.assert(condition)
        if call.obj == "System" and call.method == "assert":
            self._do_assert(args)
            return None

        # System.assertEquals(expected, actual)
        if call.obj == "System" and call.method == "assertEquals":
            self._do_assert_equals(args)
            return None

        # System.assertNotEquals(expected, actual)
        if call.obj == "System" and call.method == "assertNotEquals":
            self._do_assert_not_equals(args)
            return None

        return super()._exec_method_call(call)

    def _do_assert(self, args):
        condition = args[0] if args else False
        msg = args[1] if len(args) > 1 else ""
        if self._is_truthy(condition):
            self.assertions_passed += 1
        else:
            self.assertions_failed += 1
            self.failures.append("assert failed: {}".format(msg or "condition is false"))

    def _do_assert_equals(self, args):
        expected = args[0] if args else None
        actual = args[1] if len(args) > 1 else None
        msg = args[2] if len(args) > 2 else ""
        if expected == actual:
            self.assertions_passed += 1
        else:
            self.assertions_failed += 1
            self.failures.append(
                "assertEquals failed: expected={}, actual={}{}".format(
                    repr(expected), repr(actual),
                    " — " + str(msg) if msg else ""
                )
            )

    def _do_assert_not_equals(self, args):
        expected = args[0] if args else None
        actual = args[1] if len(args) > 1 else None
        if expected != actual:
            self.assertions_passed += 1
        else:
            self.assertions_failed += 1
            self.failures.append(
                "assertNotEquals failed: both are {}".format(repr(expected))
            )


def run_test_file(path: str, org, method: str = "run") -> dict:
    """Exécute un fichier .cls de test et retourne les résultats."""
    with open(path) as f:
        source = f.read()

    parser = ApexParser()
    ast = parser.parse_class(source, method)

    interp = ApexTestInterpreter(org)
    try:
        interp._exec_block(ast)
    except Exception as e:
        interp.assertions_failed += 1
        interp.failures.append("Runtime error: {}".format(e))

    return {
        "file": os.path.basename(path),
        "passed": interp.assertions_passed,
        "failed": interp.assertions_failed,
        "failures": interp.failures,
        "output": interp.output,
    }


def run_test_dir(test_dir: str, org, pattern: str = "Test*.cls") -> bool:
    """Exécute tous les fichiers de test d'un répertoire."""
    files = sorted(glob.glob(os.path.join(test_dir, pattern)))
    if not files:
        print(YELLOW + "Aucun fichier de test trouvé: {}".format(
            os.path.join(test_dir, pattern)
        ) + RESET)
        return True

    total_passed = 0
    total_failed = 0
    all_ok = True

    for path in files:
        result = run_test_file(path, org)
        passed = result["passed"]
        failed = result["failed"]
        total_passed += passed
        total_failed += failed

        if failed == 0:
            status = GREEN + "PASS" + RESET
        else:
            status = RED + "FAIL" + RESET
            all_ok = False

        print("  {} {} — {} assertions".format(
            status, result["file"], passed + failed
        ))

        for f in result["failures"]:
            print("    " + RED + "✗ " + f + RESET)

    print()
    summary = "{}Total: {} passed, {} failed{}".format(
        BOLD, total_passed, total_failed, RESET
    )
    if all_ok:
        print(GREEN + "✓ " + RESET + summary)
    else:
        print(RED + "✗ " + RESET + summary)

    return all_ok
