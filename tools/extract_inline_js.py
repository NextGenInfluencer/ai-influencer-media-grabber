"""Extract inline <script> blocks from Jinja templates so ESLint can check them.

Each template becomes ``<out>/<name>.inline.js``. Script lines keep their original line
numbers (everything else is blank), so ESLint reports point straight at the template.
Line 1 carries a ``/* global ... */`` comment listing the top-level names declared by the
page's own external scripts (``/static/*.js``, including ``{% include %}``-d templates),
because the inline code may call them.

Usage: python tools/extract_inline_js.py [--out build/inline-js] [templates ...]
"""
import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
JINJA_EXPRESSION = re.compile(r'\{\{.*?\}\}', re.S)
JINJA_STATEMENT = re.compile(r'\{%.*?%\}', re.S)
INCLUDE = re.compile(r"\{%\s*include\s+['\"]([^'\"]+)['\"]\s*%\}")
STATIC_SRC = re.compile(r"""(?:/static/|filename=['"])([\w./-]+\.js)""")
TOP_LEVEL_NAME = re.compile(
    r'^(?:(?:async\s+)?function\s*\*?\s*|(?:const|let|var|class)\s+|window\.)([A-Za-z_$][\w$]*)', re.M)
JS_TYPES = ('', 'text/javascript', 'application/javascript', 'module')


class _Scripts(HTMLParser):
    """Collect inline script bodies (with their starting line) and external script sources."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.inline, self.external = [], []
        self._current = None

    def handle_starttag(self, tag, attrs):
        if tag != 'script':
            return
        attributes = dict(attrs)
        if attributes.get('src'):
            self.external.append(attributes['src'])
        elif (attributes.get('type') or '').lower() in JS_TYPES:
            self._current = [self.getpos()[0], '']

    def handle_data(self, data):
        if self._current is not None:
            if not self._current[1]:
                # Body starts on the line of the opening tag (after the tag itself).
                self._current[0] = self.getpos()[0]
            self._current[1] += data

    def handle_endtag(self, tag):
        if tag == 'script' and self._current is not None:
            self.inline.append(tuple(self._current))
            self._current = None


def _external_sources(template, folder, seen=None):
    seen = seen if seen is not None else {template.name}
    text = template.read_text(encoding='utf-8')
    sources = STATIC_SRC.findall(' '.join(re.findall(r'<script[^>]*>', text)))
    for name in INCLUDE.findall(text):
        child = folder / name
        if name not in seen and child.is_file():
            seen.add(name)
            sources += _external_sources(child, folder, seen)
    return sources


def declared_globals(sources):
    names = set()
    for source in sources:
        path = ROOT / 'static' / source
        if path.is_file() and 'vendor/' not in source:
            names.update(TOP_LEVEL_NAME.findall(path.read_text(encoding='utf-8')))
    return sorted(names)


def extract(template, out_dir):
    """Write the inline scripts of ``template``; returns the output path or None when it has none."""
    raw = template.read_text(encoding='utf-8')
    # Neutralise Jinja so the HTML/JS stays parseable without changing line counts.
    text = JINJA_STATEMENT.sub(lambda m: '\n' * m.group(0).count('\n'), raw)
    text = JINJA_EXPRESSION.sub(lambda m: '0' + '\n' * m.group(0).count('\n'), text)
    parser = _Scripts()
    parser.feed(text)
    parser.close()
    if not parser.inline:
        return None
    lines = [''] * (text.count('\n') + 2)
    for start, body in parser.inline:
        for offset, line in enumerate(body.split('\n')):
            lines[start - 1 + offset] = line if offset else lines[start - 1] + line
    names = declared_globals(_external_sources(template, template.parent))
    if names:
        lines[0] = '/* global ' + ', '.join(names) + ' */'
    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / (template.stem + '.inline.js')
    destination.write_text('\n'.join(lines), encoding='utf-8')
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', default=str(ROOT / 'build' / 'inline-js'))
    parser.add_argument('templates', nargs='*')
    args = parser.parse_args(argv)
    templates = [Path(t) for t in args.templates] or sorted((ROOT / 'templates').glob('*.html'))
    out_dir = Path(args.out)
    for stale in out_dir.glob('*.inline.js'):
        stale.unlink()
    for template in templates:
        result = extract(template, out_dir)
        print(f'{template.name}: ' + (str(result) if result else 'no inline scripts'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
