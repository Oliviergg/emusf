"""Moteur de formules Salesforce unifié.

Évalue les formules utilisées dans les flows, validation rules, formula fields
et expressions Visualforce. Le langage est commun ; seule la résolution des
références change selon le contexte (callback ``resolver``).

Grammaire (récursive descendante) :

    expr        → or_expr
    or_expr     → and_expr ( '||' and_expr )*
    and_expr    → equality ( '&&' equality )*
    equality    → comparison ( ('==' | '!=' | '<>') comparison )*
    comparison  → addition ( ('<' | '<=' | '>' | '>=') addition )*
    addition    → multiply ( ('+' | '-') multiply )*
    multiply    → unary ( ('*' | '/') unary )*
    unary       → '!' unary | '-' unary | primary
    primary     → NUMBER | STRING | BOOL | NULL
                | IDENT '(' args ')'      -- appel de fonction
                | IDENT ( '.' IDENT )*    -- référence
                | '(' expr ')'
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"""
    (?P<NUMBER>     \d+(?:\.\d+)? )
  | (?P<STRING>     "(?:[^"\\]|\\.)*" | '(?:[^'\\]|\\.)*' )
  | (?P<OP>         [!=]=|<>|<=|>=|&&|\|\||[+\-*/<>!(),.\^] )
  | (?P<AMP>        &(?!&) )          # concaténation &
  | (?P<IDENT>      [A-Za-z_$][A-Za-z0-9_]* )
  | (?P<SKIP>       \s+ )
""", re.VERBOSE)


class Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str):
        self.kind = kind
        self.value = value

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r})"


def _tokenize(expression: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(expression):
        m = _TOKEN_RE.match(expression, pos)
        if not m:
            raise FormulaError(f"Caractère inattendu à la position {pos}: {expression[pos:]!r}")
        pos = m.end()
        if m.lastgroup == "SKIP":
            continue
        if m.lastgroup == "AMP":
            tokens.append(Token("OP", "&"))
        else:
            tokens.append(Token(m.lastgroup, m.group()))
    tokens.append(Token("EOF", ""))
    return tokens


# ---------------------------------------------------------------------------
# Résolveur par défaut (noop)
# ---------------------------------------------------------------------------

def _noop_resolver(ref: str) -> Any:
    return None


# ---------------------------------------------------------------------------
# Parser / Évaluateur
# ---------------------------------------------------------------------------

class FormulaEngine:
    """Évalue une expression de formule Salesforce.

    Parameters
    ----------
    resolver : callable(str) -> Any
        Fonction qui résout une référence (ex: ``"$Record.Name"``,
        ``"MyField__c"``) et renvoie sa valeur.
    """

    def __init__(self, resolver: Callable[[str], Any] | None = None):
        self.resolver = resolver or _noop_resolver

    def evaluate(self, expression: str) -> Any:
        """Évalue *expression* et renvoie le résultat."""
        expression = expression.strip()
        if not expression:
            return None
        tokens = _tokenize(expression)
        self._tokens = tokens
        self._pos = 0
        result = self._parse_expr()
        return result

    # -- helpers de lecture de tokens --

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: str, value: str | None = None) -> Token:
        tok = self._advance()
        if tok.kind != kind or (value is not None and tok.value != value):
            raise FormulaError(f"Attendu {kind}({value!r}), obtenu {tok}")
        return tok

    def _match_op(self, *ops: str) -> Token | None:
        tok = self._peek()
        if tok.kind == "OP" and tok.value in ops:
            return self._advance()
        return None

    # -- grammaire récursive descendante --

    def _parse_expr(self) -> Any:
        return self._parse_or()

    def _parse_or(self) -> Any:
        left = self._parse_and()
        while self._match_op("||"):
            right = self._parse_and()
            left = bool(left) or bool(right)
        return left

    def _parse_and(self) -> Any:
        left = self._parse_equality()
        while self._match_op("&&"):
            right = self._parse_equality()
            left = bool(left) and bool(right)
        return left

    def _parse_equality(self) -> Any:
        left = self._parse_comparison()
        while True:
            op = self._match_op("==", "!=", "<>")
            if not op:
                break
            right = self._parse_comparison()
            if op.value == "==":
                left = _eq(left, right)
            else:
                left = not _eq(left, right)
        return left

    def _parse_comparison(self) -> Any:
        left = self._parse_concat()
        while True:
            op = self._match_op("<", "<=", ">", ">=")
            if not op:
                break
            right = self._parse_concat()
            ln, rn = _num(left), _num(right)
            if op.value == "<":
                left = ln < rn
            elif op.value == "<=":
                left = ln <= rn
            elif op.value == ">":
                left = ln > rn
            else:
                left = ln >= rn
        return left

    def _parse_concat(self) -> Any:
        """Concaténation avec ``&`` (opérateur Salesforce)."""
        left = self._parse_addition()
        while self._match_op("&"):
            right = self._parse_addition()
            left = _str(left) + _str(right)
        return left

    def _parse_addition(self) -> Any:
        left = self._parse_multiply()
        while True:
            op = self._match_op("+", "-")
            if not op:
                break
            right = self._parse_multiply()
            if op.value == "+":
                left = _num(left) + _num(right)
            else:
                left = _num(left) - _num(right)
        return left

    def _parse_multiply(self) -> Any:
        left = self._parse_power()
        while True:
            op = self._match_op("*", "/")
            if not op:
                break
            right = self._parse_power()
            if op.value == "*":
                left = _num(left) * _num(right)
            else:
                rn = _num(right)
                left = _num(left) / rn if rn != 0 else 0
        return left

    def _parse_power(self) -> Any:
        """Exponentiation avec ``^``."""
        base = self._parse_unary()
        if self._match_op("^"):
            exp = self._parse_power()  # associativité droite
            return _num(base) ** _num(exp)
        return base

    def _parse_unary(self) -> Any:
        if self._match_op("!"):
            return not self._parse_unary()
        if self._peek().kind == "OP" and self._peek().value == "-":
            self._advance()
            return -_num(self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Any:
        tok = self._peek()

        # Nombre
        if tok.kind == "NUMBER":
            self._advance()
            return float(tok.value) if "." in tok.value else int(tok.value)

        # Chaîne
        if tok.kind == "STRING":
            self._advance()
            return tok.value[1:-1]  # retirer les quotes

        # Parenthèses
        if tok.kind == "OP" and tok.value == "(":
            self._advance()
            val = self._parse_expr()
            self._expect("OP", ")")
            return val

        # Identifiant : mot-clé, fonction ou référence
        if tok.kind == "IDENT":
            return self._parse_ident()

        raise FormulaError(f"Expression inattendue: {tok}")

    def _parse_ident(self) -> Any:
        """Parse un identifiant : mot-clé, appel de fonction, ou référence."""
        tok = self._advance()
        name = tok.value

        # Mots-clés
        upper = name.upper()
        if upper == "TRUE":
            return True
        if upper == "FALSE":
            return False
        if upper == "NULL":
            return None

        # Appel de fonction : IDENT(...)
        if self._peek().kind == "OP" and self._peek().value == "(":
            self._advance()  # consommer '('
            args = self._parse_args()
            self._expect("OP", ")")
            return self._call_function(upper, args)

        # Référence avec chemin pointé : IDENT.IDENT.IDENT...
        parts = [name]
        while self._peek().kind == "OP" and self._peek().value == ".":
            self._advance()  # consommer '.'
            next_tok = self._advance()
            if next_tok.kind != "IDENT":
                raise FormulaError(f"Identifiant attendu après '.', obtenu {next_tok}")
            parts.append(next_tok.value)

        ref = ".".join(parts)
        return self.resolver(ref)

    def _parse_args(self) -> list[Any]:
        """Parse les arguments d'un appel de fonction (évalués paresseusement)."""
        # On retourne des « thunks » pour certaines fonctions (ex: IF)
        # mais pour simplifier on évalue tout sauf cas particuliers.
        # => On stocke les positions et parse à la demande.
        # Approche simple : on évalue chaque argument.
        args = []
        if self._peek().kind == "OP" and self._peek().value == ")":
            return args
        args.append(self._parse_expr())
        while self._match_op(","):
            args.append(self._parse_expr())
        return args

    # -- fonctions built-in --

    def _call_function(self, name: str, args: list[Any]) -> Any:
        """Dispatch un appel de fonction Salesforce."""
        fn = _FUNCTIONS.get(name)
        if fn:
            return fn(args, self)
        raise FormulaError(f"Fonction inconnue: {name}")


# ---------------------------------------------------------------------------
# Fonctions Salesforce
# ---------------------------------------------------------------------------

def _fn_and(args, engine):
    return all(bool(a) for a in args)

def _fn_or(args, engine):
    return any(bool(a) for a in args)

def _fn_not(args, engine):
    return not bool(args[0]) if args else False

def _fn_if(args, engine):
    if len(args) < 3:
        return args[1] if args[0] else None
    return args[1] if args[0] else args[2]

def _fn_isblank(args, engine):
    val = args[0] if args else None
    return val is None or val == ""

def _fn_isnull(args, engine):
    return args[0] is None if args else True

def _fn_ispickval(args, engine):
    if len(args) < 2:
        return False
    return args[0] == args[1]

def _fn_text(args, engine):
    val = args[0] if args else None
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)

def _fn_value(args, engine):
    """VALUE(text) — convertit une chaîne en nombre."""
    val = args[0] if args else None
    if val is None:
        return 0
    try:
        s = str(val).strip()
        return float(s) if "." in s else int(s)
    except (ValueError, TypeError):
        return 0

def _fn_len(args, engine):
    val = args[0] if args else None
    return len(str(val)) if val is not None else 0

def _fn_trim(args, engine):
    val = args[0] if args else None
    return str(val).strip() if val is not None else ""

def _fn_upper(args, engine):
    val = args[0] if args else None
    return str(val).upper() if val is not None else ""

def _fn_lower(args, engine):
    val = args[0] if args else None
    return str(val).lower() if val is not None else ""

def _fn_left(args, engine):
    val = _str(args[0]) if args else ""
    n = int(_num(args[1])) if len(args) > 1 else 0
    return val[:n]

def _fn_right(args, engine):
    val = _str(args[0]) if args else ""
    n = int(_num(args[1])) if len(args) > 1 else 0
    return val[-n:] if n > 0 else ""

def _fn_mid(args, engine):
    val = _str(args[0]) if args else ""
    start = int(_num(args[1])) if len(args) > 1 else 0
    length = int(_num(args[2])) if len(args) > 2 else 0
    # Salesforce MID est 1-indexé
    return val[start - 1:start - 1 + length] if start > 0 else ""

def _fn_substitute(args, engine):
    val = _str(args[0]) if args else ""
    old = _str(args[1]) if len(args) > 1 else ""
    new = _str(args[2]) if len(args) > 2 else ""
    return val.replace(old, new)

def _fn_contains(args, engine):
    val = _str(args[0]) if args else ""
    sub = _str(args[1]) if len(args) > 1 else ""
    return sub in val

def _fn_begins(args, engine):
    val = _str(args[0]) if args else ""
    prefix = _str(args[1]) if len(args) > 1 else ""
    return val.startswith(prefix)

def _fn_find(args, engine):
    """FIND(search, text [, start]) — 1-indexé, 0 si non trouvé."""
    search = _str(args[0]) if args else ""
    text = _str(args[1]) if len(args) > 1 else ""
    start = int(_num(args[2])) - 1 if len(args) > 2 else 0
    idx = text.find(search, max(start, 0))
    return idx + 1 if idx >= 0 else 0

def _fn_concatenate(args, engine):
    return "".join(_str(a) for a in args)

def _fn_now(args, engine):
    return datetime.now()

def _fn_today(args, engine):
    return date.today()

def _fn_year(args, engine):
    val = args[0] if args else None
    if isinstance(val, (date, datetime)):
        return val.year
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).year
        except ValueError:
            pass
    return 0

def _fn_month(args, engine):
    val = args[0] if args else None
    if isinstance(val, (date, datetime)):
        return val.month
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).month
        except ValueError:
            pass
    return 0

def _fn_day(args, engine):
    val = args[0] if args else None
    if isinstance(val, (date, datetime)):
        return val.day
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).day
        except ValueError:
            pass
    return 0

def _fn_date(args, engine):
    """DATE(year, month, day)"""
    if len(args) < 3:
        return None
    return date(int(_num(args[0])), int(_num(args[1])), int(_num(args[2])))

def _fn_datetimevalue(args, engine):
    """DATETIMEVALUE(text)"""
    val = args[0] if args else None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None

def _fn_datevalue(args, engine):
    """DATEVALUE(text)"""
    val = args[0] if args else None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return None

def _fn_abs(args, engine):
    return abs(_num(args[0])) if args else 0

def _fn_ceiling(args, engine):
    import math
    return math.ceil(_num(args[0])) if args else 0

def _fn_floor(args, engine):
    import math
    return math.floor(_num(args[0])) if args else 0

def _fn_round(args, engine):
    val = _num(args[0]) if args else 0
    decimals = int(_num(args[1])) if len(args) > 1 else 0
    return round(val, decimals)

def _fn_max(args, engine):
    if not args:
        return 0
    return max(_num(a) for a in args)

def _fn_min(args, engine):
    if not args:
        return 0
    return min(_num(a) for a in args)

def _fn_mod(args, engine):
    if len(args) < 2:
        return 0
    divisor = _num(args[1])
    return _num(args[0]) % divisor if divisor != 0 else 0

def _fn_sqrt(args, engine):
    import math
    return math.sqrt(_num(args[0])) if args else 0

def _fn_log(args, engine):
    import math
    val = _num(args[0])
    return math.log10(val) if val > 0 else 0

def _fn_ln(args, engine):
    import math
    val = _num(args[0])
    return math.log(val) if val > 0 else 0

def _fn_exp(args, engine):
    import math
    return math.exp(_num(args[0])) if args else 1

def _fn_nullvalue(args, engine):
    """NULLVALUE(expr, substitute) — renvoie substitute si expr est null."""
    if len(args) < 2:
        return args[0] if args else None
    return args[0] if args[0] is not None else args[1]

def _fn_blankvalue(args, engine):
    """BLANKVALUE(expr, substitute) — renvoie substitute si expr est null ou vide."""
    if len(args) < 2:
        return args[0] if args else None
    val = args[0]
    if val is None or val == "":
        return args[1]
    return val

def _fn_case(args, engine):
    """CASE(expr, val1, result1, val2, result2, ..., else_result)"""
    if len(args) < 3:
        return None
    expr_val = args[0]
    i = 1
    while i + 1 < len(args):
        if _eq(expr_val, args[i]):
            return args[i + 1]
        i += 2
    # Dernier argument = else
    if i < len(args):
        return args[i]
    return None

def _fn_br(args, engine):
    """BR() — retour à la ligne."""
    return "\n"

def _fn_hyperlink(args, engine):
    """HYPERLINK(url, label) — simplifié, retourne l'URL."""
    return args[0] if args else ""

def _fn_image(args, engine):
    """IMAGE(url, alt) — simplifié, retourne l'URL."""
    return args[0] if args else ""

def _fn_urlfor(args, engine):
    """URLFOR(...) — simplifié, retourne le premier argument."""
    return args[0] if args else ""

def _fn_regex(args, engine):
    """REGEX(text, pattern)"""
    if len(args) < 2:
        return False
    text = _str(args[0])
    pattern = _str(args[1])
    return bool(re.fullmatch(pattern, text))

def _fn_includes(args, engine):
    """INCLUDES(multiselect_field, value)"""
    if len(args) < 2:
        return False
    field_val = _str(args[0])
    value = _str(args[1])
    return value in field_val.split(";")

def _fn_addmonths(args, engine):
    """ADDMONTHS(date, num_months)"""
    if len(args) < 2:
        return None
    val = args[0]
    months = int(_num(args[1]))
    if isinstance(val, str):
        try:
            val = datetime.fromisoformat(val.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    if isinstance(val, datetime):
        val = val.date()
    if isinstance(val, date):
        month = val.month - 1 + months
        year = val.year + month // 12
        month = month % 12 + 1
        day = min(val.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
        return date(year, month, day)
    return None


# Registre des fonctions
_FUNCTIONS: dict[str, Callable] = {
    # Logiques
    "AND": _fn_and,
    "OR": _fn_or,
    "NOT": _fn_not,
    "IF": _fn_if,
    "CASE": _fn_case,
    # Tests
    "ISBLANK": _fn_isblank,
    "ISNULL": _fn_isnull,
    "ISPICKVAL": _fn_ispickval,
    "NULLVALUE": _fn_nullvalue,
    "BLANKVALUE": _fn_blankvalue,
    # Texte
    "TEXT": _fn_text,
    "VALUE": _fn_value,
    "LEN": _fn_len,
    "TRIM": _fn_trim,
    "UPPER": _fn_upper,
    "LOWER": _fn_lower,
    "LEFT": _fn_left,
    "RIGHT": _fn_right,
    "MID": _fn_mid,
    "SUBSTITUTE": _fn_substitute,
    "CONTAINS": _fn_contains,
    "BEGINS": _fn_begins,
    "FIND": _fn_find,
    "CONCATENATE": _fn_concatenate,
    "BR": _fn_br,
    "HYPERLINK": _fn_hyperlink,
    "IMAGE": _fn_image,
    "URLFOR": _fn_urlfor,
    "REGEX": _fn_regex,
    "INCLUDES": _fn_includes,
    # Dates
    "NOW": _fn_now,
    "TODAY": _fn_today,
    "YEAR": _fn_year,
    "MONTH": _fn_month,
    "DAY": _fn_day,
    "DATE": _fn_date,
    "DATETIMEVALUE": _fn_datetimevalue,
    "DATEVALUE": _fn_datevalue,
    "ADDMONTHS": _fn_addmonths,
    # Maths
    "ABS": _fn_abs,
    "CEILING": _fn_ceiling,
    "FLOOR": _fn_floor,
    "ROUND": _fn_round,
    "MAX": _fn_max,
    "MIN": _fn_min,
    "MOD": _fn_mod,
    "SQRT": _fn_sqrt,
    "LOG": _fn_log,
    "LN": _fn_ln,
    "EXP": _fn_exp,
}


# ---------------------------------------------------------------------------
# Utilitaires de coercition
# ---------------------------------------------------------------------------

def _eq(a: Any, b: Any) -> bool:
    """Comparaison d'égalité flexible à la Salesforce."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if type(a) == type(b):
        return a == b
    # Comparer comme strings si types différents
    return str(a).lower() == str(b).lower()


def _num(v: Any) -> float:
    """Convertit en nombre pour les opérations arithmétiques."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _str(v: Any) -> str:
    """Convertit en chaîne."""
    if v is None:
        return ""
    return str(v)


# ---------------------------------------------------------------------------
# Helpers publics
# ---------------------------------------------------------------------------

def resolve_merge_fields(text: str, resolver: Callable[[str], Any]) -> str:
    """Résout les merge fields ``{!ref}`` dans une chaîne de texte.

    Utilisé pour les text templates, labels et formules flow qui contiennent
    des références ``{!variable}`` ou ``{!$Record.Field}``.
    """
    def _replacer(m):
        ref = m.group(1)
        val = resolver(ref)
        return str(val) if val is not None else ""
    return re.sub(r'\{!([^}]+)\}', _replacer, text)


def evaluate(expression: str, resolver: Callable[[str], Any] | None = None) -> Any:
    """Raccourci pour évaluer une formule avec un resolver donné."""
    engine = FormulaEngine(resolver)
    return engine.evaluate(expression)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class FormulaError(Exception):
    """Erreur lors de l'évaluation d'une formule."""
    pass
