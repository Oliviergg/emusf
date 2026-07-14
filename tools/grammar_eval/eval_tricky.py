#!/usr/bin/env python3
"""Confronte les deux parsers à des constructions Apex avancées."""
import sys, os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

sys.path.insert(0, os.path.join(REPO_ROOT, "emusf", "antlr", "generated"))
sys.path.insert(0, REPO_ROOT)

from antlr4 import InputStream, CommonTokenStream
from antlr4.error.ErrorListener import ErrorListener
from ApexLexer import ApexLexer
from ApexParser import ApexParser

SNIPPETS = {
    "propriétés get/set": """
public class C {
    public String Name { get; set; }
    public Integer Count { get { return c; } set { c = value; } }
    private Integer c = 0;
}""",
    "inner class + interface + enum": """
public class C {
    public enum Status { OPEN, CLOSED }
    public interface Handler { void handle(SObject s); }
    public class Impl implements Handler {
        public void handle(SObject s) {}
    }
    public virtual class Base {}
    public class Child extends Base {}
}""",
    "génériques imbriqués": """
public class C {
    Map<Id, List<Map<String, Set<Integer>>>> data =
        new Map<Id, List<Map<String, Set<Integer>>>>();
}""",
    "switch on sObject / enum / literals": """
public class C {
    void m(SObject o, Integer i) {
        switch on o {
            when Account a { System.debug(a); }
            when Contact c, Lead l { }
            when null { }
            when else { }
        }
        switch on i {
            when 1, 2, 3 { }
            when -1 { }
            when else { }
        }
    }
}""",
    "SOQL complet (agrégats, GROUP BY ROLLUP, FOR UPDATE)": """
public class C {
    void m() {
        List<AggregateResult> r = [
            SELECT COUNT(Id) cnt, MAX(Amount), StageName
            FROM Opportunity
            WHERE CloseDate = LAST_N_DAYS:30 AND (Amount > 1000 OR Name LIKE '%x%')
            WITH SECURITY_ENFORCED
            GROUP BY ROLLUP(StageName)
            HAVING COUNT(Id) > 2
            ORDER BY StageName NULLS LAST
            LIMIT 10 OFFSET 5
        ];
        List<Account> a = [SELECT Id FROM Account FOR UPDATE];
        Account b = [SELECT Id, (SELECT Id FROM Contacts WHERE LastName != null) FROM Account LIMIT 1];
    }
}""",
    "SOSL": """
public class C {
    void m() {
        List<List<SObject>> r = [FIND 'test*' IN ALL FIELDS
            RETURNING Account(Id, Name WHERE Name != null LIMIT 5), Contact(Id)];
    }
}""",
    "safe navigation + null coalescing": """
public class C {
    void m(Account a) {
        String s = a?.Owner?.Name;
        Integer i = a?.NumberOfEmployees ?? 0;
    }
}""",
    "annotations avec paramètres": """
public class C {
    @AuraEnabled(cacheable=true)
    public static String f() { return null; }
    @InvocableMethod(label='X' description='Y' category='Z')
    public static void g(List<Id> ids) {}
    @future(callout=true)
    public static void h() {}
    @TestVisible private Integer x;
}""",
    "batchable + database methods": """
public class C implements Database.Batchable<SObject>, Database.Stateful {
    public Database.QueryLocator start(Database.BatchableContext bc) {
        return Database.getQueryLocator('SELECT Id FROM Account');
    }
    public void execute(Database.BatchableContext bc, List<Account> scope) {}
    public void finish(Database.BatchableContext bc) {}
}""",
    "blocs d'initialisation static/instance": """
public class C {
    static Integer x;
    static { x = 1; }
    Integer y;
    { y = 2; }
}""",
    "syntaxe tableau ancienne + init": """
public class C {
    String[] names = new String[]{'a', 'b'};
    Integer[] nums = new Integer[5];
    Account[] accs = new List<Account>();
}""",
    "DML merge / upsert avec champ / undelete": """
public class C {
    void m(Account a, Account b, List<Lead> leads) {
        merge a b;
        upsert leads MyExtId__c;
        undelete a;
        Database.upsert(leads, Lead.Fields.Email, false);
    }
}""",
    "ternaire imbriqué + cast + instanceof": """
public class C {
    Object m(Object o) {
        return o instanceof Account ? ((Account) o).Name
             : o instanceof Contact ? ((Contact) o).LastName : null;
    }
}""",
    "chaînage sur new + this()/super()": """
public class C {
    public C() { this(1); }
    public C(Integer i) {}
    void m() {
        String s = new Account(Name='x').Name;
        Integer l = new List<Integer>{1,2,3}.size();
    }
}""",
    "for classiques et variantes": """
public class C {
    void m() {
        for (Integer i = 0, j = 10; i < j; i++, j--) {}
        for (Account a : [SELECT Id FROM Account]) {}
        for (;;) { break; }
        do { continue; } while (false);
    }
}""",
    "try/catch/finally multiples + throw": """
public class C {
    void m() {
        try { insert new Account(); }
        catch (DmlException e) { throw new AuraHandledException(e.getMessage()); }
        catch (Exception e) {}
        finally {}
    }
}""",
    "identifiants = mots-clés contextuels": """
public class C {
    Integer after = 1;
    String trigger_x;
    void m() {
        Integer when = 2;   // 'when' est un mot-clé contextuel
        Integer switch_v = 3;
    }
}""",
    "littéraux (long, decimal, date, datetime, exposant)": """
public class C {
    Long l = 2147483648L;
    Decimal d = 3.14;
    Double e = 1.5e10;
    void m() {
        Date dt = Date.newInstance(2024, 1, 1);
        Object o = null;
        Boolean b = true;
    }
}""",
    "interface générique Comparable + typage": """
public class C implements Comparable {
    public Integer compareTo(Object o) { return 0; }
}""",
    "classe abstraite + virtual + override + transient": """
public abstract class C {
    protected abstract void m();
    public virtual void n() {}
    transient Integer cache;
    public with sharing class Inner {
        public void o() {}
    }
}""",
    "without/inherited sharing + global": """
global inherited sharing class C {
    global static void m() {}
    webservice static String ws() { return null; }
}""",
    "bind expressions SOQL complexes": """
public class C {
    void m(Set<Id> ids, Account acc) {
        List<Account> l = [SELECT Id FROM Account WHERE Id IN :ids AND Name = :acc.Name
                           AND CreatedDate > :Date.today().addDays(-7)];
        Integer n = [SELECT COUNT() FROM Contact WHERE AccountId = :l[0].Id];
    }
}""",
    "TYPEOF dans SOQL": """
public class C {
    void m() {
        List<Event> evts = [SELECT TYPEOF What WHEN Account THEN Phone WHEN Opportunity THEN Amount ELSE Name END FROM Event];
    }
}""",
}


class CollectErrors(ErrorListener):
    def __init__(self):
        self.errors = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append(f"L{line}:{column} {msg}")


def antlr_parse(text):
    errs = CollectErrors()
    lexer = ApexLexer(InputStream(text))
    lexer.removeErrorListeners(); lexer.addErrorListener(errs)
    parser = ApexParser(CommonTokenStream(lexer))
    parser.removeErrorListeners(); parser.addErrorListener(errs)
    parser.compilationUnit()
    return errs.errors


def emusf_parse(text):
    try:
        from emusf.apex_parser import ApexParser as EmusfParser
        EmusfParser().parse_full_class_legacy(text)
        return []
    except Exception as e:
        return [f"{type(e).__name__}: {str(e)[:100]}"]


def main():
    antlr_ok = emusf_ok = 0
    print(f"{'Construction':55} {'ANTLR':>7} {'EMUSF':>7}")
    print("-" * 72)
    details = []
    for name, code in SNIPPETS.items():
        a = antlr_parse(code)
        e = emusf_parse(code)
        antlr_ok += not a
        emusf_ok += not e
        print(f"{name:55} {'OK' if not a else 'FAIL':>7} {'OK' if not e else 'FAIL':>7}")
        if a:
            details.append(("ANTLR", name, a[0]))
        if e:
            details.append(("EMUSF", name, e[0]))
    n = len(SNIPPETS)
    print("-" * 72)
    print(f"{'TOTAL':55} {antlr_ok:>4}/{n} {emusf_ok:>4}/{n}")
    if details:
        print("\n--- Détails des échecs ---")
        for who, name, err in details:
            print(f"[{who}] {name}\n    {err}")


if __name__ == "__main__":
    main()
