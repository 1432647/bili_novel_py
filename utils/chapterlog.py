import re
from typing import Optional
from bs4 import BeautifulSoup

from utils.http_utils import get_http


DEFAULT_FIXED_LENGTH = 20
DEFAULT_SEED_MULTIPLIER = 135
DEFAULT_SEED_OFFSET = 234
DEFAULT_A = 9302
DEFAULT_C = 49397
DEFAULT_MOD = 233280


class ShuffleParams:
    def __init__(self, fixed_length: int, seed: int, a: int, c: int, mod: int):
        self.fixed_length = fixed_length
        self.seed = seed
        self.a = a
        self.c = c
        self.mod = mod


def _eval_js_expr(expr: str) -> Optional[int]:
    """Evaluate a simple JavaScript integer expression (+, -, *, /, %, <<, >>, ^)."""
    expr = expr.strip()
    if not expr:
        return None

    parser = _ExprParser(expr)
    try:
        return parser.parse()
    except (ValueError, IndexError):
        return None


class _ExprParser:
    def __init__(self, source: str):
        self._source = source
        self._idx = 0

    def parse(self) -> int:
        val = self._parse_xor()
        self._skip_ws()
        if self._idx != len(self._source):
            raise ValueError("trailing chars")
        return val

    def _parse_xor(self) -> int:
        val = self._parse_shift()
        while True:
            self._skip_ws()
            if not self._match('^'):
                return val
            val ^= self._parse_shift()

    def _parse_shift(self) -> int:
        val = self._parse_add_sub()
        while True:
            self._skip_ws()
            if self._match('<<'):
                val <<= self._parse_add_sub()
            elif self._match('>>>'):
                val >>= self._parse_add_sub()
            elif self._match('>>'):
                val >>= self._parse_add_sub()
            else:
                return val

    def _parse_add_sub(self) -> int:
        val = self._parse_mul_div()
        while True:
            self._skip_ws()
            if self._match('+'):
                val += self._parse_mul_div()
            elif self._match('-'):
                val -= self._parse_mul_div()
            else:
                return val

    def _parse_mul_div(self) -> int:
        val = self._parse_unary()
        while True:
            self._skip_ws()
            if self._match('*'):
                val *= self._parse_unary()
            elif self._match('/'):
                val //= self._parse_unary()
            elif self._match('%'):
                val %= self._parse_unary()
            else:
                return val

    def _parse_unary(self) -> int:
        self._skip_ws()
        if self._match('+'):
            return self._parse_unary()
        if self._match('-'):
            return -self._parse_unary()
        if self._match('~'):
            return ~self._parse_unary()
        return self._parse_primary()

    def _parse_primary(self) -> int:
        self._skip_ws()
        if self._match('('):
            val = self._parse_xor()
            self._skip_ws()
            if not self._match(')'):
                raise ValueError("missing )")
            return val
        return self._parse_number()

    def _parse_number(self) -> int:
        self._skip_ws()
        start = self._idx
        while self._idx < len(self._source) and self._source[self._idx] in '0123456789':
            self._idx += 1
        if start == self._idx:
            raise ValueError("expected number")
        return int(self._source[start:self._idx])

    def _match(self, s: str) -> bool:
        if self._source.startswith(s, self._idx):
            self._idx += len(s)
            return True
        return False

    def _skip_ws(self):
        while self._idx < len(self._source) and self._source[self._idx] in ' \t\n\r':
            self._idx += 1


def _strip_outer_parens(expr: str) -> str:
    val = expr.strip()
    while val.startswith('(') and val.endswith(')'):
        depth = 0
        wraps = True
        for i, ch in enumerate(val):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0 and i != len(val) - 1:
                    wraps = False
                    break
        if not wraps:
            return val
        val = val[1:-1].strip()
    return val


def _split_top_level(expr: str, op: str) -> list[str]:
    parts = []
    start = 0
    depth = 0
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif depth == 0 and expr.startswith(op, i):
            parts.append(expr[start:i].strip())
            start = i + len(op)
            i += len(op) - 1
        i += 1
    parts.append(expr[start:].strip())
    return parts


def _eval_with_vars(expr: str, variables: dict) -> Optional[int]:
    for key, val in variables.items():
        expr = re.sub(r'\b' + re.escape(key) + r'\b', str(val), expr)
    return _eval_js_expr(expr)


class ChapterLogResolver:
    def __init__(self, domain: str = "https://www.linovelib.com"):
        self._domain = domain
        self._cache: dict[str, Optional[ShuffleParams]] = {}

    def get_shuffle_params(self, soup: BeautifulSoup, chapter_id: int) -> Optional[ShuffleParams]:
        scripts = soup.find_all("script", src=re.compile(r"chapterlog\.js\?v"))
        if not scripts:
            return None

        js_src = scripts[0]["src"]
        js_url = js_src if js_src.startswith("http") else self._domain + js_src

        cache_key = js_src.split("?v")[0] if "?v" in js_src else js_src
        if cache_key in self._cache:
            template = self._cache[cache_key]
        else:
            template = self._load_template(js_url)
            self._cache[cache_key] = template

        if template is None:
            return None

        seed = chapter_id * DEFAULT_SEED_MULTIPLIER + DEFAULT_SEED_OFFSET
        return ShuffleParams(
            fixed_length=template.fixed_length if template else DEFAULT_FIXED_LENGTH,
            seed=seed,
            a=template.a if template else DEFAULT_A,
            c=template.c if template else DEFAULT_C,
            mod=template.mod if template else DEFAULT_MOD,
        )

    def _load_template(self, js_url: str) -> Optional[ShuffleParams]:
        try:
            http = get_http()
            js = http.get_js(js_url)
            return _parse_chapterlog(js)
        except Exception as e:
            print(f"  [warn] failed to load chapterlog.js: {e}")
            return None


def _parse_chapterlog(js: str) -> Optional[ShuffleParams]:
    template = _try_parse_plain(js)
    if template:
        return template
    return _try_parse_obfuscated(js)


def _try_parse_plain(js: str) -> Optional[ShuffleParams]:
    m = re.search(r'if\s*\(\s*[_$a-zA-Z0-9]+\s*>\s*((?:\(.*\)|\d+))', js)
    if not m:
        return None
    fixed_expr = m.group(1)
    fixed = _eval_js_expr(_strip_outer_parens(fixed_expr))
    if fixed is None:
        return None

    m = re.search(r'=\s*(.+?Number\s*\(\s*chapterId\s*\).+?)\s*;', js)
    if not m:
        return None
    seed_expr = m.group(1)
    offset = _eval_with_vars(seed_expr, {"chapterId": 0})
    one_val = _eval_with_vars(seed_expr, {"chapterId": 1})
    if offset is None or one_val is None:
        return None
    multiplier = one_val - offset

    m = re.search(r'=\s*(\(\s*[_$a-zA-Z0-9]+\s*\*.+?\)\s*%\s*.+?)\s*;', js)
    if not m:
        return None
    lcg_expr = m.group(1)
    parts = _split_top_level(lcg_expr, '%')
    if len(parts) != 2:
        return None
    mod = _eval_js_expr(parts[1])
    if mod is None:
        return None

    left = _strip_outer_parens(parts[0])
    var_match = re.match(r'[_$a-zA-Z][_$a-zA-Z0-9]*', left)
    if not var_match:
        return None
    varname = var_match.group(0)
    c_val = _eval_with_vars(left, {varname: 0})
    one2 = _eval_with_vars(left, {varname: 1})
    if c_val is None or one2 is None:
        return None
    a_val = one2 - c_val

    return ShuffleParams(
        fixed_length=fixed,
        seed=0,
        a=a_val,
        c=c_val,
        mod=mod,
    )


def _try_parse_obfuscated(js: str) -> Optional[ShuffleParams]:
    m = re.search(
        r'var\s+[_$a-zA-Z0-9]+\s*=\s*(.+?)\s*\(\s*[_$a-zA-Z0-9]+\s*\)\s*,'
        r'\s*(.+?)\s*\)\s*,\s*(.+?)\s*\)\s*,',
        js
    )
    if not m:
        return None

    multiplier = _eval_js_expr(m.group(2))
    offset = _eval_js_expr(m.group(3))
    if multiplier is None or offset is None:
        return None

    m2 = re.search(
        r'([_$a-zA-Z0-9]+)\s*=\s*(.+?)\s*\(\s*\1\s*,\s*(.+?)\s*\)\s*,\s*'
        r'(.+?)\s*\)\s*,\s*(.+?)\s*\)\s*;',
        js
    )
    if not m2:
        return None

    a_val = _eval_js_expr(m2.group(3))
    c_val = _eval_js_expr(m2.group(4))
    mod = _eval_js_expr(m2.group(5))
    if a_val is None or c_val is None or mod is None:
        return None

    return ShuffleParams(
        fixed_length=DEFAULT_FIXED_LENGTH,
        seed=0,
        a=a_val,
        c=c_val,
        mod=mod,
    )


def reverse_shuffle(paragraphs: list, params: ShuffleParams) -> list:
    """Reverse the Fisher-Yates shuffle applied by chapterlog.js.

    Matches the Dart implementation: apply forward Fisher-Yates to the
    index array, then use the permuted indices to map paragraphs back
    to their original positions via mapped[indices[i]] = paragraphs[i].
    """
    if len(paragraphs) <= params.fixed_length:
        return paragraphs

    n_paragraphs = len(paragraphs)
    fixed = list(range(params.fixed_length))
    shuffled = list(range(params.fixed_length, n_paragraphs))

    seed = params.seed
    n_shuffled = len(shuffled)
    for i in range(n_shuffled - 1, 0, -1):
        seed = (seed * params.a + params.c) % params.mod
        j = int((seed / params.mod) * (i + 1))
        shuffled[i], shuffled[j] = shuffled[j], shuffled[i]

    indices = fixed + shuffled

    mapped = [None] * n_paragraphs
    for i in range(n_paragraphs):
        mapped[indices[i]] = paragraphs[i]

    return mapped
