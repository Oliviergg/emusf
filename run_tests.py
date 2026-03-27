"""Lance tous les tests Apex du répertoire apex_tests/."""

import sys
import os
import glob
from emusf import FakeOrg
from emusf.test_runner import run_test_dir, run_test_file, ApexTestInterpreter
from emusf.apex_parser import ApexParser
from emusf.interpreter import ApexInterpreter

# Couleurs
GREEN = "\033[32m"
RED = "\033[31m"
BOLD = "\033[1m"
RESET = "\033[0m"

org = FakeOrg()
org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0"})
org.create_sobject("Contact", {"LastName": "TEXT", "FirstName": "TEXT", "AccountId": "TEXT"})
org.register_relationship("Contacts", "Contact", "AccountId", "Account")

test_dir = sys.argv[1] if len(sys.argv) > 1 else "apex_tests"

# Charger les helpers (classes partagées)
helpers_dir = os.path.join(test_dir, "helpers")
helper_classes = {}
if os.path.isdir(helpers_dir):
    parser = ApexParser()
    for path in sorted(glob.glob(os.path.join(helpers_dir, "*.cls"))):
        with open(path) as f:
            source = f.read()
        try:
            class_def = parser.parse_full_class(source)
            helper_classes[class_def.name] = class_def
        except Exception as e:
            print("{}WARN: impossible de charger {}: {}{}".format(
                RED, os.path.basename(path), e, RESET
            ))

# Runner custom qui pré-charge les helpers
files = sorted(glob.glob(os.path.join(test_dir, "Test*.cls")))
if not files:
    print("Aucun test trouvé")
    sys.exit(0)

total_passed = 0
total_failed = 0
all_ok = True

for path in files:
    with open(path) as f:
        source = f.read()

    p = ApexParser()
    ast = p.parse_class(source, "run")

    interp = ApexTestInterpreter(org)
    # Charger les helpers dans l'interpréteur
    for name, cls in helper_classes.items():
        interp.classes[name] = cls
        for cname, (ctype, expr) in cls.constants.items():
            interp.variables["{}.{}".format(name, cname)] = interp._eval(expr)

    try:
        interp._exec_block(ast)
    except Exception as e:
        interp.assertions_failed += 1
        interp.failures.append("Runtime error: {}".format(e))

    passed = interp.assertions_passed
    failed = interp.assertions_failed
    total_passed += passed
    total_failed += failed

    if failed == 0:
        status = GREEN + "PASS" + RESET
    else:
        status = RED + "FAIL" + RESET
        all_ok = False

    fname = os.path.basename(path)
    print("  {} {} — {} assertions".format(status, fname, passed + failed))
    for f in interp.failures:
        print("    " + RED + "✗ " + f + RESET)

print()
summary = "{}Total: {} passed, {} failed{}".format(BOLD, total_passed, total_failed, RESET)
if all_ok:
    print(GREEN + "✓ " + RESET + summary)
else:
    print(RED + "✗ " + RESET + summary)

sys.exit(0 if all_ok else 1)
