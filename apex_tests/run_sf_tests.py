"""
Lance les vrais tests Apex du projet Salesforce sf-btp dans emusf.
Utilise PgTestOrg contre le schema test + métadonnées SFDX.
"""

import os
import re
import sys

# Permet `python apex_tests/run_sf_tests.py` depuis n'importe où
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emusf import ApexParser
from emusf.pg_test_org import PgTestOrg
from emusf.sfdx_loader import configure_pg_org
from emusf.interpreter import ApexInterpreter, ReturnException
from emusf.test_runner import ApexTestInterpreter

# Couleurs
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

from emusf.config import DSN, SF_CLASSES, SFDX_OBJECTS


class SfTestInterpreter(ApexTestInterpreter):
    def __init__(self, org):
        super().__init__(org)
        from emusf.queue import SyncJobQueue
        self.job_queue = SyncJobQueue()

    def _exec_method_call(self, call):
        if call.obj == "Test" and call.method == "startTest":
            return None
        if call.obj == "Test" and call.method == "stopTest":
            self.job_queue.flush(self)  # Execute all queued jobs
            return None
        if call.obj == "Test" and call.method == "setMock":
            args = [self._eval(a) for a in call.args]
            if len(args) >= 2:
                self._http_mock = args[1]
            return None
        return super()._exec_method_call(call)


def load_class_source(class_name):
    path = os.path.join(SF_CLASSES, class_name + ".cls")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


def extract_test_methods(source):
    methods = []
    setup_method = None
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        # @testSetup
        if stripped.lower() == "@testsetup":
            for j in range(i + 1, min(i + 5, len(lines))):
                m = re.search(r'(?:static\s+)?void\s+(\w+)\s*\(', lines[j])
                if m:
                    setup_method = m.group(1)
                    break
        # @isTest
        elif stripped.lower() in ("@istest", "@istest"):
            for j in range(i + 1, min(i + 5, len(lines))):
                m = re.search(r'(?:static\s+)?void\s+(\w+)\s*\(', lines[j])
                if m:
                    methods.append(m.group(1))
                    break
        elif "testMethod" in stripped or "testmethod" in stripped:
            m = re.search(r'(?:testMethod|testmethod)\s+void\s+(\w+)\s*\(', stripped)
            if m:
                methods.append(m.group(1))
    return methods, setup_method


def load_all_source_classes(prefixes):
    parser = ApexParser()
    classes = {}
    for fname in sorted(os.listdir(SF_CLASSES)):
        if not fname.endswith(".cls") or fname.endswith("-meta.xml"):
            continue
        name = fname[:-4]
        if re.search(r'test', name, re.IGNORECASE) and name not in ("TestDataFactory", "TestDataFactory2"):
            continue
        if not any(name.startswith(p) for p in prefixes):
            continue
        source = load_class_source(name)
        if not source:
            continue
        try:
            class_def = parser.parse_full_class(source)
            classes[class_def.name] = class_def
        except Exception:
            pass
    return classes


def run_test_class(test_class_name, all_classes, parser):
    test_source = load_class_source(test_class_name)
    if test_source is None:
        return {}

    test_methods, setup_method = extract_test_methods(test_source)
    if not test_methods:
        return {}

    results = {}

    # Org PG partagée
    org = PgTestOrg(DSN, schema="test")

    # Charger les relations SFDX (cached globally)
    if not hasattr(run_test_class, '_sfdx_loaded'):
        sfdx_objects = [d for d in os.listdir(SFDX_OBJECTS) if os.path.isdir(os.path.join(SFDX_OBJECTS, d))]
        configure_pg_org(org, SFDX_OBJECTS, sfdx_objects)
        run_test_class._sfdx_loaded = True
        run_test_class._sfdx_registry = org.sf_schema
    else:
        org.sf_schema = run_test_class._sfdx_registry

    for method_name in test_methods:
        org.truncate_all()

        interp = SfTestInterpreter(org)

        for name, cls in all_classes.items():
            interp.classes[name] = cls
            for cname, (ctype, expr) in cls.constants.items():
                try:
                    interp.variables["{}.{}".format(name, cname)] = interp._eval(expr) if expr is not None else None
                except Exception:
                    pass

        # Charger les inner classes du fichier test
        try:
            test_class_def = parser.parse_full_class(test_source)
            interp.classes[test_class_def.name] = test_class_def
            for ic_name, ic_def in test_class_def.inner_classes.items():
                interp.classes[ic_name] = ic_def
        except Exception:
            pass

        try:
            # Run @testSetup first if present
            if setup_method:
                try:
                    setup_ast = parser.parse_class(test_source, setup_method)
                    interp._exec_block(setup_ast)
                except Exception:
                    pass  # Setup failure shouldn't block the test

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
                "error": str(e)[:100],
            }

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
            detail = DIM + " — " + r["failures"][0][:80] + RESET

        print("{} {} ({} assert){}".format(icon, method, r["passed"] + r["failed"], detail))

    return passed, total


# --- Main ---
if __name__ == "__main__":
    parser = ApexParser()

    prefixes = [
        "XPL", "ILG", "FuzzyWuzzy",
        "ParQueJob", "ParallelQueueableJob", "QueueableJob", "QueueManager",
        "TestDataFactory", "MockHttp",
    ]
    print(DIM + "Chargement des classes source..." + RESET)
    all_classes = load_all_source_classes(prefixes)
    print("  {} classes chargées".format(len(all_classes)))

    test_pattern = sys.argv[1] if len(sys.argv) > 1 else None
    test_files = []
    for fname in sorted(os.listdir(SF_CLASSES)):
        if not fname.endswith(".cls") or fname.endswith("-meta.xml"):
            continue
        name = fname[:-4]
        if not re.search(r'test', name, re.IGNORECASE):
            continue
        if not any(name.startswith(p) for p in ["XPL", "ILG", "FuzzyWuzzy", "ParQueJob"]):
            continue
        if test_pattern and test_pattern not in name:
            continue
        test_files.append(name)

    grand_passed = 0
    grand_total = 0
    class_results = {}

    for test_class in test_files:
        results = run_test_class(test_class, all_classes, parser)
        if results:
            p, t = print_results(test_class, results)
            grand_passed += p
            grand_total += t
            class_results[test_class] = (p, t)

    print("\n" + BOLD + "=" * 60 + RESET)
    for cls, (p, t) in sorted(class_results.items()):
        color = GREEN if p == t else YELLOW if p > 0 else RED
        bar = "█" * (p * 20 // t) + "░" * (20 - p * 20 // t) if t > 0 else ""
        print("  {} {:40s} {}{}/{}{}  {}".format(bar, cls, color, p, t, RESET, "✓" if p == t else ""))

    pct = int(100 * grand_passed / grand_total) if grand_total > 0 else 0
    color = GREEN if grand_passed == grand_total else YELLOW if grand_passed > 0 else RED
    print("\n{}Total: {}/{} methods passed ({}%){}\n".format(
        color, grand_passed, grand_total, pct, RESET
    ))
