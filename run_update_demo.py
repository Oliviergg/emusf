"""Demo: update un Account et déclenche un trigger."""

from emusf import FakeOrg, ApexInterpreter
from emusf.trigger_parser import load_trigger

# Setup org
org = FakeOrg()
org.create_sobject("Account", {
    "Name": "TEXT",
    "Industry": "TEXT",
    "Rating": "TEXT",
})

# Charger le trigger
load_trigger("apex/AccountUpdateTrigger.trigger", org)

# Lire et exécuter le script Apex
with open("apex/AccountUpdateDemo.cls") as f:
    source = f.read()

interp = ApexInterpreter(org)
interp.run(source, method="run")
