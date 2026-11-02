import unittest
from site_paths import URLRewriter, relative_url


class SitePathsTest(unittest.TestCase):
    def test_cross_site_from_nested_page(self):
        self.assertEqual(relative_url('/sdk/testing/model-case/#inputs', 'demo/build/index.html', '/CUTE/'),
                         '../../sdk/testing/model-case/#inputs')

    def test_already_prefixed_asset(self):
        self.assertEqual(relative_url('/CUTE/assets/main.css', '404.html', '/CUTE/'), 'assets/main.css')

    def test_root_and_relative_urls(self):
        self.assertEqual(relative_url('/', 'sdk/index.html', '/CUTE/'), '../')
        for value in ['../config-architecture/#flow', '#flow', 'https://example.com/x', '//cdn.example.com/x', 'mailto:a@example.com']:
            self.assertEqual(relative_url(value, 'index.html', '/CUTE/'), value)

    def test_local_preview(self):
        self.assertEqual(relative_url('/design/', 'sdk/index.html', '/'), '../design/')

    def test_only_attributes_change(self):
        source = '''<p>/sdk/</p><pre>&lt;a href="/sdk/"&gt;</pre>
<script>const text = '<a href="/sdk/">';</script>
<math display="block"><mi>x</mi></math><a href='/sdk/?q=a&amp;b=2#x'>SDK</a>'''
        result = URLRewriter(source, 'demo/index.html', '/CUTE/').rewritten()
        self.assertEqual(result, source.replace("href='/sdk/?q=a&amp;b=2#x'", "href='../sdk/?q=a&amp;b=2#x'"))

    def test_idempotent(self):
        source = '<img src="/assets/demo.svg"/><a href="/">home</a>'
        first = URLRewriter(source, 'sdk/index.html', '/CUTE/').rewritten()
        self.assertEqual(first, URLRewriter(first, 'sdk/index.html', '/CUTE/').rewritten())

    def test_other_attributes_are_unchanged(self):
        source = '''<div data-href="/sdk/" title='example href="/sdk/"'><a HREF="/sdk/">SDK</a></div>'''
        expected = source.replace('HREF="/sdk/"', 'HREF="../sdk/"')
        self.assertEqual(URLRewriter(source, 'demo/index.html', '/CUTE/').rewritten(), expected)


if __name__ == '__main__':
    unittest.main()
