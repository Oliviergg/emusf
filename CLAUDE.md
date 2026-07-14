# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

EMUSF (Émulateur Salesforce) — a Python Apex/SOQL emulator that runs Salesforce code locally against PostgreSQL. It parses Apex classes, SOQL queries, and triggers, then interprets them using a PostgreSQL-backed simulated Salesforce org.

## Commands

```bash
# Run all pytest tests
python3 -m pytest tests/ -v

# Run a single test
python3 -m pytest tests/test_emulator.py::test_simple_soql -v

# Unified entry point: REPL, Apex class, or scenario — see python3 run.py --help
python3 run.py                                  # interactive Apex/SOQL REPL (sandbox org)
python3 run.py --org data                       # REPL on exported Salesforce data (DML rolled back at end)
python3 run.py apex/AccountDemo.cls [method]    # execute a static method (sandbox: DML + triggers)
python3 run.py apex/AccountPgDemo.cls --org data  # execute against exported data
python3 run.py scenarios/account_trigger        # run a scenario (classes + triggers + flows)
python3 run.py scenarios/data_dml_demo --org data  # scenario against exported data (rollback by default)
# Options: --ast (print AST), --trace [normal|verbose] (log execution: calls/statements/SOQL/DML), --no-seed / --no-triggers (sandbox), --entry (scenario entry file)
# Options org data: --commit (persist DML, otherwise rolled back), --triggers (fire DML triggers)

# Run Apex test suite (apex_tests/ directory, includes the Test*Pg.cls DML tests)
python3 apex_tests/run_tests.py

# Run tests against real SFDX project metadata
python3 apex_tests/run_sf_tests.py
```

## Architecture

**Parsing pipeline**: Apex source → `emusf/antlr/` (ANTLR apex-parser grammar, vendored generated parser, `builder.py` maps the parse tree to `ast_nodes`) → `interpreter.py` (execution). `apex_parser.py` (`ApexParser`) and `trigger_parser.py` (`TriggerParser`) are thin façades over the ANTLR chain. SOQL has its own parser in `parser.py`. See `emusf/antlr/README.md` for grammar provenance and regeneration.

**AST nodes** (`ast_nodes.py`): All dataclass-based. Expressions (StringLiteral, MethodCall, BinaryOp, etc.) and statements (VarDecl, IfElse, ForEach, DmlInsert, etc.).

**Three org implementations**:
- `PgOrg` — read-only org for querying exported Salesforce data
- `PgDataOrg` — DML on the exported data (schema `data`): all writes accumulate in one transaction rolled back at end of run unless `--commit`; strict schema (missing table/column → `DmlException`, never CREATE/ALTER); values adapted to real column types; IDs generated with the emulator pod `Zz` (no collision with real IDs); triggers opt-in via `--triggers`. A long-lived session holds one open transaction (won't see concurrent external commits).
- `PgTestOrg` — full test org with DML, auto-ID generation, trigger firing, and transaction isolation via SAVEPOINT/ROLLBACK

**Interpreter** (`interpreter.py`): `_eval(expr)` evaluates expressions, `_exec_stmt(stmt)` executes statements. Control flow uses exceptions (`ReturnException`, `BreakException`, `ContinueException`). SObjects are plain Python dicts. Variables and classes stored in interpreter state.

**DML & triggers**: Triggers fire in order (before → DML → after). `Trigger.new`/`Trigger.old` are set as context. IDs auto-generated using Salesforce base-62 encoding with 3-char prefixes per SObject type (defined in `dml.py`).

**Flows**: Salesforce Flows (`.flow-meta.xml`) are parsed by `flow_parser.py` into dataclass AST nodes (`flow_nodes.py`), then executed by `flow_interpreter.py` as a state machine. Supports assignments, decisions, loops, record CRUD, formulas, and variables.

**SOQL → SQL**: Case conversion (CamelCase → lowercase), bind variable resolution (`:varName`), relationship subqueries via registered metadata in `SchemaRegistry`.

**Test infrastructure**: pytest fixtures in `conftest.py` provide a `PgTestOrg` that truncates between tests. Apex-level tests use `ApexTestInterpreter` (in `test_runner.py`) which adds `System.assert()`/`System.assertEquals()`.

## Prerequisites

- Python 3.11+
- PostgreSQL running (connection configured in `emusf/config.py`)
- `psycopg2-binary`, `pytest`

## Conventions

- Codebase uses French for comments and some variable names
- No build step — pure Python
- `TODO.md` à la racine contient les idées à implémenter plus tard. Y ajouter les nouvelles idées qui émergent. Si plus rien à faire, piocher dedans.
