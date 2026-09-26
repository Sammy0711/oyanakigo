"""Render the release news listing using only the Python standard library."""

import argparse
from datetime import date
from difflib import unified_diff
from html import escape
import json
import os
from pathlib import Path
import re
import sys
import tempfile

# Do not leave bytecode files when importing the read-only HTML parser.
sys.dont_write_bytecode = True
from validate_news import Document, require

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).with_name('news_index_template.html')
MARKER = '<!-- ARTICLE_CARDS -->'


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def text_field(obj, key):
    value = obj[key]
    require(isinstance(value, str) and value.strip(), f'missing/invalid {key}')
    require(not any(ord(c) < 32 for c in value), f'control character in {key}')
    return value


def load_articles(root):
    news = root / 'news'
    data = json.loads((news / 'articles_index.json').read_text(encoding='utf-8'),
                      object_pairs_hook=unique_keys)
    require(isinstance(data, dict) and type(data.get('schema_version')) is int
            and data['schema_version'] == 1 and data.get('language') == 'ja', 'unsupported schema')
    articles = data['articles']
    require(isinstance(articles, list), 'articles must be an array')
    ids, files = set(), set()
    for article in articles:
        require(isinstance(article, dict), 'article must be an object')
        aid = text_field(article, 'id')
        require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', aid), 'invalid article id')
        require(text_field(article, 'slug') == aid, f'{aid}: slug mismatch')
        require(aid not in ids, f'duplicate id: {aid}')
        ids.add(aid)
        require(article['status'] in ('draft', 'ready', 'release'), f'{aid}: invalid status')
        for key in ('published_date', 'updated_date', 'verified_date'):
            value = text_field(article, key)
            require(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value), f'{aid}: invalid {key}')
            date.fromisoformat(value)
        filename = text_field(article, 'file')
        require(filename.casefold() not in files, f'duplicate URL: {filename}')
        files.add(filename.casefold())
        require(filename == f"{article['published_date']}-{aid}.html", f'{aid}: invalid article URL')
        path = (news / filename).resolve()
        require(path.parent == news.resolve() and path.is_file(), f'{aid}: missing/unsafe article HTML')
        for key in ('title', 'summary'):
            text_field(article, key)
        require(isinstance(article['category'], dict), f'{aid}: invalid category')
        text_field(article['category'], 'id')
        text_field(article['category'], 'label')
    return sorted((a for a in articles if a['status'] == 'release'),
                  key=lambda a: (-date.fromisoformat(a['published_date']).toordinal(), a['id']))


def render(articles):
    template = TEMPLATE.read_text(encoding='utf-8')
    require(template.count(MARKER) == 1, 'template must contain one card marker')
    cards = []
    for a in articles:
        day = date.fromisoformat(a['published_date'])
        cards.append(f'''        <li data-article-id="{escape(a['id'], quote=True)}">
          <a href="{escape(a['file'], quote=True)}">
            <p class="meta"><time datetime="{escape(a['published_date'], quote=True)}">{day.year}年{day.month}月{day.day}日</time><span class="category">{escape(a['category']['label'], quote=True)}</span></p>
            <h2>{escape(a['title'], quote=True)}</h2>
            <p class="summary">{escape(a['summary'], quote=True)}</p>
            <span class="read">記事を読む →</span>
          </a>
        </li>''')
    return template.replace(MARKER, '\n'.join(cards)).encode('utf-8')


def validate_generated(path, articles):
    doc = Document(path)
    require(len(doc.select('main')) == 1 and len(doc.select('h1')) == 1, 'invalid page structure')
    require(all(link in doc.links for link in ('../index.html', '../index.html#contact')),
            'missing site navigation')
    cards = [n for n in doc.nodes if 'data-article-id' in n['attrs']]
    require([n['attrs']['data-article-id'] for n in cards] == [a['id'] for a in articles],
            'generated card membership/order mismatch')
    for card, article in zip(cards, articles):
        require(card['links'] == [article['file']] and card['dates'] == [article['published_date']],
                'generated card link/date mismatch')
        require(all(value in card['text'] for value in
                    (article['title'], article['summary'], article['category']['label'])),
                'generated card text mismatch')


def run(root, check=False):
    root = root.resolve()
    articles = load_articles(root)
    output = render(articles)
    target = root / 'news' / 'index.html'
    current = target.read_bytes() if target.exists() else b''
    changed = current != output
    if check:
        # Check mode creates no files, including temporary files.
        class MemoryHTML:
            name = 'planned news/index.html'

            def read_bytes(self):
                return output

        validate_generated(MemoryHTML(), articles)
        print(f"PASS: JSON, article files and generated HTML; {len(articles)} release article(s).")
        print('DIFF: ' + ('yes' if changed else 'no') + '; no files changed.')
        if changed:
            diff = ''.join(unified_diff(current.decode('utf-8').splitlines(True),
                                        output.decode('utf-8').splitlines(True),
                                        fromfile='current news/index.html', tofile='generated news/index.html'))
            print(diff or '(UTF-8/newline byte differences only)')
        return 1 if changed else 0
    temporary = None
    try:
        # Same-directory temporary file permits atomic replacement on the same volume.
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, prefix='.news-index-',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        validate_generated(temporary, articles)
        if changed:
            os.replace(temporary, target)
            temporary = None
        print(f"PASS: {len(articles)} release article(s); index {'updated' if changed else 'unchanged'}.")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='read-only check; exit 1 if out of date')
    parser.add_argument('--root', type=Path, default=ROOT, help='site root (also used for isolated tests)')
    args = parser.parse_args()
    try:
        sys.exit(run(args.root, args.check))
    except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        sys.exit(2)
