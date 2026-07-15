"""Lexer SOQL — tokenise une requête SOQL en tokens."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TT(Enum):
    """Token types SOQL."""
    # Mots-clés
    SELECT = auto()
    FROM = auto()
    WHERE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    IN = auto()
    LIKE = auto()
    ORDER = auto()
    BY = auto()
    GROUP = auto()
    HAVING = auto()
    LIMIT = auto()
    ASC = auto()
    DESC = auto()
    NULLS = auto()
    FIRST = auto()
    LAST = auto()
    NULL = auto()
    TRUE = auto()
    FALSE = auto()
    # Fonctions d'agrégation (traitées comme mots-clés)
    COUNT = auto()
    SUM = auto()
    MIN = auto()
    MAX = auto()
    AVG = auto()
    # Littéraux de date
    TODAY = auto()
    YESTERDAY = auto()
    # Opérateurs
    EQ = auto()       # =
    NEQ = auto()      # !=
    LT = auto()       # <
    GT = auto()       # >
    LTE = auto()      # <=
    GTE = auto()      # >=
    # Symboles
    LPAREN = auto()   # (
    RPAREN = auto()   # )
    COMMA = auto()    # ,
    DOT = auto()      # .
    STAR = auto()     # *
    # Valeurs
    STRING = auto()   # 'hello'
    INTEGER = auto()  # 42
    DECIMAL = auto()  # 3.14
    IDENT = auto()    # nom_champ, SObject, etc.
    BIND = auto()     # :varName, :obj.field
    # Fin
    EOF = auto()


# Mots-clés SOQL (case-insensitive)
_KEYWORDS = {
    "select": TT.SELECT, "from": TT.FROM, "where": TT.WHERE,
    "and": TT.AND, "or": TT.OR, "not": TT.NOT, "in": TT.IN,
    "like": TT.LIKE, "order": TT.ORDER, "by": TT.BY,
    "group": TT.GROUP, "having": TT.HAVING, "limit": TT.LIMIT,
    "asc": TT.ASC, "desc": TT.DESC,
    "nulls": TT.NULLS, "first": TT.FIRST, "last": TT.LAST,
    "null": TT.NULL, "true": TT.TRUE, "false": TT.FALSE,
    "count": TT.COUNT, "sum": TT.SUM, "min": TT.MIN, "max": TT.MAX, "avg": TT.AVG,
    "today": TT.TODAY, "yesterday": TT.YESTERDAY,
}

# Clauses WITH à ignorer
_WITH_SKIP = {"system_mode", "user_mode", "security_enforced"}


@dataclass
class SoqlToken:
    type: TT
    value: str
    pos: int = 0


def tokenize(soql: str) -> list[SoqlToken]:
    """Transforme une chaîne SOQL en liste de tokens."""
    tokens = []
    i = 0
    n = len(soql)

    while i < n:
        ch = soql[i]

        # Commentaires /* ... */ et // (hors chaînes — traitées plus bas)
        if ch == "/" and i + 1 < n and soql[i + 1] == "*":
            end = soql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if ch == "/" and i + 1 < n and soql[i + 1] == "/":
            end = soql.find("\n", i + 2)
            i = n if end == -1 else end + 1
            continue

        # Whitespace
        if ch in " \t\r\n":
            i += 1
            continue

        # Commentaire ligne
        if ch == '-' and i + 1 < n and soql[i + 1] == '-':
            while i < n and soql[i] != '\n':
                i += 1
            continue

        # String literal
        if ch == "'":
            start = i
            i += 1
            val = ""
            while i < n:
                if soql[i] == "'" and i + 1 < n and soql[i + 1] == "'":
                    val += "'"
                    i += 2
                elif soql[i] == "'":
                    i += 1
                    break
                else:
                    val += soql[i]
                    i += 1
            tokens.append(SoqlToken(TT.STRING, val, start))
            continue

        # Nombre
        if ch.isdigit() or (ch == '-' and i + 1 < n and soql[i + 1].isdigit()):
            start = i
            if ch == '-':
                i += 1
            while i < n and soql[i].isdigit():
                i += 1
            if i < n and soql[i] == '.':
                i += 1
                while i < n and soql[i].isdigit():
                    i += 1
                tokens.append(SoqlToken(TT.DECIMAL, soql[start:i], start))
            else:
                tokens.append(SoqlToken(TT.INTEGER, soql[start:i], start))
            continue

        # Bind variable :varName, :obj.field ou :UserInfo.getUsername()
        if ch == ':':
            start = i
            i += 1
            path = ""
            while i < n:
                c = soql[i]
                if c.isalnum() or c in "_.":
                    path += c
                    i += 1
                elif c == "(" and i + 1 < n and soql[i + 1] == ")":
                    path += "()"
                    i += 2
                else:
                    break
            tokens.append(SoqlToken(TT.BIND, path, start))
            continue

        # Opérateurs multi-caractères
        if ch == '!' and i + 1 < n and soql[i + 1] == '=':
            tokens.append(SoqlToken(TT.NEQ, "!=", i))
            i += 2
            continue
        if ch == '<' and i + 1 < n and soql[i + 1] == '=':
            tokens.append(SoqlToken(TT.LTE, "<=", i))
            i += 2
            continue
        if ch == '>' and i + 1 < n and soql[i + 1] == '=':
            tokens.append(SoqlToken(TT.GTE, ">=", i))
            i += 2
            continue

        # Opérateurs / symboles simples
        simple = {
            '=': TT.EQ, '<': TT.LT, '>': TT.GT,
            '(': TT.LPAREN, ')': TT.RPAREN, ',': TT.COMMA,
            '.': TT.DOT, '*': TT.STAR,
        }
        if ch in simple:
            tokens.append(SoqlToken(simple[ch], ch, i))
            i += 1
            continue

        # Identifiant ou mot-clé
        if ch.isalpha() or ch == '_':
            start = i
            while i < n and (soql[i].isalnum() or soql[i] == '_'):
                i += 1
            word = soql[start:i]
            lower = word.lower()

            # WITH SYSTEM_MODE / USER_MODE / SECURITY_ENFORCED → ignorer
            if lower == "with":
                # Regarder le mot suivant
                j = i
                while j < n and soql[j] in " \t\r\n":
                    j += 1
                k = j
                while k < n and (soql[k].isalnum() or soql[k] == '_'):
                    k += 1
                next_word = soql[j:k].lower()
                if next_word in _WITH_SKIP:
                    i = k  # sauter les deux mots
                    continue

            tt = _KEYWORDS.get(lower, TT.IDENT)
            tokens.append(SoqlToken(tt, word, start))
            continue

        # Caractère inconnu — ignorer (brackets, etc.)
        i += 1

    tokens.append(SoqlToken(TT.EOF, "", n))
    return tokens
