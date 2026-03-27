"""Token-based expression parser — remplace le parsing regex des expressions."""

from __future__ import annotations

from .lexer import Token, TokenType, LexerError
from .ast_nodes import (
    Expr, StringLiteral, IntegerLiteral, BooleanLiteral, NullLiteral,
    Variable, FieldAccess, BinaryOp, UnaryOp, NewSObject,
    MethodCall, ChainedCall, Ternary, NewList, NewMap, NewSet, NewMapInit,
)


class TokenStream:
    """Flux de tokens avec peek/advance."""

    def __init__(self, tokens: list):
        self.tokens = tokens
        self.pos = 0

    def peek(self, offset=0) -> Token:
        p = self.pos + offset
        if p < len(self.tokens):
            return self.tokens[p]
        return Token(TokenType.EOF, "")

    def current(self) -> Token:
        return self.peek(0)

    def advance(self) -> Token:
        tok = self.current()
        self.pos += 1
        return tok

    def expect(self, ttype: TokenType) -> Token:
        tok = self.advance()
        if tok.type != ttype:
            raise Exception("Expected {}, got {} ('{}')".format(ttype.name, tok.type.name, tok.value))
        return tok

    def match(self, ttype: TokenType) -> bool:
        if self.current().type == ttype:
            self.advance()
            return True
        return False

    def at(self, ttype: TokenType) -> bool:
        return self.current().type == ttype

    def at_any(self, *ttypes) -> bool:
        return self.current().type in ttypes


# Operator precedence (higher = tighter binding)
PRECEDENCE = {
    TokenType.OR: 1,
    TokenType.AND: 2,
    TokenType.EQ: 3,
    TokenType.NEQ: 3,
    TokenType.LT: 4,
    TokenType.GT: 4,
    TokenType.LTE: 4,
    TokenType.GTE: 4,
    TokenType.PLUS: 5,
    TokenType.MINUS: 5,
    TokenType.STAR: 6,
    TokenType.SLASH: 6,
    TokenType.INSTANCEOF: 3,
}

OP_MAP = {
    TokenType.PLUS: "+",
    TokenType.MINUS: "-",
    TokenType.STAR: "*",
    TokenType.SLASH: "/",
    TokenType.EQ: "==",
    TokenType.NEQ: "!=",
    TokenType.LT: "<",
    TokenType.GT: ">",
    TokenType.LTE: "<=",
    TokenType.GTE: ">=",
    TokenType.AND: "&&",
    TokenType.OR: "||",
    TokenType.INSTANCEOF: "instanceof",
}


def parse_expression(stream: TokenStream) -> Expr:
    """Parse une expression complète avec priorité d'opérateurs."""
    expr = _parse_ternary(stream)
    # Null coalescing: expr ?? default
    if stream.match(TokenType.NULLCOAL):
        default = _parse_ternary(stream)
        return Ternary(
            condition=BinaryOp(left=expr, op="!=", right=NullLiteral()),
            then_expr=expr,
            else_expr=default,
        )
    return expr


def _parse_ternary(stream: TokenStream) -> Expr:
    """Parse ternaire: expr ? then : else"""
    expr = _parse_binary(stream, 0)
    if stream.match(TokenType.QUESTION):
        then_expr = parse_expression(stream)
        stream.expect(TokenType.COLON)
        else_expr = parse_expression(stream)
        return Ternary(condition=expr, then_expr=then_expr, else_expr=else_expr)
    return expr


def _parse_binary(stream: TokenStream, min_prec: int) -> Expr:
    """Precedence climbing pour les opérateurs binaires."""
    left = _parse_unary(stream)

    while True:
        tok = stream.current()
        if tok.type not in PRECEDENCE:
            break
        prec = PRECEDENCE[tok.type]
        if prec < min_prec:
            break
        stream.advance()
        right = _parse_binary(stream, prec + 1)
        left = BinaryOp(left=left, op=OP_MAP[tok.type], right=right)

    return left


def _parse_unary(stream: TokenStream) -> Expr:
    """Parse unaire: !expr, -expr"""
    if stream.match(TokenType.NOT):
        operand = _parse_unary(stream)
        return UnaryOp(op="!", operand=operand)
    if stream.current().type == TokenType.MINUS:
        stream.advance()
        operand = _parse_unary(stream)
        return BinaryOp(left=IntegerLiteral(value=0), op="-", right=operand)
    return _parse_postfix(stream)


def _parse_postfix(stream: TokenStream) -> Expr:
    """Parse postfix: method calls, field access, chaînage."""
    expr = _parse_primary(stream)

    while True:
        if stream.match(TokenType.DOT):
            member = stream.expect(TokenType.IDENT).value
            if stream.match(TokenType.LPAREN):
                # Method call
                args = _parse_args(stream)
                if isinstance(expr, Variable):
                    expr = MethodCall(obj=expr.name, method=member, args=args)
                else:
                    expr = ChainedCall(target=expr, method=member, args=args)
            else:
                # Field access
                if isinstance(expr, Variable):
                    expr = FieldAccess(obj=expr.name, field=member)
                else:
                    expr = ChainedCall(target=expr, method=member, args=[])
        elif stream.match(TokenType.LBRACKET):
            # Array access: expr[index]
            index = parse_expression(stream)
            stream.expect(TokenType.RBRACKET)
            expr = MethodCall(obj="_indexer", method="get", args=[expr, index])
        else:
            break

    return expr


def _parse_primary(stream: TokenStream) -> Expr:
    """Parse expression primaire."""
    tok = stream.current()

    # Parenthèses
    if tok.type == TokenType.LPAREN:
        stream.advance()
        # Check for type cast: (Type) expr
        if stream.at(TokenType.IDENT) and stream.peek(1).type == TokenType.RPAREN:
            # Could be cast — for now treat as grouped expression
            pass
        expr = parse_expression(stream)
        stream.expect(TokenType.RPAREN)
        return expr

    # Literals
    if tok.type == TokenType.STRING:
        stream.advance()
        return StringLiteral(value=tok.value)
    if tok.type == TokenType.INTEGER:
        stream.advance()
        return IntegerLiteral(value=int(tok.value))
    if tok.type == TokenType.DECIMAL:
        stream.advance()
        return IntegerLiteral(value=float(tok.value))
    if tok.type == TokenType.TRUE:
        stream.advance()
        return BooleanLiteral(value=True)
    if tok.type == TokenType.FALSE:
        stream.advance()
        return BooleanLiteral(value=False)
    if tok.type == TokenType.NULL:
        stream.advance()
        return NullLiteral()

    # SOQL
    if tok.type == TokenType.SOQL:
        stream.advance()
        return StringLiteral(value=tok.value)  # Wrapped as string, handled by interpreter

    # new
    if tok.type == TokenType.NEW:
        return _parse_new(stream)

    # Identifier
    if tok.type == TokenType.IDENT:
        stream.advance()
        name = tok.value
        # Function call: name(args)
        if stream.match(TokenType.LPAREN):
            args = _parse_args(stream)
            return MethodCall(obj="_self", method=name, args=args)
        return Variable(name=name)

    raise Exception("Unexpected token: {} ('{}') at line {}".format(tok.type.name, tok.value, tok.line))


def _parse_new(stream: TokenStream) -> Expr:
    """Parse: new Type(...) / new List<T>() / new Map<K,V>() / new Set<T>()"""
    stream.expect(TokenType.NEW)  # consume 'new'
    type_name = stream.expect(TokenType.IDENT).value

    # List<T>, Set<T>, Map<K,V>
    if type_name in ("List", "Set", "Map") and stream.match(TokenType.LT):
        return _parse_new_collection(stream, type_name)

    # new SObject(field = val, ...) or new ClassName(args)
    if stream.match(TokenType.LPAREN):
        # Check if it's SObject constructor (field = value) or regular constructor
        if stream.at(TokenType.IDENT) and stream.peek(1).type == TokenType.ASSIGN:
            fields = _parse_constructor_fields(stream)
            return NewSObject(sobject_type=type_name, fields=fields)
        elif stream.at(TokenType.RPAREN):
            stream.advance()
            return NewSObject(sobject_type=type_name, fields={})
        else:
            # Regular constructor with args (exceptions etc.)
            args = _parse_args(stream)
            if args:
                return NewSObject(sobject_type=type_name, fields={"message": args[0]})
            return NewSObject(sobject_type=type_name, fields={})

    return NewSObject(sobject_type=type_name, fields={})


def _parse_new_collection(stream: TokenStream, collection_type: str) -> Expr:
    """Parse new List<T>(), new Set<T>{...}, new Map<K,V>()"""
    elem_type = stream.expect(TokenType.IDENT).value

    if collection_type == "Map":
        stream.expect(TokenType.COMMA)
        # Value type might be generic like List<String>
        val_type = stream.expect(TokenType.IDENT).value
        stream.expect(TokenType.GT)
        if stream.match(TokenType.LBRACE):
            # Map init: { 'key' => value, ... }
            return _parse_map_init(stream, elem_type, val_type)
        stream.expect(TokenType.LPAREN)
        stream.expect(TokenType.RPAREN)
        return NewMap(key_type=elem_type, value_type=val_type)

    # List or Set
    stream.expect(TokenType.GT)

    init_values = []
    if stream.match(TokenType.LBRACE):
        # {val1, val2, ...}
        if not stream.at(TokenType.RBRACE):
            init_values.append(parse_expression(stream))
            while stream.match(TokenType.COMMA):
                init_values.append(parse_expression(stream))
        stream.expect(TokenType.RBRACE)
    elif stream.match(TokenType.LPAREN):
        stream.expect(TokenType.RPAREN)

    if collection_type == "List":
        return NewList(element_type=elem_type, init_values=init_values)
    return NewSet(element_type=elem_type, init_values=init_values)


def _parse_constructor_fields(stream: TokenStream) -> dict:
    """Parse SObject constructor: Name = 'val', Active__c = true"""
    fields = {}
    while not stream.at(TokenType.RPAREN) and not stream.at(TokenType.EOF):
        name = stream.expect(TokenType.IDENT).value
        stream.expect(TokenType.ASSIGN)
        value = parse_expression(stream)
        fields[name] = value
        if not stream.match(TokenType.COMMA):
            break
    stream.expect(TokenType.RPAREN)
    return fields


def _parse_map_init(stream: TokenStream, key_type: str, val_type: str) -> NewMapInit:
    """Parse Map init: { 'key' => value, ... } — opening { already consumed."""
    entries = []
    if not stream.at(TokenType.RBRACE):
        key = parse_expression(stream)
        stream.expect(TokenType.ARROW)
        val = parse_expression(stream)
        entries.append((key, val))
        while stream.match(TokenType.COMMA):
            if stream.at(TokenType.RBRACE):
                break
            key = parse_expression(stream)
            stream.expect(TokenType.ARROW)
            val = parse_expression(stream)
            entries.append((key, val))
    stream.expect(TokenType.RBRACE)
    return NewMapInit(key_type=key_type, value_type=val_type, entries=entries)


def _parse_args(stream: TokenStream) -> list:
    """Parse liste d'arguments: expr, expr, ...) — la RPAREN est consommée."""
    args = []
    if not stream.at(TokenType.RPAREN):
        args.append(parse_expression(stream))
        while stream.match(TokenType.COMMA):
            args.append(parse_expression(stream))
    stream.expect(TokenType.RPAREN)
    return args
