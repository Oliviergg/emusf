"""
Lance les vrais tests Apex du projet Salesforce sf-btp dans emusf.
Charge toutes les classes source XPL/ILG, puis exécute chaque méthode @isTest.
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
    """Interpréteur qui ignore Test.startTest(), Test.stopTest(), etc."""

    def _exec_method_call(self, call):
        if call.obj == "Test" and call.method in ("startTest", "stopTest", "setMock"):
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
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() in ("@istest", "@istest"):
            for j in range(i + 1, min(i + 5, len(lines))):
                m = re.search(r'(?:static\s+)?void\s+(\w+)\s*\(', lines[j])
                if m:
                    methods.append(m.group(1))
                    break
        elif "testMethod" in stripped or "testmethod" in stripped:
            m = re.search(r'(?:testMethod|testmethod)\s+void\s+(\w+)\s*\(', stripped)
            if m:
                methods.append(m.group(1))
    return methods


def load_all_source_classes(prefixes):
    """Charge toutes les classes source (non-test) pour les préfixes donnés."""
    parser = ApexParser()
    classes = {}
    constants = {}

    all_files = sorted(os.listdir(SF_CLASSES))
    for fname in all_files:
        if not fname.endswith(".cls") or fname.endswith("-meta.xml"):
            continue
        name = fname[:-4]
        # Skip test classes
        if re.search(r'test', name, re.IGNORECASE) and name not in ("TestDataFactory", "TestDataFactory2"):
            continue
        # Match prefixes
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
    """Exécute une classe de test et retourne les résultats par méthode."""
    test_source = load_class_source(test_class_name)
    if test_source is None:
        return {}

    test_methods = extract_test_methods(test_source)
    if not test_methods:
        return {}

    results = {}

    for method_name in test_methods:
        org = FakeOrg()
        # Standard objects
        org.create_sobject("Account", {
            "Name": "TEXT", "Type": "TEXT", "RecordTypeId": "TEXT",
            "SIRET__c": "TEXT", "SIRET_NOR__c": "TEXT", "BillingCity": "TEXT",
            "BillingPostalCode": "TEXT", "BillingStreet": "TEXT", "BillingCountry": "TEXT",
            "Phone": "TEXT", "Industry": "TEXT", "OwnerId": "TEXT",
            "IsDeleted": "INTEGER DEFAULT 0", "Description": "TEXT",
        })
        org.create_sobject("Contact", {
            "LastName": "TEXT", "FirstName": "TEXT", "AccountId": "TEXT",
            "Email": "TEXT", "Phone": "TEXT", "Title": "TEXT",
        })
        org.create_sobject("Lead", {
            "LastName": "TEXT", "FirstName": "TEXT", "Company": "TEXT",
            "Email": "TEXT", "Phone": "TEXT", "Status": "TEXT",
            "RecordTypeId": "TEXT", "Description": "TEXT",
            "Street": "TEXT", "City": "TEXT", "PostalCode": "TEXT", "Country": "TEXT",
        })
        org.create_sobject("Opportunity", {
            "Name": "TEXT", "AccountId": "TEXT", "StageName": "TEXT",
            "Amount": "REAL", "CloseDate": "TEXT",
        })
        org.create_sobject("RecordType", {
            "Name": "TEXT", "DeveloperName": "TEXT", "SObjectType": "TEXT",
            "IsActive": "INTEGER DEFAULT 1",
        })
        org.create_sobject("ContentVersion", {
            "Title": "TEXT", "PathOnClient": "TEXT", "VersionData": "TEXT",
            "ContentDocumentId": "TEXT", "FileExtension": "TEXT",
        })
        # XPL custom objects
        org.create_sobject("XPLMarchePublic__c", {
            "Name": "TEXT", "IDENTIFIANT_EXPLORE__c": "TEXT", "CLE_MARCHE_PUBLIC_EXPLORE__c": "TEXT",
            "TITRE_MARCHE__c": "TEXT", "ORGANISME__c": "TEXT", "STATUS__c": "TEXT",
            "CP__c": "TEXT", "VILLE__c": "TEXT", "TYPE_AVIS__c": "TEXT",
            "Objet__c": "TEXT", "Description__c": "TEXT",
            "Date_Limite_Reponse__c": "TEXT", "Date_Publication__c": "TEXT",
            "OwnerId": "TEXT", "RecordTypeId": "TEXT",
            "Lieu_Execution_Code_Postal__c": "TEXT", "Lieu_Execution_Ville__c": "TEXT",
            "Lieu_Execution_Adresse__c": "TEXT", "Lieu_Execution_Pays__c": "TEXT",
            "MarchePublic_Initial__c": "TEXT", "statusApplication__c": "TEXT",
            "Formes_Marche__c": "TEXT", "Type_Contrat__c": "TEXT",
            "Procedures__c": "TEXT", "Localisations__c": "TEXT",
            "Type_Prestations__c": "TEXT", "Missions__c": "TEXT",
            "CreatedDate": "TEXT", "IsDeleted": "INTEGER DEFAULT 0",
        })
        org.create_sobject("XPL_Analyse__c", {
            "Name": "TEXT", "XPLMarchePublic__c": "TEXT", "Status__c": "TEXT",
            "TYPE_AVIS__c": "TEXT", "Score__c": "REAL", "Analyse_Type__c": "TEXT",
            "XPL_Analyse_Type__c": "TEXT",
            "Societes__c": "TEXT", "Resume__c": "TEXT",
            "Date_limite_reponse__c": "TEXT", "Lieu_execution__c": "TEXT",
            "Qualification_LLM__c": "TEXT", "Extraction_LLM__c": "TEXT",
            "Markdown__c": "TEXT", "OwnerId": "TEXT",
            "Next_Action__c": "TEXT", "Lead__c": "TEXT",
        })
        org.create_sobject("XPL_Analyse_Type__c", {
            "Name": "TEXT", "Prompt_Qualification__c": "TEXT",
            "Prompt_Extract__c": "TEXT", "IsActive__c": "INTEGER DEFAULT 1",
        })
        org.create_sobject("XPLDCE__c", {
            "Name": "TEXT", "XPLMarchePublic__c": "TEXT",
            "URL__c": "TEXT", "FileName__c": "TEXT",
        })
        org.create_sobject("XPLValidFileForPrompt__c", {
            "Name": "TEXT", "XPL_Analyse__c": "TEXT",
        })
        org.create_sobject("XPLSettings__c", {
            "Name": "TEXT", "Value__c": "TEXT",
        })
        org.create_sobject("XPL_Prompt_by_analyse_type__c", {
            "Name": "TEXT", "XPL_Analyse_Type__c": "TEXT",
            "Prompt_Name__c": "TEXT", "Status__c": "TEXT",
        })
        org.create_sobject("XPL_Feedback__c", {
            "Name": "TEXT", "XPL_Analyse__c": "TEXT",
            "Rating__c": "TEXT", "Comment__c": "TEXT",
        })
        # ILG custom objects
        org.create_sobject("ILGPortfolio__c", {
            "Name": "TEXT", "Account__c": "TEXT", "Status__c": "TEXT",
        })
        org.create_sobject("ILGSurveillance__c", {
            "Name": "TEXT", "Account__c": "TEXT", "ILGPortfolio__c": "TEXT",
            "Status__c": "TEXT", "Active__c": "INTEGER DEFAULT 1",
            "ILG_Id__c": "TEXT", "End_Date__c": "TEXT",
        })
        org.create_sobject("ILGConsultation__c", {
            "Name": "TEXT", "Account__c": "TEXT", "ILGPortfolio__c": "TEXT",
        })
        org.create_sobject("ILGNotation__c", {
            "Name": "TEXT", "Account__c": "TEXT", "Score__c": "REAL",
        })
        org.create_sobject("Queue_Job__c", {
            "Name": "TEXT", "Status__c": "TEXT", "Job_Type__c": "TEXT",
            "Payload__c": "TEXT", "Error_Message__c": "TEXT",
        })
        org.create_sobject("LLM_Prompt_Result__c", {
            "Name": "TEXT", "Prompt_Name__c": "TEXT", "Result__c": "TEXT",
            "XPL_Analyse__c": "TEXT",
        })
        # Relationships
        org.register_relationship("Contacts", "Contact", "AccountId", "Account")
        org.register_relationship("XPL_Analyses__r", "XPL_Analyse__c", "XPLMarchePublic__c", "XPLMarchePublic__c")
        org.register_relationship("XPLDCEs__r", "XPLDCE__c", "XPLMarchePublic__c", "XPLMarchePublic__c")

        interp = SfTestInterpreter(org)

        # Charger toutes les classes source
        for name, cls in all_classes.items():
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
                "error": str(e)[:100],
            }

    return results


def print_results(test_class, results):
    total = len(results)
    passed = sum(1 for r in results.values() if r["status"] == "PASS")

    print("\n{}{}{} — {}/{} methods".format(BOLD, test_class, RESET, passed, total))

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

    # Charger toutes les classes source
    prefixes = ["XPL", "ILG", "FuzzyWuzzy", "ParQueJob"]
    print(DIM + "Chargement des classes source..." + RESET)
    all_classes = load_all_source_classes(prefixes)
    print("  {} classes chargées".format(len(all_classes)))

    # Trouver toutes les classes de test
    test_pattern = sys.argv[1] if len(sys.argv) > 1 else None
    test_files = []
    for fname in sorted(os.listdir(SF_CLASSES)):
        if not fname.endswith(".cls") or fname.endswith("-meta.xml"):
            continue
        name = fname[:-4]
        if not re.search(r'test', name, re.IGNORECASE):
            continue
        if not any(name.startswith(p) for p in ["XPL", "ILG", "FuzzyWuzzy"]):
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

    # Summary
    print("\n" + BOLD + "=" * 60 + RESET)
    for cls, (p, t) in sorted(class_results.items()):
        pct = int(100 * p / t) if t > 0 else 0
        color = GREEN if p == t else YELLOW if p > 0 else RED
        bar = "█" * (p * 20 // t) + "░" * (20 - p * 20 // t) if t > 0 else ""
        print("  {} {:40s} {}{}/{}{}  {}".format(bar, cls, color, p, t, RESET, "✓" if p == t else ""))

    pct = int(100 * grand_passed / grand_total) if grand_total > 0 else 0
    color = GREEN if grand_passed == grand_total else YELLOW if grand_passed > 0 else RED
    print("\n{}Total: {}/{} methods passed ({}%){}\n".format(
        color, grand_passed, grand_total, pct, RESET
    ))
