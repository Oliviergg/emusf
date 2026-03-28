"""Lance les tests Apex avec DML contre PostgreSQL (schema test)."""

import sys
import os
import glob

from emusf import ApexParser
from emusf.pg_test_org import PgTestOrg
from emusf.test_runner import ApexTestInterpreter

# Couleurs
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

DSN = "host=localhost port=6000 user=postgres password=dcc948df3501919f709cb976fa2cb24000be8b12 dbname=biup"

org = PgTestOrg(DSN, schema="test")

# Charger les helpers
parser = ApexParser()
helpers_dir = "apex_tests/helpers"
helper_classes = {}
if os.path.isdir(helpers_dir):
    for path in sorted(glob.glob(os.path.join(helpers_dir, "*.cls"))):
        with open(path) as f:
            source = f.read()
        try:
            class_def = parser.parse_full_class(source)
            helper_classes[class_def.name] = class_def
        except Exception as e:
            print("{}WARN: {}: {}{}".format(YELLOW, os.path.basename(path), e, RESET))

# Tests à exécuter
test_dir = sys.argv[1] if len(sys.argv) > 1 else "apex_tests"
pattern = sys.argv[2] if len(sys.argv) > 2 else "Test*Pg.cls"
files = sorted(glob.glob(os.path.join(test_dir, pattern)))

if not files:
    print("Aucun test trouvé: {}".format(os.path.join(test_dir, pattern)))
    sys.exit(0)

total_passed = 0
total_failed = 0

for path in files:
    fname = os.path.basename(path)

    with open(path) as f:
        source = f.read()

    # Truncate tables avant chaque test
    org.truncate_all()

    interp = ApexTestInterpreter(org)

    # Charger les helpers
    for name, cls in helper_classes.items():
        interp.classes[name] = cls
        for cname, (ctype, expr) in cls.constants.items():
            try:
                interp.variables["{}.{}".format(name, cname)] = interp._eval(expr)
            except Exception:
                pass

    try:
        ast = parser.parse_class(source, "run")
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

    print("  {} {} — {} assertions".format(status, fname, passed + failed))
    for f in interp.failures:
        print("    " + RED + "✗ " + f + RESET)

print()
summary = "{}Total: {} passed, {} failed{}".format(BOLD, total_passed, total_failed, RESET)
if total_failed == 0:
    print(GREEN + "✓ " + RESET + summary)
else:
    print(RED + "✗ " + RESET + summary)

sys.exit(0 if total_failed == 0 else 1)
