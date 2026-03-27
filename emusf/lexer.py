"""Lexer Apex — transforme du code source en tokens."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class TokenType(Enum):
    # Literals
    STRING = auto()       # 'hello'
    INTEGER = auto()      # 42
    DECIMAL = auto()      # 3.14
    TRUE = auto()         # true
    FALSE = auto()        # false
    NULL = auto()         # null

    # Identifiers & keywords
    IDENT = auto()        # variableName
    NEW = auto()          # new
    RETURN = auto()       # return
    IF = auto()           # if
    ELSE = auto()         # else
    FOR = auto()          # for
    WHILE = auto()        # while
    SWITCH = auto()       # switch
    ON = auto()           # on
    WHEN = auto()         # when
    TRY = auto()          # try
    CATCH = auto()        # catch
    THROW = auto()        # throw
    INSERT = auto()       # insert
    UPDATE = auto()       # update
    DELETE = auto()       # delete
    INSTANCEOF = auto()   # instanceof

    # Operators
    PLUS = auto()         # +
    MINUS = auto()        # -
    STAR = auto()         # *
    SLASH = auto()        # /
    EQ = auto()           # ==
    NEQ = auto()          # !=
    LT = auto()           # <
    GT = auto()           # >
    LTE = auto()          # <=
    GTE = auto()          # >=
    AND = auto()          # &&
    OR = auto()           # ||
    NOT = auto()          # !
    ASSIGN = auto()       # =
    QUESTION = auto()     # ?
    COLON = auto()        # :
    NULLCOAL = auto()     # ??
    ARROW = auto()        # =>

    # Delimiters
    LPAREN = auto()       # (
    RPAREN = auto()       # )
    LBRACE = auto()       # {
    RBRACE = auto()       # }
    LBRACKET = auto()     # [
    RBRACKET = auto()     # ]
    DOT = auto()          # .
    COMMA = auto()        # ,
    SEMI = auto()         # ;

    # Special
    EOF = auto()
    SOQL = auto()         # [SELECT ...]


KEYWORDS = {
    "new": TokenType.NEW,
    "return": TokenType.RETURN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "for": TokenType.FOR,
    "while": TokenType.WHILE,
    "switch": TokenType.SWITCH,
    "on": TokenType.ON,
    "when": TokenType.WHEN,
    "try": TokenType.TRY,
    "catch": TokenType.CATCH,
    "throw": TokenType.THROW,
    "insert": TokenType.INSERT,
    "update": TokenType.UPDATE,
    "delete": TokenType.DELETE,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "null": TokenType.NULL,
    "instanceof": TokenType.INSTANCEOF,
}


@dataclass
class Token:
    type: TokenType
    value: str
    line: int = 0
    col: int = 0

    def __repr__(self):
        if self.type in (TokenType.STRING, TokenType.INTEGER, TokenType.DECIMAL, TokenType.IDENT, TokenType.SOQL):
            return "Token({}, {})".format(self.type.name, repr(self.value))
        return "Token({})".format(self.type.name)


class LexerError(Exception):
    def __init__(self, msg, line=0, col=0):
        super().__init__("Lexer error at {}:{}: {}".format(line, col, msg))


class Lexer:
    """Tokenize du code Apex."""

    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens = []

    def tokenize(self) -> list:
        """Produit la liste complète de tokens."""
        while self.pos < len(self.source):
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.source):
                break

            ch = self.source[self.pos]

            # String literal
            if ch == "'":
                self.tokens.append(self._read_string())
                continue

            # Number
            if ch.isdigit():
                self.tokens.append(self._read_number())
                continue

            # SOQL inline [SELECT ...]
            if ch == "[":
                # Peek ahead to see if it's SOQL
                rest = self.source[self.pos + 1:].lstrip()
                if rest.upper().startswith("SELECT"):
                    self.tokens.append(self._read_soql())
                    continue
                self.tokens.append(Token(TokenType.LBRACKET, "[", self.line, self.col))
                self._advance()
                continue

            # Identifier / keyword
            if ch.isalpha() or ch == "_":
                self.tokens.append(self._read_ident())
                continue

            # Two-char operators (must check before single-char)
            two = self.source[self.pos:self.pos + 2]
            if two == "=>":
                self.tokens.append(Token(TokenType.ARROW, "=>", self.line, self.col))
                self._advance(2)
                continue
            if two == "==":
                self.tokens.append(Token(TokenType.EQ, "==", self.line, self.col))
                self._advance(2)
                continue
            if two == "!=":
                self.tokens.append(Token(TokenType.NEQ, "!=", self.line, self.col))
                self._advance(2)
                continue
            if two == "<=":
                self.tokens.append(Token(TokenType.LTE, "<=", self.line, self.col))
                self._advance(2)
                continue
            if two == ">=":
                self.tokens.append(Token(TokenType.GTE, ">=", self.line, self.col))
                self._advance(2)
                continue
            if two == "&&":
                self.tokens.append(Token(TokenType.AND, "&&", self.line, self.col))
                self._advance(2)
                continue
            if two == "||":
                self.tokens.append(Token(TokenType.OR, "||", self.line, self.col))
                self._advance(2)
                continue
            if two == "??":
                self.tokens.append(Token(TokenType.NULLCOAL, "??", self.line, self.col))
                self._advance(2)
                continue

            # Single-char operators
            single_map = {
                "+": TokenType.PLUS,
                "-": TokenType.MINUS,
                "*": TokenType.STAR,
                "/": TokenType.SLASH,
                "<": TokenType.LT,
                ">": TokenType.GT,
                "!": TokenType.NOT,
                "=": TokenType.ASSIGN,
                "?": TokenType.QUESTION,
                ":": TokenType.COLON,
                "(": TokenType.LPAREN,
                ")": TokenType.RPAREN,
                "{": TokenType.LBRACE,
                "}": TokenType.RBRACE,
                "]": TokenType.RBRACKET,
                ".": TokenType.DOT,
                ",": TokenType.COMMA,
                ";": TokenType.SEMI,
            }
            if ch in single_map:
                self.tokens.append(Token(single_map[ch], ch, self.line, self.col))
                self._advance()
                continue

            # Annotations (@isTest, @AuraEnabled) — skip
            if ch == "@":
                self._skip_annotation()
                continue

            # Unknown char — skip
            self._advance()

        self.tokens.append(Token(TokenType.EOF, "", self.line, self.col))
        return self.tokens

    def _advance(self, n=1):
        for _ in range(n):
            if self.pos < len(self.source):
                if self.source[self.pos] == "\n":
                    self.line += 1
                    self.col = 1
                else:
                    self.col += 1
                self.pos += 1

    def _peek(self, offset=0) -> str:
        p = self.pos + offset
        if p < len(self.source):
            return self.source[p]
        return "\0"

    def _skip_whitespace_and_comments(self):
        while self.pos < len(self.source):
            ch = self.source[self.pos]

            # Whitespace
            if ch in " \t\r\n":
                self._advance()
                continue

            # Single-line comment
            if ch == "/" and self._peek(1) == "/":
                while self.pos < len(self.source) and self.source[self.pos] != "\n":
                    self._advance()
                continue

            # Multi-line comment
            if ch == "/" and self._peek(1) == "*":
                self._advance(2)
                while self.pos < len(self.source):
                    if self.source[self.pos] == "*" and self._peek(1) == "/":
                        self._advance(2)
                        break
                    self._advance()
                continue

            break

    def _read_string(self) -> Token:
        """Lit une string literal avec support des séquences d'échappement Apex."""
        start_line, start_col = self.line, self.col
        self._advance()  # skip opening '
        value = ""
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch == "\\" and self.pos + 1 < len(self.source):
                next_ch = self.source[self.pos + 1]
                if next_ch == "'":
                    value += "'"
                    self._advance(2)
                    continue
                elif next_ch == "\\":
                    value += "\\"
                    self._advance(2)
                    continue
                elif next_ch == "n":
                    value += "\n"
                    self._advance(2)
                    continue
                elif next_ch == "t":
                    value += "\t"
                    self._advance(2)
                    continue
            if ch == "'":
                self._advance()  # skip closing '
                return Token(TokenType.STRING, value, start_line, start_col)
            value += ch
            self._advance()
        raise LexerError("Unterminated string", start_line, start_col)

    def _read_number(self) -> Token:
        start = self.pos
        start_line, start_col = self.line, self.col
        while self.pos < len(self.source) and (self.source[self.pos].isdigit() or self.source[self.pos] == "."):
            self._advance()
        value = self.source[start:self.pos]
        if "." in value:
            return Token(TokenType.DECIMAL, value, start_line, start_col)
        return Token(TokenType.INTEGER, value, start_line, start_col)

    def _read_ident(self) -> Token:
        start = self.pos
        start_line, start_col = self.line, self.col
        while self.pos < len(self.source) and (self.source[self.pos].isalnum() or self.source[self.pos] == "_"):
            self._advance()
        value = self.source[start:self.pos]
        ttype = KEYWORDS.get(value, TokenType.IDENT)
        return Token(ttype, value, start_line, start_col)

    def _read_soql(self) -> Token:
        """Lit un SOQL inline [SELECT ...]."""
        start_line, start_col = self.line, self.col
        start = self.pos
        depth = 0
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    self._advance()
                    return Token(TokenType.SOQL, self.source[start:self.pos], start_line, start_col)
            self._advance()
        raise LexerError("Unterminated SOQL", start_line, start_col)

    def _skip_annotation(self):
        """Skip @isTest, @AuraEnabled(cacheable=true), etc."""
        self._advance()  # skip @
        # Read annotation name
        while self.pos < len(self.source) and (self.source[self.pos].isalnum() or self.source[self.pos] == "_"):
            self._advance()
        # Skip optional (args)
        self._skip_whitespace_and_comments()
        if self.pos < len(self.source) and self.source[self.pos] == "(":
            depth = 0
            while self.pos < len(self.source):
                if self.source[self.pos] == "(":
                    depth += 1
                elif self.source[self.pos] == ")":
                    depth -= 1
                    if depth == 0:
                        self._advance()
                        break
                self._advance()
