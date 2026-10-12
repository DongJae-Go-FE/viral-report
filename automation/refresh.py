#!/usr/bin/env python3
"""Public, unauthenticated view-count collector. Defaults to a read-only plan.

Only exact, article-local counters with validated markup are supported. No browser
profile, cookies, private endpoints, retries or access-control workarounds.
"""
import argparse
import collections
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
KASI = 'https://astro.kasi.re.kr/kor/life/post/almanac?search_year=2026'
MPM = ('https://www.mpm.go.kr/mpm/comm/newsPress/newsPressRelease/'
       '?mode=list&pageIdx=1&searchCondition=title&searchKeyword=%EA%B3%B5%ED%9C%B4%EC%9D%BC')
PATTERNS = {
    'www.fmkorea.com': r'<span>\s*조회\s*수\s*<b>\s*([\d,]+)\s*</b>\s*</span>',
    'mlbpark.donga.com': r'<span class=[\'"]tit[\'"]>조회</span>\s*<span class=[\'"]val[\'"]>\s*([\d,]+)\s*</span>',
    'm.bobaedream.co.kr': r'<span class="data4">조회\s*([\d,]+)</span>',
    'www.teamblind.com': r'<span class="pv"[^>]*><i class="blind"[^>]*>조회수</i>\s*([\d,]+)</span>',
}
BLOCKS = re.compile(r'^  \{\n.*?^  \},', re.M | re.S)
TBODY = re.compile(r'(<tbody\b[^>]*>)(.*?)(</tbody>)', re.S)
ROW = re.compile(r'<tr\b[^>]*>.*?</tr>', re.S)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def get_page(url, json_response=False):
    """Only HTTPS, same-host redirects; never send authentication."""
    host = urllib.parse.urlsplit(url).hostname
    if urllib.parse.urlsplit(url).scheme != 'https':
        raise ValueError('HTTPS required')

    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target = urllib.parse.urlsplit(newurl)
            if target.scheme != 'https' or target.hostname != host:
                raise ValueError('cross-host redirect refused')
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    req = urllib.request.Request(urllib.parse.quote(url, safe=':/?=&%'), headers={'User-Agent': 'ViralViewsAudit/0.1'})
    with urllib.request.build_opener(Redirect).open(req, timeout=20) as response:
        if ('application/json' if json_response else 'text/html') not in response.headers.get('Content-Type', ''):
            raise ValueError('unexpected content type')
        body = response.read(3_000_001)
        if len(body) > 3_000_000:
            raise ValueError('response too large')
        return body.decode(response.headers.get_content_charset() or 'utf-8', errors='strict')


def naver_counter(url, fetch=get_page):
    """Follow the public article route exposed by Naver's own page/client.

    The public app currently GETs article.cafe.naver.com/gw/v4/cafes/{id}/articles/{id}.
    No cookies, art/access keys, session import or alternate access route are used.
    Error responses never become zero counts.
    """
    path = urllib.parse.urlsplit(url).path
    match = re.fullmatch(r'/([A-Za-z0-9_]+)/([0-9]+)', path)
    if not match:
        raise ValueError('unsupported Naver URL')
    article_id = int(match[2])
    page = fetch(url)
    frames = re.findall(r'ArticleRead\.nhn\?articleid=(\d+)&(?:amp;)?clubid=(\d+)', page)
    clubs = {club for article, club in frames if int(article) == article_id}
    if len(clubs) != 1:
        raise ValueError('public Naver article route not found')
    club = clubs.pop()
    endpoint = f'https://article.cafe.naver.com/gw/v4/cafes/{club}/articles/{article_id}'
    payload = json.loads(fetch(endpoint, json_response=True))
    result = payload.get('result', {})
    article = result.get('article', {})
    if (str(result.get('cafeId')) != club or result.get('articleId') != article_id
            or article.get('id') != article_id or type(article.get('readCount')) is not int):
        raise ValueError('Naver denied access or returned an unexpected article schema')
    return article['readCount']


def parse_counter(url, body):
    host = urllib.parse.urlsplit(url).hostname
    if host not in PATTERNS:
        raise ValueError('unsupported exact counter')
    if re.search(r'<title>[^<]*(captcha|access denied|just a moment|로그인)', body, re.I):
        raise ValueError('access challenge')
    # A canonical/og URL must identify the requested article, not a redirect or list.
    links = re.findall(r'<(?:meta|link)\b[^>]*(?:og:url|canonical)[^>]*>', body, re.I)
    if host == 'mlbpark.donga.com':
        article = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get('id', [''])[0]
    elif host == 'www.teamblind.com':
        article = urllib.parse.urlsplit(url).path.rsplit('-',1)[-1]
    elif host == 'm.bobaedream.co.kr':
        match = re.search(r'/bbs_view/[^/]+/(\d+)', url)
        article = match[1] if match else ''
        links = re.findall(r'"No"\s*:\s*"\d+"', body)
    else:
        article = urllib.parse.urlsplit(url).path.strip('/')
    if host == 'm.bobaedream.co.kr':
        identities = re.findall(r'"No"\s*:\s*"(\d+)"', body)
    else:
        identities = []
        for tag in links:
            for candidate in re.findall(r'(?:content|href)=[\'"]([^\'"]+)', tag):
                parsed = urllib.parse.urlsplit(html.unescape(candidate))
                if parsed.hostname != host:
                    continue
                identity = (urllib.parse.parse_qs(parsed.query).get('id', [''])[0]
                            if host == 'mlbpark.donga.com' else
                            parsed.path.rsplit('-', 1)[-1] if host == 'www.teamblind.com'
                            else parsed.path.strip('/'))
                identities.append(identity)
    if not article or article not in identities:
        raise ValueError('article identity not confirmed')
    hits = re.findall(PATTERNS[host], body)
    if len(hits) != 1 or not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)', hits[0]):
        raise ValueError('missing or ambiguous exact counter')
    return int(hits[0].replace(',', ''))


def hogang_counter(url, body):
    match = re.fullmatch(r'/community/apts/apts-(\d+)', urllib.parse.urlsplit(url).path)
    payloads = re.findall(r'<script id="__HGNN_DATA__"[^>]*>(.*?)</script>', body, re.S)
    if not match or len(payloads) != 1:
        raise ValueError('no public article state')
    article_id = int(match[1])
    data = json.loads(payloads[0])
    hits = []
    for query in data.get('queryState', {}).get('queries', []):
        key = query.get('queryKey', [{}])[0]
        if key.get('entity') != 'getReviewById' or key.get('params', {}).get('reviewId') != article_id:
            continue
        review = query.get('state', {}).get('data', {}).get('review', {})
        if review.get('reviewId') != article_id or any(review.get(k) for k in ['isBlocked','isDeleted','isBlinded']):
            raise ValueError('unavailable review')
        if type(review.get('viewCount')) is not int:
            raise ValueError('no exact review count')
        hits.append(review['viewCount'])
    if len(hits) != 1:
        raise ValueError('ambiguous review identity')
    return hits[0]


def ts_records(text, group):
    result = []
    for m in BLOCKS.finditer(text):
        url = re.search(r"url: '([^']+)'", m[0])
        count = re.search(r'views: (null|\d+)', m[0])
        if not url or not count:
            raise ValueError('unrecognized TypeScript record')
        result.append({'url': url[1], 'views': None if count[1] == 'null' else int(count[1]), 'group': group})
    if not result:
        raise ValueError('no data records')
    return result


def html_records(text):
    result = []
    tables = list(TBODY.finditer(text))
    if len(tables) < 2:
        raise ValueError('expected posts and shares tables')
    for table, group in zip(tables[:2], ['posts', 'shares']):
        for row in ROW.findall(table[2]):
            link = re.search(r'<a\b[^>]*href="([^"]+)"', row)
            count = re.search(r'class="views-num">([\d,]+)</span>', row)
            if not link:
                raise ValueError('row without source URL')
            result.append({'url': html.unescape(link[1]), 'views': int(count[1].replace(',', '')) if count else None, 'group': group})
    return result


def records(root):
    if (root / 'src/data/posts.ts').is_file():
        return sum([ts_records((root / f'src/data/{g}.ts').read_text(), g) for g in ['posts', 'shares']], [])
    return html_records((root / 'index.html').read_text())


def collect(items, fetch=get_page, delay=1.0):
    results = {}
    failures = collections.Counter()
    for item in items:
        url = item['url']
        if url in results:
            continue
        host = urllib.parse.urlsplit(url).hostname
        if item['views'] is None or host not in {*PATTERNS, 'cafe.naver.com', 'hogangnono.com'}:
            results[url] = {'status': 'unavailable', 'reason': 'no validated public exact counter'}
            continue
        if failures[host] >= 5:
            results[url] = {'status': 'unavailable', 'reason': 'host unavailable after five consecutive failures'}
            continue
        try:
            if host == 'cafe.naver.com':
                value = naver_counter(url, fetch)
            elif host == 'hogangnono.com':
                value = hogang_counter(url, fetch(url))
            else:
                value = parse_counter(url, fetch(url))
            if value < item['views'] or value > max(item['views'] * 3, item['views'] + 10000):
                raise ValueError('counter regression or unusual increase')
            results[url] = {'status': 'ok', 'views': value}
            failures[host] = 0
        except Exception as exc:
            # Never include response bodies, headers, cookies or exception URL details.
            results[url] = {'status': 'unavailable', 'reason': type(exc).__name__}
            failures[host] += 1
        if delay:
            if failures[host] == 5:
                print('Preserving remaining values for unavailable host: ' + host, flush=True)
            elif len(results) % 25 == 0:
                print('Checked records: ' + str(len(results)), flush=True)
            time.sleep(delay)
    return results


def stamp(now):
    t = now.astimezone(KST)
    return f'{t.year}. {t.month}. {t.day} {t:%H:%M}'


def changes(items, snapshot):
    updates = {}
    for item in items:
        got = snapshot.get(item['url'], {})
        value = got.get('views')
        if got.get('status') != 'ok':
            continue
        if type(value) is not int or item['views'] is None or value < item['views']:
            raise ValueError('invalid or decreasing observation')
        if value != item['views']:
            updates[item['url']] = value
    return updates


def edit_ts(text, updates, when):
    def edit(m):
        block = m[0]
        url = re.search(r"url: '([^']+)'", block)[1]
        if url not in updates:
            return block
        block = re.sub(r'views: \d+', f'views: {updates[url]}', block, count=1)
        note = re.search(r"    note: '([^']*)',", block)
        old_note = re.sub(r'^자동 확인: .*?(?: · 이전 메모: |$)', '', note[1]) if note else ''
        message = f'자동 확인: {when}' + (f' · 이전 메모: {old_note}' if old_note else '')
        if note:
            block = block[:note.start()] + f"    note: '{message}'," + block[note.end():]
        else:
            block = block.replace('\n  },', f"\n    note: '{message}',\n  }},")
        return block
    return BLOCKS.sub(edit, text)


def edit_report(text, updates, when):
    table_index = 0
    def table_edit(m):
        nonlocal table_index
        idx = table_index
        table_index += 1
        if idx > 1:
            return m[0]
        rows = ROW.findall(m[2])
        changed = False
        output = []
        for row in rows:
            url = html.unescape(re.search(r'<a\b[^>]*href="([^"]+)"', row)[1])
            if url in updates:
                changed = True
                row = re.sub(r'(class="views-num">)[\d,]+', lambda x: x[1] + f'{updates[url]:,}', row, count=1)
                row = re.sub(r'<small class="muted" data-auto-checked="true">.*?</small>', '', row)
                row = re.sub(r'(<small class="muted">)(?!이전 메모:)(.*?)(</small>)',
                             lambda x: x[1]+'이전 메모: '+x[2]+x[3], row)
                row = re.sub(r'(class="views-num">[\d,]+</span>)', lambda x: x[1] + f'<small class="muted" data-auto-checked="true">확인 {when}</small>', row, count=1)
            output.append(row)
        if not changed:
            return m[0]
        if idx == 0:
            def views(row):
                return int(re.search(r'class="views-num">([\d,]+)', row)[1].replace(',', ''))
            output.sort(key=views, reverse=True)
            maximum = views(output[0])
            for rank, row in enumerate(output, 1):
                row = re.sub(r'(class="col-rank">)\d+', lambda x: x[1] + str(rank), row, count=1)
                ratio = 100 * views(row) / maximum if maximum else 0
                output[rank-1] = re.sub(r'--w:[\d.]+%', f'--w:{ratio:.1f}%', row, count=1)
        # Keep original separators/indentation and every unrelated table intact.
        it = iter(output)
        return m[1] + ROW.sub(lambda _: next(it), m[2]) + m[3]
    result = TBODY.sub(table_edit, text)
    if any(i['group'] == 'posts' and i['url'] in updates for i in html_records(text)):
        old_total = sum(i['views'] for i in html_records(text) if i['group'] == 'posts')
        new_total = sum(i['views'] for i in html_records(result) if i['group'] == 'posts')
        result = result.replace(f'data-count="{old_total}">{old_total:,}', f'data-count="{new_total}">{new_total:,}')
        result = result.replace(f'<strong>{old_total:,}회</strong>', f'<strong>{new_total:,}회</strong>')
        result = re.sub(r'(<p class="stat-label">누적 조회수 <span class="stat-note">).*?(</span>)',
                        lambda m: m[1] + '항목별 확인 시각 참고 · 미확인 값 보존' + m[2], result, count=1)
    return result


def plan(root, snapshot, now):
    items = records(root)
    updates = changes(items, snapshot)
    if not updates:
        return {}
    when = stamp(now)
    guide_summary = f'확인 시도: {when} · 미확인 항목은 이전 값 유지'
    output = {}
    verified = {i['url']: snapshot[i['url']]['views'] for i in items
                if snapshot.get(i['url'], {}).get('status') == 'ok' and i['views'] is not None}
    def summary(group):
        members = [i for i in items if i['group'] == group]
        success = sum(i['url'] in verified for i in members)
        retained = sum(i['views'] is not None and i['url'] not in verified for i in members)
        hidden = sum(i['views'] is None for i in members)
        return f'확인 시도: {when} · 확인 {success}건 · 이전 값 유지 {retained}건 · 공개 조회수 없음 {hidden}건'
    if (root / 'src/data/posts.ts').is_file():
        for group in ['posts', 'shares']:
            p = root / f'src/data/{group}.ts'
            old = p.read_text()
            new = edit_ts(old, verified, when)
            if group == 'posts':
                new = re.sub(r"export const viewsAsOf = '[^']+'", f"export const viewsAsOf = '{when}'", new)
            if new != old:
                output[p] = new
        p = root / 'src/content/overview.mdx'
        old = p.read_text()
        note = ('게시글 목록은 바이럴 마케팅 리포트에서 가져왔습니다. 공개 조회수를 확인한 글만 갱신했습니다. '
                '확인하지 못한 글은 이전 값과 항목에 남아 있는 확인 시각을 유지했습니다.\n\n' + guide_summary)
        output[p] = re.sub(r'(<Callout type="info" title="숫자 기준">).*?(</Callout>)',
                           lambda m: m[1]+'\n'+note+'\n'+m[2], old, count=1, flags=re.S)
        p = root / 'src/content/results.mdx'
        text = p.read_text()
        for group, title in [('posts','게시글 집계 기준'), ('shares','확산 사례 집계 기준')]:
            content = (guide_summary + '\n\n확인하지 못한 항목은 이전 값과 기존 확인 시각을 유지합니다. '
                       '항목별 메모를 함께 확인해 주세요.')
            text = re.sub(r'(<Callout type="info" title="'+title+r'">).*?(</Callout>)',
                          lambda m: m[1]+'\n'+content+'\n'+m[2], text, count=1, flags=re.S)
        output[p] = text
    else:
        p = root / 'index.html'
        text = edit_report(p.read_text(), verified, when)
        # Replace only the section's global timestamp marker, never per-item fallback notes.
        group_index = 0
        def replace_summary(m):
            nonlocal group_index
            group = 'posts' if group_index == 0 else 'shares'
            group_index += 1
            return '<span class="muted" data-auto-summary="true">'+summary(group)+'</span>'
        text = re.sub(r'<span class="muted"(?: data-auto-summary="true")?>\((?:조회수:).*?</span>|<span class="muted" data-auto-summary="true">.*?</span>', replace_summary, text)
        text = re.sub(r'<span class="muted">(?:접근 오류가 있는|로그인 요구로 갱신하지 못한).*?</span>',
                      '<span class="muted">확인하지 못한 항목은 이전 값과 기존 확인 시각을 유지했습니다. 항목별 메모를 함께 확인해 주세요.</span>', text, flags=re.S)
        text = re.sub(r'(워크샵 공유자료 · )(?:조회수는 .*? 기준|최근 확인 시도: [^<]+)',
                      lambda m: m[1]+'최근 확인 시도: '+when+' (일부 항목 이전 값 유지)', text)
        output[p] = text
    for p, content in output.items():
        if p.suffix == '.mdx':
            continue
        before = ts_records(p.read_text(), p.stem) if p.suffix == '.ts' else html_records(p.read_text())
        after = ts_records(content, p.stem) if p.suffix == '.ts' else html_records(content)
        if collections.Counter(i['url'] for i in before) != collections.Counter(i['url'] for i in after):
            raise ValueError('record identity changed')
        before_map = {i['url']: i['views'] for i in before}
        for item in after:
            expected = verified.get(item['url'], before_map[item['url']])
            if item['views'] != expected:
                raise ValueError('unexpected counter replacement')
    output = {p: content for p, content in output.items() if p.read_text() != content}
    return output


def source_fingerprint(body, kind):
    if kind == 'kasi':
        parts = re.findall(r'https://gwanbo\.go\.kr/[^\'"<>\s]+', body)
    else:
        parts = []
        for href, title in re.findall(r'<a[^>]+href="([^"]*cntId=\d+[^"]*)"[^>]*>(.*?)</a>', body, re.S):
            identity = re.search(r'cntId=(\d+)', href)[1]
            title = re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', '', title))).strip()
            if title:
                parts.append(identity + ':' + title)
    if not parts:
        raise ValueError('official calendar source unrecognized')
    return hashlib.sha256('\n'.join(sorted(set(parts))).encode()).hexdigest()


def calendar_gate(config, now, fetch=get_page):
    local = now.astimezone(KST)
    if local.weekday() >= 5:
        return False
    if not config.get('reviewed') or config.get('year') != local.year:
        raise ValueError('official holiday calendar not reviewed for this year')
    if not config['valid_from'] <= local.date().isoformat() <= config['valid_through']:
        raise ValueError('outside verified holiday coverage')
    for kind, url in [('kasi', KASI), ('mpm', MPM)]:
        try:
            fingerprint = source_fingerprint(fetch(url), kind)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            reviewed = dt.date.fromisoformat(config['reviewed_on'])
            offline_until = dt.date.fromisoformat(config.get('offline_valid_through', '1900-01-01'))
            if reviewed <= local.date() <= min(offline_until, reviewed + dt.timedelta(days=7)):
                print('Using reviewed calendar during temporary source failure: ' + kind, flush=True)
                continue
            raise ValueError('official calendar unavailable and offline review expired: ' + kind) from None
        except Exception as exc:
            raise ValueError('official calendar source unavailable: ' + kind + ' (' + type(exc).__name__ + ')') from None
        if fingerprint != config['fingerprints'][kind]:
            raise ValueError('official holiday announcements changed; review required')
    return local.date().isoformat() not in config['holidays']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path.cwd())
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--scheduled', action='store_true')
    ap.add_argument('--calendar-only', action='store_true')
    ap.add_argument('--probe', help='read a single public article without modifying files')
    args = ap.parse_args()
    root = args.root.resolve()
    now = dt.datetime.now(dt.timezone.utc)
    if args.probe:
        value = naver_counter(args.probe) if urllib.parse.urlsplit(args.probe).hostname == 'cafe.naver.com' else parse_counter(args.probe, get_page(args.probe))
        print(json.dumps({'views': value}))
        return
    lockpath = Path(tempfile.gettempdir()) / ('viral-refresh-' + hashlib.sha256(str(root).encode()).hexdigest()[:16] + '.lock')
    with lockpath.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = json.loads((root / 'automation/calendar.json').read_text())
        if args.calendar_only:
            print('Calendar check: ' + ('eligible weekday' if calendar_gate(config, now) else 'holiday/weekend'))
            return
        if args.scheduled and not calendar_gate(config, now):
            print('Skipped: weekend or official Korean holiday')
            return
        if args.apply:
            if not config.get('collector_ready'):
                raise ValueError('activation blocked: full collector coverage not validated')
            if not args.scheduled:
                raise ValueError('--apply requires --scheduled calendar guard')
            if git(root, 'rev-parse', '--show-toplevel') != str(root) or git(root, 'branch', '--show-current') != 'main':
                raise ValueError('unexpected repository or branch')
            if git(root, 'status', '--porcelain'):
                raise ValueError('existing local changes; refusing to mix changes')
        items = records(root)
        snapshot = collect(items)
        ok = sum(snapshot[i['url']]['status'] == 'ok' for i in items if i['views'] is not None)
        numeric = sum(i['views'] is not None for i in items)
        direct = [i for i in items if i['group'] == 'posts']
        direct_ok = sum(snapshot[i['url']]['status'] == 'ok' for i in direct)
        output = plan(root, snapshot, now)
        print(json.dumps({'exact_counts': ok, 'numeric_records': numeric, 'preserved_records': numeric-ok,
                          'direct_exact_counts': direct_ok, 'direct_records': len(direct),
                          'changed_files': [str(p.relative_to(root)) for p in output],
                          'mode': 'apply' if args.apply else 'dry-run'}, ensure_ascii=False))
        if args.apply:
            if direct_ok / max(1,len(direct)) < .9:
                raise ValueError('less than 90% verified; preserving all files')
            # Validate all planned replacements before making any file changes.
            for p, content in output.items():
                tmp = p.with_name(p.name + '.refresh-tmp')
                tmp.write_text(content)
                os.replace(tmp, p)


if __name__ == '__main__':
    main()
