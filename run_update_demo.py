"""Demo: update un Account et déclenche un trigger."""

from emusf import PgTestOrg, ApexInterpreter
from emusf.config import DSN
from emusf.trigger_parser import load_trigger

# Setup org
org = PgTestOrg(DSN, schema="test")
org.truncate_all()
org.create_sobject("Account", {
    "Name": "TEXT",
    "Industry": "TEXT",
    "Rating": "TEXT",
})

# Charger le trigger
load_trigger(org, "apex/AccountUpdateTrigger.trigger")

# Lire et exécuter le script Apex
with open("apex/AccountUpdateDemo.cls") as f:
    source = f.read()

interp = ApexInterpreter(org)
interp.run(source, method="run")

# Cleanup
org.truncate_all()
org.conn.close()
