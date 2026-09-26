"""Isolated regression tests; never modify the real news directory."""

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import render_news_index as renderer


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.news = self.root / 'news'
        self.news.mkdir()
        self.data = json.loads((renderer.ROOT / 'news/articles_index.json').read_text(encoding='utf-8'))
        for article in self.data['articles']:
            (self.news / article['file']).write_text('<html></html>', encoding='utf-8')
        self.target = self.news / 'index.html'
        self.target.write_bytes(b'original index must survive errors')
        self.save()

    def save(self):
        (self.news / 'articles_index.json').write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')

    def run_render(self, check=False):
        with redirect_stdout(io.StringIO()):
            return renderer.run(self.root, check)

    def snapshot(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.news.iterdir()}

    def test_check_does_not_write_and_generation_is_repeatable(self):
        before = self.snapshot()
        self.assertEqual(self.run_render(True), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_render(), 0)
        generated = self.snapshot()
        self.assertEqual(self.run_render(True), 0)
        self.assertEqual(self.run_render(), 0)
        self.assertEqual(self.snapshot(), generated)
        self.assertEqual(self.target.read_bytes().count(b'data-article-id='), 1)

    def test_invalid_inputs_keep_original(self):
        baseline = deepcopy(self.data)
        cases = ('broken', 'missing', 'missing_file', 'duplicate_id', 'duplicate_url',
                 'bad_date', 'impossible_date', 'bad_status', 'unsafe_url', 'duplicate_key')
        for case in cases:
            with self.subTest(case=case):
                self.data = deepcopy(baseline)
                a = self.data['articles'][0]
                if case == 'missing': del a['title']
                if case == 'missing_file':
                    a['id'] = a['slug'] = 'missing'
                    a['file'] = '2026-09-26-missing.html'
                if case == 'duplicate_id': self.data['articles'].append(deepcopy(a))
                if case == 'duplicate_url':
                    other = deepcopy(a)
                    other['id'] = other['slug'] = 'other'
                    self.data['articles'].append(other)
                if case == 'bad_date': a['published_date'] = '2026-9-26'
                if case == 'impossible_date': a['published_date'] = '2026-02-30'
                if case == 'bad_status': a['status'] = 'typo'
                if case == 'unsafe_url': a['file'] = '../index.html'
                self.save()
                if case == 'broken': (self.news / 'articles_index.json').write_text('{', encoding='utf-8')
                if case == 'duplicate_key':
                    p = self.news / 'articles_index.json'
                    p.write_text(p.read_text(encoding='utf-8').replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'), encoding='utf-8')
                before = self.snapshot()
                for check in (True, False):
                    with self.assertRaises((ValueError, KeyError)):
                        self.run_render(check)
                    self.assertEqual(self.snapshot(), before)

    def test_filter_sort_escape_and_empty(self):
        original = deepcopy(self.data['articles'][0])
        self.data['articles'] = []
        for aid, status, day in [('z', 'release', '2026-09-26'), ('a', 'release', '2026-09-26'),
                                 ('old', 'release', '2026-09-25'), ('draft', 'draft', '2026-09-26'),
                                 ('ready', 'ready', '2026-09-26')]:
            a = deepcopy(original)
            a.update(id=aid, slug=aid, status=status, published_date=day, file=f'{day}-{aid}.html')
            a['title'] = a['summary'] = a['category']['label'] = '<script>"&\'</script>'
            (self.news / a['file']).write_text('article', encoding='utf-8')
            self.data['articles'].append(a)
        self.save()
        self.run_render()
        doc = renderer.Document(self.target)
        self.assertEqual([n['attrs']['data-article-id'] for n in doc.nodes if 'data-article-id' in n['attrs']], ['a', 'z', 'old'])
        self.assertFalse(doc.select('script'))
        self.assertIn('&lt;script&gt;&quot;&amp;&#x27;', self.target.read_text(encoding='utf-8'))
        self.data['articles'] = []
        self.save()
        self.run_render()
        self.assertNotIn(b'data-article-id=', self.target.read_bytes())

    def test_validation_or_replace_failure_keeps_original_and_cleans_temp(self):
        for target, exception in [('validate_generated', ValueError('invalid generated HTML')),
                                  ('os.replace', PermissionError('file locked'))]:
            with self.subTest(target=target):
                before = self.snapshot()
                with patch('render_news_index.' + target, side_effect=exception):
                    with self.assertRaises(type(exception)):
                        self.run_render()
                self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
