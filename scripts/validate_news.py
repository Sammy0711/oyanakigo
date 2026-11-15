"""Read-only structural checks; source accuracy still requires editorial review."""

import argparse
from datetime import date
from difflib import SequenceMatcher
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


VOID = set('area base br col embed hr img input link meta param source track wbr'.split())


class Document(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.raw = path.read_bytes()
        self.nodes, self.stack, self.ids, self.links = [], [], {}, []
        self.feed(self.raw.decode('utf-8'))
        self.close()
        require(not self.stack, f'{path.name}: unclosed HTML tags')

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        node = {'tag': tag, 'attrs': attrs, 'text': '', 'links': [], 'dates': []}
        self.nodes.append(node)
        if tag == 'time':
            for parent in self.stack:
                parent['dates'].append(attrs.get('datetime'))
        if 'id' in attrs:
            require(attrs['id'] not in self.ids, f'{self.path.name}: duplicate HTML id')
            self.ids[attrs['id']] = node
        for key in ('href', 'src'):
            if key in attrs:
                self.links.append(attrs[key])
                for parent in self.stack:
                    parent['links'].append(attrs[key])
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        require(bool(self.stack) and self.stack[-1]['tag'] == tag,
                f'{self.path.name}: mismatched end tag {tag}')
        self.stack.pop()

    def handle_data(self, data):
        for node in self.stack:
            node['text'] += data

    def select(self, tag):
        return [node for node in self.nodes if node['tag'] == tag]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def valid_date(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value),
            f'invalid date: {value}')
    result = date.fromisoformat(value)
    require(result <= date.today(), f'future date requires review: {value}')
    return result


# 読者に「確認できなかった」「自分で調べて」と伝える表現の禁止（2026-11-15 依頼主の指示）。
# この日以降に更新（updated_date）した記事は、本文（出典一覧を除く）にこれらの表現があると不合格。
# 確認できない事項は、一次情報を取り直して確認するか、記事から外す。古い記事は更新時に直す。
BANNED_WORDING_SINCE = date(2026, 11, 15)
BANNED_WORDING = [
    (r'未確認', '「未確認」'),
    (r'確認できて(い)?ません|確認できませんでした|確認できなかった', '「確認できていません」等'),
    (r'読み取れ(ませ|なかっ|ず)', '「読み取れなかった」等'),
    (r'(発表|公表|原文|最新情報|最新の情報|ホームページ|ウェブサイト|資料|通知|告示)で(ご)?確認(ください|して|を)', '読者に一次情報の確認を求める表現'),
    (r'(公表|発表|決定)を待つ|待つ必要', '「今後の公表を待つ」等'),
    (r'記載(が|は)ありません|記載していません|記載されていません|記載はありません', '「記載がありません／記載していません」'),
    (r'わかりません|分かりません|不明です', '「分かりません／不明です」'),
]


def banned_wording(raw_html):
    """出典一覧を除いた記事本文から、禁止表現を (表示名, 前後の文) のリストで返す。"""
    text = re.sub(r'(?s)<section class="sources">.*?</section>', '', raw_html)
    text = re.sub(r'(?s)<(script|style|head)\b.*?</\1>', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    found = []
    for pattern, label in BANNED_WORDING:
        for match in re.finditer(pattern, text):
            found.append((label, text[max(0, match.start() - 25):match.end() + 15].replace('\n', ' ')))
    return found


def validate(root):
    root = root.resolve()
    news = root / 'news'
    data = json.loads((news / 'articles_index.json').read_text(encoding='utf-8'))
    require(data['schema_version'] == 1 and data['language'] == 'ja', 'unsupported schema')
    articles = data['articles']
    require(isinstance(articles, list) and articles, 'no reviewed articles')
    docs = {path.resolve(): Document(path) for path in sorted(news.glob('*.html'))}
    listing = docs[(news / 'index.html').resolve()]
    cards = [node for node in listing.nodes if 'data-article-id' in node['attrs']]
    expected = sorted((a for a in articles if a['status'] == 'release'), key=lambda a: (-date.fromisoformat(a['published_date']).toordinal(), a['id']))
    require([node['attrs']['data-article-id'] for node in cards] == [a['id'] for a in expected],
            'index article membership/order mismatch')
    for key in ('id', 'slug', 'file', 'title'):
        values = [a[key] for a in articles]
        require(len(values) == len(set(values)), f'duplicate {key}')
    require({p.name for p in docs} == {'index.html'} | {a['file'] for a in articles},
            'unlisted or missing article HTML')
    bodies = []
    for article in articles:
        aid = article['id']
        require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', aid), 'invalid article id')
        require(article['slug'] == aid, f'{aid}: slug mismatch')
        require(re.fullmatch(r'\d{4}-\d{2}-\d{2}-' + re.escape(aid) + r'\.html', article['file']),
                f'{aid}: invalid filename')
        require(article['status'] in ('ready', 'release'), f'{aid}: not ready for publication')
        published = valid_date(article['published_date'])
        updated = valid_date(article['updated_date'])
        verified = valid_date(article['verified_date'])
        require(published <= updated <= verified, f'{aid}: edit after source review')
        review = article['review']
        require(valid_date(review['reviewed_on']) == verified, f'{aid}: review date mismatch')
        require(review['reviewer'].strip(), f'{aid}: missing reviewer')
        gates = review['gates']
        require(sorted(g['id'] for g in gates) == list(range(1, 11)), f'{aid}: missing/duplicate gates')
        require(all(g['result'] == 'pass' and g['evidence'].strip() for g in gates),
                f'{aid}: failed or undocumented editorial gate')
        doc = docs[(news / article['file']).resolve()]
        require(sha256(doc.raw.replace(b'\r\n', b'\n')).hexdigest() == review['article_sha256'],
                f'{aid}: HTML changed since review')
        if updated >= BANNED_WORDING_SINCE:
            hits = banned_wording(doc.raw.decode('utf-8'))
            require(not hits, f'{aid}: 読者に確認を委ねる表現が残っています（一次情報で確認して書き直すか、記述を外す）: '
                    + ' / '.join(f'{label}「…{context}…」' for label, context in hits[:5]))
        require(len(doc.select('h1')) == 1 and doc.select('h1')[0]['text'] == article['title'],
                f'{aid}: title mismatch')
        require(any(node['attrs'].get('class') == 'category' and node['text'] == article['category']['label']
                    for node in doc.nodes), f'{aid}: category mismatch')
        for label, key in (('published', 'published_date'), ('verified', 'verified_date')):
            times = [n for n in doc.select('time') if n['attrs'].get('data-date') == label]
            require(len(times) == 1 and times[0]['attrs'].get('datetime') == article[key],
                    f'{aid}: {label} date mismatch')
        if article['status'] == 'release':
            card = next(n for n in cards if n['attrs']['data-article-id'] == aid)
            require(article['file'] in card['links'] and article['title'] in card['text']
                    and article['summary'] in card['text'] and article['category']['label'] in card['text'],
                    f'{aid}: index card mismatch')
            require(card['dates'] == [article['published_date']], f'{aid}: index date mismatch')
        require(all(link in doc.links for link in ('index.html', '../index.html', '../index.html#contact')),
                f'{aid}: missing navigation/contact')
        sources = article['sources']
        require(sources and len({s['id'] for s in sources}) == len(sources), f'{aid}: missing/duplicate sources')
        source_ids = {s['id'] for s in sources}
        require(any(s['type'] == 'primary' for s in sources), f'{aid}: no primary source')
        for source in sources:
            require(source['type'] in ('primary', 'secondary'), f'{aid}: invalid source type')
            require(urlsplit(source['url']).scheme == 'https', f'{aid}: invalid source URL')
            require(valid_date(source['checked_on']) == verified, f'{aid}: source not rechecked')
            for key in ('publisher', 'title', 'locator', 'verification', 'date_kind'):
                require(source[key].strip(), f'{aid}: missing source {key}')
            precision, value = source['date_precision'], source['document_date']
            if precision == 'day':
                require(valid_date(value) <= verified, f'{aid}: source date after verification')
            elif precision == 'month':
                require(re.fullmatch(r'\d{4}-\d{2}', value), f'{aid}: invalid source month')
                require(valid_date(value + '-01') <= verified, f'{aid}: future edition')
            else:
                require(precision == 'unknown' and value is None, f'{aid}: unknown date must be null')
            anchor = doc.ids.get('source-' + source['id'])
            require(anchor and source['url'] in anchor['links'], f'{aid}: source link mismatch')
        claims = article['claims']
        require(claims and len({c['id'] for c in claims}) == len(claims), f'{aid}: missing/duplicate claims')
        used = set()
        for claim in claims:
            require(claim['statement'].strip() and claim['source_ids'], f'{aid}: unsupported claim')
            require(set(claim['source_ids']) <= source_ids, f'{aid}: unknown claim source')
            node = doc.ids.get(claim['id'])
            require(node is not None, f'{aid}: claim absent from HTML')
            require(all('#source-' + sid in node['links'] for sid in claim['source_ids']),
                    f'{aid}: citation not adjacent to claim')
            used.update(claim['source_ids'])
        require(used == source_ids, f'{aid}: unrelated unused source')
        require(article['editorial_proposals'].strip(), f'{aid}: label editorial proposals')
        body = re.sub(r'\s+', '', doc.select('article')[0]['text'])
        for other_id, other_body in bodies:
            require(SequenceMatcher(None, body, other_body, autojunk=False).ratio() < .9,
                    f'{aid}: substantially duplicated text with {other_id}; review manually')
        bodies.append((aid, body))
    # Check local files and fragments, including links to the unchanged site.
    for doc in list(docs.values()):
        require(len(doc.select('h1')) == 1 and len(doc.select('main')) == 1, f'{doc.path.name}: landmarks')
        require(any(n['attrs'].get('name') == 'description' and n['attrs'].get('content')
                    for n in doc.select('meta')), f'{doc.path.name}: missing description')
        for link in doc.links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = ((root / unquote(parsed.path).lstrip('/')) if parsed.path.startswith('/')
                      else (doc.path.parent / unquote(parsed.path)) if parsed.path else doc.path).resolve()
            require(target.is_relative_to(root) and target.is_file(), f'broken local link: {link}')
            if parsed.fragment:
                if target not in docs:
                    docs[target] = Document(target)
                require(unquote(parsed.fragment) in docs[target].ids, f'broken fragment: {link}')
    print(f'PASS: {len(articles)} article(s); metadata, 10 review records, hashes, citations, HTML and local links.')
    print('Source accuracy, legal interpretation and semantic originality require editorial review; no files changed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        validate(args.root)
    except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        sys.exit(1)
