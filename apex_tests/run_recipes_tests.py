"""
Lance les tests Apex du projet trailheadapps/apex-recipes dans emusf.

Structure attendue (clone de https://github.com/trailheadapps/apex-recipes,
racine configurable via EMUSF_RECIPES_ROOT, défaut: ../apex-recipes) :
  force-app/main/default/classes/<Catégorie>/*.cls   — classes source
  force-app/main/default/objects/                    — métadonnées SObjects
  force-app/main/default/triggers/*.trigger          — triggers
  force-app/tests/<Catégorie>/*_Tests.cls            — classes de test

Usage:
  python apex_tests/run_recipes_tests.py [pattern] [--json rapport.json]
"""

import contextlib
import glob
import json
import os
import re
import signal
import sys


class DiscardIO:
    """Puits pour le stdout des tests — System.debug dans une boucle peut
    produire des millions de lignes."""

    def write(self, s):
        return len(s)

    def flush(self):
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emusf import ApexParser
from emusf.config import DSN, RECIPES_ROOT
from emusf.interpreter import AssertException
from emusf.pg_test_org import PgTestOrg
from emusf.sfdx_loader import configure_pg_org
from emusf.test_runner import ApexTestInterpreter
from emusf.trigger_parser import load_trigger

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

CLASSES_DIR = os.path.join(RECIPES_ROOT, "force-app", "main", "default", "classes")
OBJECTS_DIR = os.path.join(RECIPES_ROOT, "force-app", "main", "default", "objects")
TRIGGERS_DIR = os.path.join(RECIPES_ROOT, "force-app", "main", "default", "triggers")
TESTS_DIR = os.path.join(RECIPES_ROOT, "force-app", "tests")

METHOD_TIMEOUT = 20  # secondes par méthode de test (boucles LDV, etc.)


class MethodTimeout(BaseException):
    """BaseException : ne doit pas être avalée par les try/catch Apex
    de l'interpréteur (qui capturent Exception)."""
    pass


def _alarm_handler(signum, frame):
    raise MethodTimeout("timeout après {}s".format(METHOD_TIMEOUT))


class RecipesTestInterpreter(ApexTestInterpreter):
    def __init__(self, org):
        super().__init__(org)
        from emusf.queue import SyncJobQueue
        self.job_queue = SyncJobQueue()

    def _exec_method_call(self, call):
        if call.obj == "Test":
            if call.method == "startTest":
                return None
            if call.method == "stopTest":
                self.job_queue.flush(self)
                return None
            if call.method == "setMock":
                args = [self._eval(a) for a in call.args]
                if len(args) >= 2:
                    self._http_mock = args[1]
                return None
        return super()._exec_method_call(call)


def extract_test_methods(source):
    """Extrait (méthodes @isTest, méthode @testSetup) par regex."""
    methods = []
    setup_method = None
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower().startswith("@testsetup"):
            for j in range(i + 1, min(i + 5, len(lines))):
                m = re.search(r'(?:static\s+)?void\s+(\w+)\s*\(', lines[j])
                if m:
                    setup_method = m.group(1)
                    break
        elif stripped.lower().startswith("@istest") and "(" not in stripped.split("//")[0].replace("@isTest", "", 1)[:1]:
            for j in range(i + 1, min(i + 5, len(lines))):
                m = re.search(r'(?:static\s+)?(?:void|String)\s+(\w+)\s*\(', lines[j])
                if m and "class" not in lines[j]:
                    methods.append(m.group(1))
                    break
        elif "testmethod" in stripped.lower():
            m = re.search(r'(?:testMethod|testmethod)\s+void\s+(\w+)\s*\(', stripped)
            if m:
                methods.append(m.group(1))
    return methods, setup_method


def load_source_classes(parser):
    """Charge récursivement toutes les classes source du repo apex-recipes.

    Retourne (classes chargées, erreurs de parsing {nom: message}).
    """
    classes = {}
    parse_errors = {}
    for path in sorted(glob.glob(os.path.join(CLASSES_DIR, "**", "*.cls"), recursive=True)):
        name = os.path.basename(path)[:-4]
        with open(path) as f:
            source = f.read()
        try:
            class_def = parser.parse_full_class(source)
            classes[class_def.name] = class_def
        except Exception as e:
            parse_errors[name] = str(e)[:200]
    return classes, parse_errors


def load_test_files():
    """Retourne {nom: (chemin, source)} des classes de test (*_Tests.cls),
    et les helpers présents dans force-app/tests (non suffixés _Tests)."""
    tests = {}
    helpers = {}
    for path in sorted(glob.glob(os.path.join(TESTS_DIR, "**", "*.cls"), recursive=True)):
        name = os.path.basename(path)[:-4]
        with open(path) as f:
            source = f.read()
        if name.endswith("_Tests") or name.endswith("_Test") or name.endswith("Test") or name.endswith("Tests"):
            tests[name] = (path, source)
        else:
            helpers[name] = source
    return tests, helpers


def run_test_class(test_class_name, test_source, all_classes, parser, org):
    test_methods, setup_method = extract_test_methods(test_source)
    if not test_methods:
        return {}

    results = {}

    # Parse de la classe de test elle-même (une fois)
    try:
        test_class_def = parser.parse_full_class(test_source)
    except Exception as e:
        return {m: {"status": "ERROR", "passed": 0, "failed": 0, "failures": [],
                    "error": "parse: " + str(e)[:200]} for m in test_methods}

    for method_name in test_methods:
        org.truncate_schema()

        interp = RecipesTestInterpreter(org)

        for name, cls in all_classes.items():
            interp.classes[name] = cls
            for cname, (ctype, expr) in cls.constants.items():
                try:
                    interp.variables["{}.{}".format(name, cname)] = (
                        interp._eval(expr) if expr is not None else None)
                except Exception:
                    pass

        interp.classes[test_class_def.name] = test_class_def
        interp._current_class = test_class_def
        for ic_name, ic_def in test_class_def.inner_classes.items():
            interp.classes[ic_name] = ic_def

        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(METHOD_TIMEOUT)
        # Jette le stdout des tests (System.debug peut être très verbeux)
        stdout_ctx = contextlib.redirect_stdout(DiscardIO())
        stdout_ctx.__enter__()
        try:
            if setup_method:
                try:
                    setup_ast = parser.parse_class(test_source, setup_method)
                    interp._exec_block(setup_ast)
                except Exception:
                    pass

            for cls_name, cls in list(interp.classes.items()):
                if getattr(cls, "static_init", None):
                    prev_cls = interp._current_class
                    interp._current_class = cls
                    try:
                        for stmt in cls.static_init:
                            interp._exec_stmt(stmt)
                    except Exception:
                        pass
                    finally:
                        interp._current_class = prev_cls

            ast = parser.parse_class(test_source, method_name)
            interp._exec_block(ast)
            results[method_name] = {
                "status": "PASS" if interp.assertions_failed == 0 else "FAIL",
                "passed": interp.assertions_passed,
                "failed": interp.assertions_failed,
                "failures": interp.failures,
                "error": None,
            }
        except AssertException:
            # L'échec est déjà compté dans assertions_failed/failures
            results[method_name] = {
                "status": "FAIL",
                "passed": interp.assertions_passed,
                "failed": interp.assertions_failed,
                "failures": interp.failures,
                "error": None,
            }
        except MethodTimeout:
            results[method_name] = {
                "status": "ERROR",
                "passed": interp.assertions_passed,
                "failed": interp.assertions_failed,
                "failures": interp.failures,
                "error": "TIMEOUT: >{}s (boucle infinie probable)".format(METHOD_TIMEOUT),
            }
        except Exception as e:
            results[method_name] = {
                "status": "ERROR",
                "passed": interp.assertions_passed,
                "failed": interp.assertions_failed,
                "failures": interp.failures,
                "error": "{}: {}".format(type(e).__name__, str(e)[:200]),
            }
        finally:
            signal.alarm(0)
            stdout_ctx.__exit__(None, None, None)

    return results


def print_results(test_class, results):
    total = len(results)
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    print("\n{}{}{} — {}/{}".format(BOLD, test_class, RESET, passed, total))
    for method, r in results.items():
        if r["status"] == "PASS":
            icon = GREEN + "  ✓" + RESET
        elif r["status"] == "FAIL":
            icon = RED + "  ✗" + RESET
        else:
            icon = YELLOW + "  ⚠" + RESET
        detail = ""
        if r["error"]:
            detail = DIM + " — " + r["error"] + RESET
        elif r["failures"]:
            detail = DIM + " — " + str(r["failures"][0])[:100] + RESET
        print("{} {} ({} assert){}".format(icon, method, r["passed"] + r["failed"], detail))
    return passed, total


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    json_path = None
    if "--json" in args:
        i = args.index("--json")
        json_path = args[i + 1]
        del args[i:i + 2]
    test_pattern = args[0] if args else None

    if not os.path.isdir(RECIPES_ROOT):
        print(RED + "Clone apex-recipes introuvable: {} (EMUSF_RECIPES_ROOT)".format(RECIPES_ROOT) + RESET)
        sys.exit(1)

    parser = ApexParser()

    print(DIM + "Chargement des classes source apex-recipes..." + RESET)
    all_classes, parse_errors = load_source_classes(parser)
    print("  {} classes chargées, {} erreurs de parsing".format(len(all_classes), len(parse_errors)))
    for name, err in parse_errors.items():
        print(DIM + "  PARSE FAIL {}: {}".format(name, err[:120]) + RESET)

    tests, helpers = load_test_files()
    for name, source in helpers.items():
        try:
            class_def = parser.parse_full_class(source)
            all_classes[class_def.name] = class_def
        except Exception as e:
            parse_errors[name] = str(e)[:200]
            print(DIM + "  PARSE FAIL (helper) {}: {}".format(name, str(e)[:120]) + RESET)

    # Org partagée + métadonnées SFDX + triggers
    org = PgTestOrg(DSN, schema="test")
    sfdx_objects = [d for d in os.listdir(OBJECTS_DIR)
                    if os.path.isdir(os.path.join(OBJECTS_DIR, d))]
    configure_pg_org(org, OBJECTS_DIR, sfdx_objects)
    if os.path.isdir(TRIGGERS_DIR):
        for path in sorted(glob.glob(os.path.join(TRIGGERS_DIR, "*.trigger"))):
            try:
                load_trigger(org, path, classes=all_classes)
            except Exception as e:
                print(DIM + "  TRIGGER FAIL {}: {}".format(
                    os.path.basename(path), str(e)[:120]) + RESET)

    grand_passed = 0
    grand_total = 0
    class_results = {}
    report = {"parse_errors": parse_errors, "tests": {}}

    for test_class in sorted(tests):
        if test_pattern and test_pattern not in test_class:
            continue
        path, source = tests[test_class]
        print(DIM + "→ " + test_class + "..." + RESET, flush=True)
        results = run_test_class(test_class, source, all_classes, parser, org)
        if results:
            p, t = print_results(test_class, results)
            grand_passed += p
            grand_total += t
            class_results[test_class] = (p, t)
            report["tests"][test_class] = results

    print("\n" + BOLD + "=" * 70 + RESET)
    for cls, (p, t) in sorted(class_results.items()):
        color = GREEN if p == t else YELLOW if p > 0 else RED
        bar = "█" * (p * 20 // t) + "░" * (20 - p * 20 // t) if t > 0 else ""
        print("  {} {:45s} {}{}/{}{}  {}".format(bar, cls, color, p, t, RESET, "✓" if p == t else ""))

    pct = int(100 * grand_passed / grand_total) if grand_total > 0 else 0
    color = GREEN if grand_passed == grand_total else YELLOW if grand_passed > 0 else RED
    print("\n{}Total: {}/{} methods passed ({}%){}\n".format(
        color, grand_passed, grand_total, pct, RESET))

    if json_path:
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(DIM + "Rapport JSON: " + json_path + RESET)
