"""
Lance les vrais tests Apex du projet Salesforce sf-btp dans emusf.
Mesure l'avancement : combien de méthodes de test passent.
"""

import os
import re
import sys
import glob

from emusf import FakeOrg, ApexParser
from emusf.interpreter import ApexInterpreter, ReturnException
from emusf.test_runner import ApexTestInterpreter
from emusf.ast_nodes import MethodCallStmt, MethodCall

# Couleurs
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

SF_CLASSES = "/Users/olivier/Dev/btp/sf-btp/force-app/main/default/classes"


class SfTestInterpreter(ApexTestInterpreter):
    """Interpréteur qui ignore Test.startTest(), Test.stopTest(), @isTest etc."""

    def _exec_method_call(self, call):
        # Ignore Test.startTest() / Test.stopTest()
        if call.obj == "Test" and call.method in ("startTest", "stopTest"):
            return None
        return super()._exec_method_call(call)


def load_class_source(class_name):
    """Charge le source d'une classe depuis le repo sf-btp."""
    path = os.path.join(SF_CLASSES, class_name + ".cls")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


def extract_test_methods(source):
    """Extrait les noms des méthodes de test (@isTest ou testMethod)."""
    methods = []
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        # @isTest annotation
        if stripped.lower() in ("@istest", "@istest"):
            for j in range(i + 1, min(i + 5, len(lines))):
                m = re.search(r'(?:static\s+)?void\s+(\w+)\s*\(', lines[j])
                if m:
                    methods.append(m.group(1))
                    break
        # testMethod keyword
        elif "testMethod" in stripped or "testmethod" in stripped:
            m = re.search(r'(?:testMethod|testmethod)\s+void\s+(\w+)\s*\(', stripped)
            if m:
                methods.append(m.group(1))
    return methods


def run_sf_test_class(test_class_name, dependencies=None):
    """
    Charge une classe de test SF et ses dépendances, exécute chaque méthode.
    Retourne {method: {passed, failed, errors}}.
    """
    if dependencies is None:
        dependencies = []

    org = FakeOrg()
    org.create_sobject("Account", {"Name": "TEXT"})

    parser = ApexParser()

    # Charger les dépendances
    for dep in dependencies:
        source = load_class_source(dep)
        if source is None:
            print("  {} Dépendance manquante: {}{}".format(YELLOW, dep, RESET))
            continue
        try:
            class_def = parser.parse_full_class(source)
            # On stocke pour injection dans l'interpréteur
            dependencies_loaded = getattr(run_sf_test_class, '_deps', {})
            dependencies_loaded[dep] = class_def
            run_sf_test_class._deps = dependencies_loaded
        except Exception as e:
            print("  {} Parse error on {}: {}{}".format(YELLOW, dep, e, RESET))

    # Charger la classe de test
    test_source = load_class_source(test_class_name)
    if test_source is None:
        print("  {} Classe de test non trouvée: {}{}".format(RED, test_class_name, RESET))
        return {}

    test_methods = extract_test_methods(test_source)
    if not test_methods:
        print("  {} Aucune méthode @isTest trouvée{}".format(YELLOW, RESET))
        return {}

    results = {}

    for method_name in test_methods:
        interp = SfTestInterpreter(org)

        # Charger les dépendances dans l'interpréteur
        deps = getattr(run_sf_test_class, '_deps', {})
        for name, cls in deps.items():
            interp.classes[name] = cls
            for cname, (ctype, expr) in cls.constants.items():
                try:
                    interp.variables["{}.{}".format(name, cname)] = interp._eval(expr)
                except Exception:
                    pass

        try:
            ast = parser.parse_class(test_source, method_name)
            interp._exec_block(ast)
            results[method_name] = {
                "status": "PASS" if interp.assertions_failed == 0 else "FAIL",
                "passed": interp.assertions_passed,
                "failed": interp.assertions_failed,
                "failures": interp.failures,
                "error": None,
            }
        except Exception as e:
            results[method_name] = {
                "status": "ERROR",
                "passed": interp.assertions_passed,
                "failed": interp.assertions_failed,
                "failures": interp.failures,
                "error": str(e),
            }

    return results


def print_results(test_class, results):
    """Affiche les résultats d'une classe de test."""
    total = len(results)
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    failed = sum(1 for r in results.values() if r["status"] == "FAIL")
    errors = sum(1 for r in results.values() if r["status"] == "ERROR")

    print("\n{}{}{} — {}/{} methods passed".format(BOLD, test_class, RESET, passed, total))

    for method, r in results.items():
        if r["status"] == "PASS":
            icon = GREEN + "✓" + RESET
        elif r["status"] == "FAIL":
            icon = RED + "✗" + RESET
        else:
            icon = YELLOW + "⚠" + RESET

        detail = ""
        if r["error"]:
            # Truncate long errors
            err = r["error"]
            if len(err) > 80:
                err = err[:80] + "..."
            detail = DIM + " — " + err + RESET
        elif r["failures"]:
            detail = DIM + " — " + r["failures"][0] + RESET

        print("  {} {} ({} assertions){}".format(icon, method, r["passed"] + r["failed"], detail))

    return passed, total


# --- Main ---
if __name__ == "__main__":
    test_suites = [
        ("XPLUtilTest", ["XPLUtil"]),
        ("XPLAddressNormalizerTest", ["XPLAddressNormalizer"]),
        ("XPLDateParserTest", ["XPLDateParser"]),
        ("FuzzyWuzzyTest", ["FuzzyWuzzy"]),
    ]

    grand_passed = 0
    grand_total = 0

    for test_class, deps in test_suites:
        run_sf_test_class._deps = {}
        results = run_sf_test_class(test_class, deps)
        p, t = print_results(test_class, results)
        grand_passed += p
        grand_total += t

    print("\n" + BOLD + "=" * 50 + RESET)
    pct = int(100 * grand_passed / grand_total) if grand_total > 0 else 0
    color = GREEN if grand_passed == grand_total else YELLOW if grand_passed > 0 else RED
    print("{}Total: {}/{} methods passed ({}%){}\n".format(
        color, grand_passed, grand_total, pct, RESET
    ))
