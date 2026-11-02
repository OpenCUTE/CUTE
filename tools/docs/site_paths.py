"""Make internal HTML links portable between / and a Pages project subpath.

Only URL attributes are changed; code blocks, mathematical markup and inline
scripts keep their original bytes. Markdown sources remain unchanged.
"""
import html
from html.parser import HTMLParser
import posixpath
import re
from urllib.parse import urlsplit, urlunsplit

ATTRIBUTE = re.compile(r'''([\w:-]+)(\s*=\s*)(["'])(.*?)\3''', re.S)


def relative_url(value, page, base_path):
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/'):
        return value
    path = parsed.path
    prefix = base_path.rstrip('/')
    if prefix and (path == prefix or path.startswith(prefix+'/')):
        path = path[len(prefix):] or '/'
    target = posixpath.normpath(path.lstrip('/') or '.')
    result = posixpath.relpath(target, posixpath.dirname(page) or '.')
    if path.endswith('/') and result != '.':
        result += '/'
    return urlunsplit(('', '', result, parsed.query, parsed.fragment))


class URLRewriter(HTMLParser):
    def __init__(self, source, page, base_path):
        super().__init__(convert_charrefs=False)
        self.source, self.page, self.base_path = source, page, base_path
        self.line_offsets = [0]
        for match in re.finditer('\n', source):
            self.line_offsets.append(match.end())
        self.changes = []

    def handle_starttag(self, tag, attrs):
        original = self.get_starttag_text()
        def replace(match):
            if match[1].lower() not in ('href', 'src', 'action', 'poster'):
                return match[0]
            value = html.unescape(match[4])
            rewritten = relative_url(value, self.page, self.base_path)
            if rewritten == value:
                return match[0]
            return match[1]+match[2]+match[3]+html.escape(rewritten, quote=True)+match[3]
        updated = ATTRIBUTE.sub(replace, original)
        if original != updated:
            line, column = self.getpos()
            offset = self.line_offsets[line-1]+column
            self.changes.append((offset, offset+len(original), updated))

    handle_startendtag = handle_starttag

    def rewritten(self):
        self.feed(self.source)
        self.close()
        result = self.source
        for start, end, updated in reversed(self.changes):
            result = result[:start]+updated+result[end:]
        return result


def localize_site(root, site_url):
    base_path = urlsplit(site_url).path
    changed = 0
    for path in sorted(root.rglob('*.html')):
        source = path.read_text(encoding='utf-8')
        result = URLRewriter(source, path.relative_to(root).as_posix(), base_path).rewritten()
        if result != source:
            path.write_text(result, encoding='utf-8')
            changed += 1
    return changed
