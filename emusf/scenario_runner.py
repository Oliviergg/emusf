"""Exécution d'un scénario Apex cohérent depuis un répertoire.

Charge toutes les classes (.cls), triggers (.trigger) et flows (.flow-meta.xml)
du répertoire, puis exécute le point d'entrée (Main.cls par défaut).

Point d'entrée CLI : `python run.py scenarios/<répertoire>`.
"""

import sys
import os
import glob
import re

from emusf.pg_test_org import PgTestOrg
from emusf.config import DSN, SFDX_OBJECTS, SF_CLASSES
from emusf.apex_parser import ApexParser
from emusf.test_runner import ApexTestInterpreter
from emusf.trigger_parser import load_trigger
from emusf.flow_interpreter import load_and_register_flow
from emusf.callout import load_named_credentials

# Couleurs
GREEN = "\033[32m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def load_sf_classes(prefixes):
    """Charge les classes source du projet Salesforce."""
    parser = ApexParser()
    classes = {}
    for fname in sorted(os.listdir(SF_CLASSES)):
        if not fname.endswith(".cls") or fname.endswith("-meta.xml"):
            continue
        name = fname[:-4]
        if not any(name.startswith(p) for p in prefixes):
            continue
        path = os.path.join(SF_CLASSES, fname)
        with open(path) as f:
            source = f.read()
        try:
            class_def = parser.parse_full_class(source)
            classes[class_def.name] = class_def
        except Exception:
            pass
    return classes


def load_scenario(scenario_dir, entry_file="Main.cls", method="run"):
    """Charge et exécute un scénario Apex depuis un répertoire."""

    if not os.path.isdir(scenario_dir):
        print("{}Erreur: répertoire '{}' introuvable{}".format(RED, scenario_dir, RESET))
        sys.exit(1)

    print("{}=== Scénario: {} ==={}\n".format(BOLD, scenario_dir, RESET))

    # --- 1. Charger toutes les classes (.cls) du scénario ---
    parser = ApexParser()
    classes = {}
    entry_class = None
    entry_path = os.path.join(scenario_dir, entry_file)

    for path in sorted(glob.glob(os.path.join(scenario_dir, "**", "*.cls"), recursive=True)):
        with open(path) as f:
            source = f.read()
        try:
            class_def = parser.parse_full_class(source)
            classes[class_def.name] = class_def
            print("  {}CLASS{} {}".format(DIM, RESET, class_def.name))
            if os.path.abspath(path) == os.path.abspath(entry_path):
                entry_class = class_def
        except Exception as e:
            print("  {}WARN: impossible de charger {}: {}{}".format(
                RED, os.path.basename(path), e, RESET
            ))

    # Charger les classes SF du projet (dépendances)
    prefixes_file = os.path.join(scenario_dir, ".prefixes")
    if os.path.exists(prefixes_file):
        with open(prefixes_file) as f:
            prefixes = [line.strip() for line in f if line.strip()]
    else:
        prefixes = ["XPL", "ILG", "FuzzyWuzzy", "ParQueJob",
                    "ParallelQueueableJob", "QueueableJob", "QueueManager",
                    "TestDataFactory", "MockHttp"]
    if os.path.isdir(SF_CLASSES):
        sf_classes = load_sf_classes(prefixes)
        print("  {}SF{} {} classes projet chargées".format(DIM, RESET, len(sf_classes)))
        # Les classes du scénario écrasent celles du projet (override)
        sf_classes.update(classes)
        classes = sf_classes

    if not entry_class:
        entry_class = classes.get(entry_file.replace(".cls", ""))
        if not entry_class:
            print("\n{}Erreur: point d'entrée '{}' introuvable dans {}{}".format(
                RED, entry_file, scenario_dir, RESET
            ))
            sys.exit(1)

    # --- 2. Créer l'org PG ---
    org = PgTestOrg(DSN, schema="test")
    org.truncate_all()

    # Charger les métadonnées SFDX si disponibles
    if os.path.isdir(SFDX_OBJECTS):
        from emusf.sfdx_loader import configure_pg_org
        sfdx_objects = [d for d in os.listdir(SFDX_OBJECTS)
                        if os.path.isdir(os.path.join(SFDX_OBJECTS, d))]
        configure_pg_org(org, SFDX_OBJECTS, sfdx_objects)
        print("  {}SFDX{} métadonnées chargées".format(DIM, RESET))

    # --- 2b. Seed data depuis le schema data ---
    seed_path = os.path.join(scenario_dir, ".seed_tables")
    if os.path.exists(seed_path):
        with open(seed_path) as f:
            tables = [line.strip() for line in f if line.strip()]
        cur = org.conn.cursor()
        for table in tables:
            try:
                cur.execute("INSERT INTO test.{t} SELECT * FROM data.{t}".format(t=table.lower()))
                org.conn.commit()
                print("  {}SEED{} {} copiée depuis data".format(DIM, RESET, table))
            except Exception as e:
                org.conn.rollback()
                print("  {}WARN: seed {} échoué: {}{}".format(RED, table, e, RESET))
        cur.close()

    # --- 3. Charger les triggers (.trigger) avec accès aux classes ---
    for path in sorted(glob.glob(os.path.join(scenario_dir, "**", "*.trigger"), recursive=True)):
        load_trigger(org, path, classes=classes)

    # --- 3b. Charger les flows (.flow-meta.xml) ---
    for path in sorted(glob.glob(os.path.join(scenario_dir, "**", "*.flow-meta.xml"), recursive=True)):
        try:
            flow_def = load_and_register_flow(org, path)
            print("  {}FLOW{} {}".format(DIM, RESET, flow_def.api_name))
        except Exception as e:
            print("  {}WARN: impossible de charger flow {}: {}{}".format(
                RED, os.path.basename(path), e, RESET
            ))

    # --- 3c. Charger les Named Credentials (credentials.yaml) ---
    named_credentials = {}
    cred_path = os.path.join(scenario_dir, "credentials.yaml")
    if os.path.exists(cred_path):
        named_credentials = load_named_credentials(cred_path)
        print("  {}CRED{} {} named credentials chargées".format(
            DIM, RESET, len(named_credentials)))

    # --- 4. Préparer l'interpréteur avec toutes les classes ---
    interp = ApexTestInterpreter(org, named_credentials=named_credentials)
    for name, cls in classes.items():
        interp.classes[name] = cls
        for cname, (ctype, expr) in cls.constants.items():
            try:
                interp.variables["{}.{}".format(name, cname)] = (
                    interp._eval(expr) if expr is not None else None)
            except Exception:
                pass

    # --- 4b. Exécuter Setup.cls si présent (avant les static init) ---
    setup_cls = classes.get("Setup")
    if setup_cls:
        setup_method = setup_cls.methods.get("run")
        if setup_method:
            print("  {}SETUP{} Setup.run()".format(DIM, RESET))
            try:
                interp._invoke_method(setup_cls, setup_method, [])
            except Exception as e:
                print("  {}WARN: Setup.run() échoué: {}{}".format(RED, e, RESET))

    # Exécuter les blocs static { ... } après le chargement de toutes les classes
    for name, cls in classes.items():
        if cls.static_init:
            prev_class = interp._current_class
            interp._current_class = cls
            try:
                for stmt in cls.static_init:
                    interp._exec_stmt(stmt)
            except Exception as e:
                print("  {}WARN: static init {} échoué: {}{}".format(
                    RED, name, e, RESET
                ))
            finally:
                interp._current_class = prev_class

    # --- 5. Exécuter le point d'entrée ---
    print("\n{}--- Exécution: {}.{}() ---{}\n".format(BOLD, entry_class.name, method, RESET))

    method_def = entry_class.methods.get(method)
    if not method_def:
        print("{}Erreur: méthode '{}' introuvable dans {}{}".format(
            RED, method, entry_class.name, RESET
        ))
        sys.exit(1)

    try:
        interp._invoke_method(entry_class, method_def, [])
    except Exception as e:
        interp.assertions_failed += 1
        interp.failures.append("Runtime error: {}".format(e))

    # --- 6. Résultat ---
    print()
    for line in interp.output:
        print("  {}".format(line))

    passed = interp.assertions_passed
    failed = interp.assertions_failed

    if passed + failed > 0:
        print()
        if failed == 0:
            print("{}{}assertions: {} passed{}".format(GREEN, BOLD, passed, RESET))
        else:
            print("{}{}assertions: {} passed, {} failed{}".format(RED, BOLD, passed, failed, RESET))
            for f in interp.failures:
                print("  {} {}{}".format(RED, f, RESET))

    # Cleanup
    org.truncate_all()
    org.conn.close()

    return failed == 0
