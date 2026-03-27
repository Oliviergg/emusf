"""Lance tous les tests Apex du répertoire apex_tests/."""

import sys
from emusf import FakeOrg
from emusf.test_runner import run_test_dir

org = FakeOrg()
org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0"})
org.create_sobject("Contact", {"LastName": "TEXT", "FirstName": "TEXT", "AccountId": "TEXT"})
org.register_relationship("Contacts", "Contact", "AccountId", "Account")

test_dir = sys.argv[1] if len(sys.argv) > 1 else "apex_tests"
ok = run_test_dir(test_dir, org, pattern="Test*.cls")
sys.exit(0 if ok else 1)
