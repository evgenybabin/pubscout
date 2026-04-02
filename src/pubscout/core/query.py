"""Boolean query parser, matcher, and arXiv translator for PubScout.

Parses boolean query strings (AND/OR with quoted phrases and parentheses) into an AST,
matches queries against publication text, and converts queries to arXiv API syntax.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------

class QueryNode(ABC):
    """Base class for all query AST nodes."""

    @abstractmethod
    def __eq__(self, other: object) -> bool: ...

    @abstractmethod
    def __repr__(self) -> str: ...


@dataclass(frozen=True)
class TermNode(QueryNode):
    """Leaf node — a single word or quoted phrase (stored lowercase)."""

    term: str

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TermNode) and self.term == other.term

    def __repr__(self) -> str:
        return f'TermNode({self.term!r})'

    def __hash__(self) -> int:
        return hash(self.term)


@dataclass
class AndNode(QueryNode):
    """All children must match."""

    children: list[QueryNode] = field(default_factory=list)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, AndNode) and self.children == other.children

    def __repr__(self) -> str:
        return f'AndNode({self.children!r})'


@dataclass
class OrNode(QueryNode):
    """Any child may match."""

    children: list[QueryNode] = field(default_factory=list)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, OrNode) and self.children == other.children

    def __repr__(self) -> str:
        return f'OrNode({self.children!r})'


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# Token types produced by the tokenizer.
_TOKEN_RE = re.compile(
    r"""
    (?P<LPAREN>\()
    | (?P<RPAREN>\))
    | (?P<QUOTED>"[^"]*")
    | (?P<WORD>[^\s()]+)
    """,
    re.VERBOSE,
)


def _tokenize(query: str) -> list[str]:
    """Split *query* into a flat list of tokens (parens, quoted strings, words)."""
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer(query):
        tok = m.group()
        tokens.append(tok)
    return tokens


# ---------------------------------------------------------------------------
# Recursive-descent parser
# ---------------------------------------------------------------------------
# Grammar (AND binds tighter than OR):
#   expr     -> and_expr (OR and_expr)*
#   and_expr -> atom (AND atom)*
#   atom     -> TERM | QUOTED | '(' expr ')'


class _Parser:
    """Recursive-descent parser that turns tokens into a QueryNode tree."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self._pos = 0

    # -- helpers -------------------------------------------------------------

    def _peek(self) -> str | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> str:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    # -- grammar rules -------------------------------------------------------

    def parse(self) -> QueryNode:
        node = self._expr()
        if not self._at_end():
            raise ValueError(f"Unexpected token at position {self._pos}: {self._peek()!r}")
        return node

    def _expr(self) -> QueryNode:
        """expr -> and_expr (OR and_expr)*"""
        children = [self._and_expr()]
        while self._peek() and self._peek().upper() == "OR":  # type: ignore[union-attr]
            self._advance()  # consume OR
            children.append(self._and_expr())
        return children[0] if len(children) == 1 else OrNode(children)

    def _and_expr(self) -> QueryNode:
        """and_expr -> atom (AND atom)*"""
        children = [self._atom()]
        while self._peek() and self._peek().upper() == "AND":  # type: ignore[union-attr]
            self._advance()  # consume AND
            children.append(self._atom())
        return children[0] if len(children) == 1 else AndNode(children)

    def _atom(self) -> QueryNode:
        """atom -> TERM | QUOTED | '(' expr ')'"""
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of query")

        if tok == "(":
            self._advance()  # consume '('
            node = self._expr()
            if self._peek() != ")":
                raise ValueError("Missing closing parenthesis")
            self._advance()  # consume ')'
            return node

        if tok.startswith('"') and tok.endswith('"'):
            self._advance()
            phrase = tok[1:-1].strip().lower()
            return TermNode(phrase)

        # bare word — must not be a keyword
        if tok.upper() in ("AND", "OR"):
            raise ValueError(f"Unexpected operator {tok!r}")
        self._advance()
        return TermNode(tok.lower())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_query(query_str: str) -> QueryNode:
    """Parse a boolean query string into an AST of :class:`QueryNode` objects.

    Supports AND, OR (case-insensitive), quoted phrases, parentheses, and bare
    terms.  AND binds tighter than OR; parentheses override precedence.
    """
    tokens = _tokenize(query_str)
    if not tokens:
        raise ValueError("Empty query")
    return _Parser(tokens).parse()


def matches(query: QueryNode, text: str) -> bool:
    """Return *True* if *text* satisfies the boolean *query* (case-insensitive)."""
    text_lower = text.lower()

    if isinstance(query, TermNode):
        return query.term in text_lower
    if isinstance(query, AndNode):
        return all(matches(child, text) for child in query.children)
    if isinstance(query, OrNode):
        return any(matches(child, text) for child in query.children)

    raise TypeError(f"Unknown node type: {type(query)}")  # pragma: no cover


def to_arxiv_query(query: QueryNode, categories: list[str] | None = None) -> str:
    """Translate a parsed query tree to arXiv API search syntax.

    Each term is expanded to ``ti:<term> OR abs:<term>``.  Multi-word phrases
    are quoted.  If *categories* are provided they are prepended as a
    ``(cat:X OR cat:Y ...)`` AND clause.
    """

    def _node_to_str(node: QueryNode) -> str:
        if isinstance(node, TermNode):
            # Multi-word phrase → quote it
            if " " in node.term:
                return f'(ti:"{node.term}" OR abs:"{node.term}")'
            return f"(ti:{node.term} OR abs:{node.term})"

        if isinstance(node, AndNode):
            parts = [_node_to_str(c) for c in node.children]
            return " AND ".join(parts)

        if isinstance(node, OrNode):
            parts = [_node_to_str(c) for c in node.children]
            return "(" + " OR ".join(parts) + ")"

        raise TypeError(f"Unknown node type: {type(node)}")  # pragma: no cover

    body = _node_to_str(query)

    if categories:
        cat_clause = "(" + " OR ".join(f"cat:{c}" for c in categories) + ")"
        return f"{cat_clause} AND {body}"

    return body
