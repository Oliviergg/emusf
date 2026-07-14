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

# Execute an Apex class
python3 run.py apex/AccountDemo.cls run

# Run Apex test suite (apex_tests/ directory, includes the Test*Pg.cls DML tests)
python3 run_tests.py

# Execute an Apex class against exported Salesforce data (schema `data`, read-only)
python3 run_pg.py apex/AccountPgDemo.cls run

# Interactive Apex/SOQL REPL against exported data
python3 utils/repl.py

# Run a scenario (loads classes + triggers from a directory)
python3 run_scenario.py scenarios/account_trigger

# Run tests against real SFDX project metadata
python3 run_sf_tests.py
```

## Architecture

**Parsing pipeline**: Apex source → `emusf/antlr/` (default frontend: ANTLR apex-parser grammar, vendored generated parser, `builder.py` maps the parse tree to `ast_nodes`) → `interpreter.py` (execution). SOQL has its own parser in `parser.py`. Trigger entry point is `trigger_parser.py`. The legacy regex/token parser (`lexer.py` + `apex_parser.py` + `token_parser.py`) is kept during the transition — `EMUSF_FRONTEND=legacy` reactivates it; `tests/test_ast_equivalence.py` and `tests/test_parser_oracle.py` cross-check both chains. See `emusf/antlr/README.md` for grammar provenance and regeneration.

**AST nodes** (`ast_nodes.py`): All dataclass-based. Expressions (StringLiteral, MethodCall, BinaryOp, etc.) and statements (VarDecl, IfElse, ForEach, DmlInsert, etc.).

**Two org implementations**:
- `PgOrg` — read-only org for querying exported Salesforce data
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
