#!/usr/bin/env python3
"""Évalue la grammaire ANTLR apex-parser (cible Python) contre le corpus Apex
du repo EMUSF, et compare avec le parser maison d'EMUSF."""
import sys, time, glob, os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "gen"))
sys.path.insert(0, REPO_ROOT)

from antlr4 import InputStream, CommonTokenStream
from antlr4.error.ErrorListener import ErrorListener
from ApexLexer import ApexLexer
from ApexParser import ApexParser


class CollectErrors(ErrorListener):
    def __init__(self):
        self.errors = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append(f"L{line}:{column} {msg}")


def antlr_parse(text, is_trigger):
    errs = CollectErrors()
    lexer = ApexLexer(InputStream(text))
    lexer.removeErrorListeners(); lexer.addErrorListener(errs)
    parser = ApexParser(CommonTokenStream(lexer))
    parser.removeErrorListeners(); parser.addErrorListener(errs)
    if is_trigger:
        parser.triggerUnit()
    else:
        parser.compilationUnit()
    return errs.errors


def emusf_parse(text, is_trigger):
    try:
        if is_trigger:
            from emusf.trigger_parser import TriggerParser
            TriggerParser().parse_trigger(text)
        else:
            from emusf.apex_parser import ApexParser as EmusfParser
            EmusfParser().parse_full_class(text)
        return []
    except Exception as e:
        return [f"{type(e).__name__}: {e}"]


def main():
    files = sorted(
        glob.glob(os.path.join(REPO_ROOT, "**/") + "*.cls", recursive=True)
        + glob.glob(os.path.join(REPO_ROOT, "**/") + "*.trigger", recursive=True)
    )
    stats = {"antlr_ok": 0, "antlr_fail": [], "emusf_ok": 0, "emusf_fail": []}
    t_antlr = t_emusf = 0.0
    for f in files:
        text = open(f, encoding="utf-8").read()
        is_trigger = f.endswith(".trigger")
        rel = os.path.relpath(f, REPO_ROOT)

        t0 = time.perf_counter()
        errs = antlr_parse(text, is_trigger)
        t_antlr += time.perf_counter() - t0
        if errs:
            stats["antlr_fail"].append((rel, errs[:2]))
        else:
            stats["antlr_ok"] += 1

        t0 = time.perf_counter()
        errs = emusf_parse(text, is_trigger)
        t_emusf += time.perf_counter() - t0
        if errs:
            stats["emusf_fail"].append((rel, errs[:1]))
        else:
            stats["emusf_ok"] += 1

    n = len(files)
    print(f"Corpus: {n} fichiers (.cls + .trigger)")
    print(f"ANTLR apex-parser : {stats['antlr_ok']}/{n} OK  ({t_antlr:.2f}s)")
    print(f"Parser EMUSF      : {stats['emusf_ok']}/{n} OK  ({t_emusf:.2f}s)")
    if stats["antlr_fail"]:
        print("\n--- Échecs ANTLR ---")
        for rel, errs in stats["antlr_fail"]:
            print(f"  {rel}")
            for e in errs:
                print(f"    {e}")
    if stats["emusf_fail"]:
        print("\n--- Échecs EMUSF ---")
        for rel, errs in stats["emusf_fail"]:
            print(f"  {rel}: {errs[0][:120]}")


if __name__ == "__main__":
    main()
