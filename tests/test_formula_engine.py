"""Tests du moteur de formules unifié."""

import math
from datetime import date, datetime

import pytest

from emusf.formula_engine import FormulaEngine, FormulaError, evaluate, resolve_merge_fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_resolver(data: dict):
    """Crée un resolver simple à partir d'un dict (supporte les chemins pointés)."""
    def resolver(ref: str):
        if ref in data:
            return data[ref]
        parts = ref.split(".")
        obj = data
        for p in parts:
            if isinstance(obj, dict) and p in obj:
                obj = obj[p]
            else:
                return None
        return obj
    return resolver


# ---------------------------------------------------------------------------
# Littéraux
# ---------------------------------------------------------------------------

class TestLiterals:
    def test_number_int(self):
        assert evaluate("42") == 42

    def test_number_float(self):
        assert evaluate("3.14") == 3.14

    def test_string_double_quotes(self):
        assert evaluate('"hello"') == "hello"

    def test_string_single_quotes(self):
        assert evaluate("'world'") == "world"

    def test_true(self):
        assert evaluate("TRUE") is True
        assert evaluate("true") is True

    def test_false(self):
        assert evaluate("FALSE") is False

    def test_null(self):
        assert evaluate("NULL") is None
        assert evaluate("null") is None

    def test_empty(self):
        assert evaluate("") is None


# ---------------------------------------------------------------------------
# Arithmétique
# ---------------------------------------------------------------------------

class TestArithmetic:
    def test_addition(self):
        assert evaluate("1 + 2") == 3.0

    def test_subtraction(self):
        assert evaluate("10 - 3") == 7.0

    def test_multiplication(self):
        assert evaluate("4 * 5") == 20.0

    def test_division(self):
        assert evaluate("10 / 4") == 2.5

    def test_division_by_zero(self):
        assert evaluate("10 / 0") == 0

    def test_precedence(self):
        assert evaluate("2 + 3 * 4") == 14.0

    def test_parentheses(self):
        assert evaluate("(2 + 3) * 4") == 20.0

    def test_negative(self):
        assert evaluate("-5 + 3") == -2.0

    def test_power(self):
        assert evaluate("2 ^ 3") == 8.0

    def test_modulo_fn(self):
        assert evaluate("MOD(10, 3)") == 1.0


# ---------------------------------------------------------------------------
# Comparaisons
# ---------------------------------------------------------------------------

class TestComparison:
    def test_equal(self):
        assert evaluate("1 == 1") is True
        assert evaluate("1 == 2") is False

    def test_not_equal(self):
        assert evaluate("1 != 2") is True
        assert evaluate("1 <> 2") is True

    def test_less_than(self):
        assert evaluate("1 < 2") is True
        assert evaluate("2 < 1") is False

    def test_greater_than(self):
        assert evaluate("3 > 2") is True

    def test_less_equal(self):
        assert evaluate("2 <= 2") is True

    def test_greater_equal(self):
        assert evaluate("3 >= 3") is True

    def test_string_equal(self):
        assert evaluate('"abc" == "abc"') is True
        assert evaluate('"abc" == "def"') is False


# ---------------------------------------------------------------------------
# Opérateurs logiques
# ---------------------------------------------------------------------------

class TestLogical:
    def test_and_op(self):
        assert evaluate("TRUE && TRUE") is True
        assert evaluate("TRUE && FALSE") is False

    def test_or_op(self):
        assert evaluate("FALSE || TRUE") is True
        assert evaluate("FALSE || FALSE") is False

    def test_not_op(self):
        assert evaluate("!TRUE") is False
        assert evaluate("!FALSE") is True

    def test_combined(self):
        assert evaluate("TRUE && (FALSE || TRUE)") is True


# ---------------------------------------------------------------------------
# Concaténation
# ---------------------------------------------------------------------------

class TestConcat:
    def test_ampersand(self):
        assert evaluate('"Hello" & " " & "World"') == "Hello World"

    def test_concat_number(self):
        assert evaluate('"Value: " & 42') == "Value: 42"


# ---------------------------------------------------------------------------
# Fonctions logiques
# ---------------------------------------------------------------------------

class TestLogicalFunctions:
    def test_and_fn(self):
        assert evaluate("AND(TRUE, TRUE)") is True
        assert evaluate("AND(TRUE, FALSE)") is False

    def test_or_fn(self):
        assert evaluate("OR(FALSE, TRUE)") is True

    def test_not_fn(self):
        assert evaluate("NOT(TRUE)") is False

    def test_if_fn(self):
        assert evaluate("IF(TRUE, 1, 2)") == 1
        assert evaluate("IF(FALSE, 1, 2)") == 2

    def test_case_fn(self):
        resolver = make_resolver({"Status": "B"})
        engine = FormulaEngine(resolver)
        assert engine.evaluate('CASE(Status, "A", 1, "B", 2, 0)') == 2

    def test_case_default(self):
        resolver = make_resolver({"Status": "C"})
        engine = FormulaEngine(resolver)
        assert engine.evaluate('CASE(Status, "A", 1, "B", 2, 99)') == 99


# ---------------------------------------------------------------------------
# Fonctions de test
# ---------------------------------------------------------------------------

class TestTestFunctions:
    def test_isblank_null(self):
        resolver = make_resolver({"x": None})
        assert FormulaEngine(resolver).evaluate("ISBLANK(x)") is True

    def test_isblank_empty(self):
        resolver = make_resolver({"x": ""})
        assert FormulaEngine(resolver).evaluate("ISBLANK(x)") is True

    def test_isblank_value(self):
        resolver = make_resolver({"x": "hello"})
        assert FormulaEngine(resolver).evaluate("ISBLANK(x)") is False

    def test_isnull(self):
        resolver = make_resolver({"x": None})
        assert FormulaEngine(resolver).evaluate("ISNULL(x)") is True

    def test_ispickval(self):
        resolver = make_resolver({"Stage": "Closed Won"})
        engine = FormulaEngine(resolver)
        assert engine.evaluate('ISPICKVAL(Stage, "Closed Won")') is True
        assert engine.evaluate('ISPICKVAL(Stage, "Open")') is False

    def test_nullvalue(self):
        resolver = make_resolver({"x": None})
        assert FormulaEngine(resolver).evaluate('NULLVALUE(x, "default")') == "default"

    def test_blankvalue(self):
        resolver = make_resolver({"x": ""})
        assert FormulaEngine(resolver).evaluate('BLANKVALUE(x, "fallback")') == "fallback"


# ---------------------------------------------------------------------------
# Fonctions texte
# ---------------------------------------------------------------------------

class TestTextFunctions:
    def test_text(self):
        assert evaluate("TEXT(42)") == "42"
        assert evaluate("TEXT(TRUE)") == "true"

    def test_len(self):
        assert evaluate('LEN("hello")') == 5

    def test_trim(self):
        assert evaluate('TRIM("  hi  ")') == "hi"

    def test_upper(self):
        assert evaluate('UPPER("hello")') == "HELLO"

    def test_lower(self):
        assert evaluate('LOWER("HELLO")') == "hello"

    def test_left(self):
        assert evaluate('LEFT("abcdef", 3)') == "abc"

    def test_right(self):
        assert evaluate('RIGHT("abcdef", 3)') == "def"

    def test_mid(self):
        # Salesforce MID est 1-indexé
        assert evaluate('MID("abcdef", 2, 3)') == "bcd"

    def test_substitute(self):
        assert evaluate('SUBSTITUTE("hello world", "world", "SF")') == "hello SF"

    def test_contains(self):
        assert evaluate('CONTAINS("hello world", "world")') is True
        assert evaluate('CONTAINS("hello", "xyz")') is False

    def test_begins(self):
        assert evaluate('BEGINS("hello", "hel")') is True
        assert evaluate('BEGINS("hello", "xyz")') is False

    def test_find(self):
        assert evaluate('FIND("lo", "hello")') == 4  # 1-indexé
        assert evaluate('FIND("xyz", "hello")') == 0

    def test_concatenate(self):
        assert evaluate('CONCATENATE("a", "b", "c")') == "abc"

    def test_value(self):
        assert evaluate('VALUE("42")') == 42
        assert evaluate('VALUE("3.14")') == 3.14

    def test_regex(self):
        assert evaluate('REGEX("abc123", "[a-z]+[0-9]+")') is True
        assert evaluate('REGEX("abc", "[0-9]+")') is False


# ---------------------------------------------------------------------------
# Fonctions date
# ---------------------------------------------------------------------------

class TestDateFunctions:
    def test_today(self):
        result = evaluate("TODAY()")
        assert isinstance(result, date)
        assert result == date.today()

    def test_now(self):
        result = evaluate("NOW()")
        assert isinstance(result, datetime)

    def test_year(self):
        assert evaluate("YEAR(TODAY())") == date.today().year

    def test_month(self):
        assert evaluate("MONTH(TODAY())") == date.today().month

    def test_day(self):
        assert evaluate("DAY(TODAY())") == date.today().day

    def test_date(self):
        result = evaluate("DATE(2024, 6, 15)")
        assert result == date(2024, 6, 15)

    def test_datevalue_string(self):
        result = evaluate('DATEVALUE("2024-06-15")')
        assert result == date(2024, 6, 15)

    def test_year_from_string(self):
        resolver = make_resolver({"d": "2024-03-15"})
        assert FormulaEngine(resolver).evaluate("YEAR(d)") == 2024

    def test_addmonths(self):
        result = evaluate("ADDMONTHS(DATE(2024, 1, 31), 1)")
        assert result == date(2024, 2, 29)  # 2024 est bissextile


# ---------------------------------------------------------------------------
# Fonctions maths
# ---------------------------------------------------------------------------

class TestMathFunctions:
    def test_abs(self):
        assert evaluate("ABS(-5)") == 5.0

    def test_ceiling(self):
        assert evaluate("CEILING(3.2)") == 4

    def test_floor(self):
        assert evaluate("FLOOR(3.8)") == 3

    def test_round(self):
        assert evaluate("ROUND(3.456, 2)") == 3.46

    def test_max(self):
        assert evaluate("MAX(1, 5, 3)") == 5.0

    def test_min(self):
        assert evaluate("MIN(1, 5, 3)") == 1.0

    def test_sqrt(self):
        assert evaluate("SQRT(9)") == 3.0

    def test_log(self):
        assert evaluate("LOG(100)") == pytest.approx(2.0)

    def test_ln(self):
        assert evaluate("LN(1)") == 0.0

    def test_exp(self):
        assert evaluate("EXP(0)") == 1.0


# ---------------------------------------------------------------------------
# Références
# ---------------------------------------------------------------------------

class TestReferences:
    def test_simple_field(self):
        resolver = make_resolver({"Name": "Acme"})
        assert FormulaEngine(resolver).evaluate("Name") == "Acme"

    def test_dotted_field(self):
        resolver = make_resolver({"Account": {"Name": "Acme"}})
        assert FormulaEngine(resolver).evaluate("Account.Name") == "Acme"

    def test_dollar_record(self):
        resolver = make_resolver({"$Record.Status__c": "Active"})
        engine = FormulaEngine(resolver)
        assert engine.evaluate("$Record.Status__c") == "Active"

    def test_unknown_ref_is_none(self):
        assert evaluate("UnknownField") is None

    def test_formula_with_refs(self):
        resolver = make_resolver({"Amount": 100, "Discount": 0.1})
        engine = FormulaEngine(resolver)
        assert engine.evaluate("Amount * (1 - Discount)") == 90.0


# ---------------------------------------------------------------------------
# Merge fields
# ---------------------------------------------------------------------------

class TestMergeFields:
    def test_resolve_merge_fields(self):
        resolver = make_resolver({"Name": "Acme", "City": "Paris"})
        result = resolve_merge_fields("Bonjour {!Name} de {!City}", resolver)
        assert result == "Bonjour Acme de Paris"

    def test_merge_field_null(self):
        resolver = make_resolver({})
        result = resolve_merge_fields("Hello {!Missing}", resolver)
        assert result == "Hello "


# ---------------------------------------------------------------------------
# Expressions complexes (cas réels SF)
# ---------------------------------------------------------------------------

class TestComplexExpressions:
    def test_validation_rule_isblank_and(self):
        resolver = make_resolver({"Phone": None, "Email": ""})
        engine = FormulaEngine(resolver)
        assert engine.evaluate("AND(ISBLANK(Phone), ISBLANK(Email))") is True

    def test_validation_rule_ispickval(self):
        resolver = make_resolver({"StageName": "Closed Won", "Amount": 0})
        engine = FormulaEngine(resolver)
        assert engine.evaluate('ISPICKVAL(StageName, "Closed Won") && Amount == 0') is True

    def test_formula_field_discount(self):
        resolver = make_resolver({"Amount": 200, "DiscountPercent__c": 15})
        engine = FormulaEngine(resolver)
        result = engine.evaluate("Amount * DiscountPercent__c / 100")
        assert result == 30.0

    def test_nested_if(self):
        resolver = make_resolver({"Score": 85})
        engine = FormulaEngine(resolver)
        result = engine.evaluate(
            'IF(Score >= 90, "A", IF(Score >= 80, "B", IF(Score >= 70, "C", "F")))'
        )
        assert result == "B"

    def test_concat_formula(self):
        resolver = make_resolver({"FirstName": "John", "LastName": "Doe"})
        engine = FormulaEngine(resolver)
        result = engine.evaluate('FirstName & " " & LastName')
        assert result == "John Doe"


# ---------------------------------------------------------------------------
# Erreurs
# ---------------------------------------------------------------------------

class TestErrors:
    def test_unknown_function(self):
        with pytest.raises(FormulaError, match="Fonction inconnue"):
            evaluate("FOOBAR(1)")

    def test_bad_syntax(self):
        with pytest.raises(FormulaError):
            evaluate("@@@")
