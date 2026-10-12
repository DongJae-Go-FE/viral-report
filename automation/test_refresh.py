import datetime as dt
from pathlib import Path
import tempfile
import unittest
import json
import shutil
from unittest.mock import patch

import refresh as r
import sync_local as sync

URL = 'https://www.fmkorea.com/123456'
NOW = dt.datetime(2026, 10, 12, 0, 20, tzinfo=dt.timezone.utc)


def page(value='1,234'):
    return f'<meta property="og:url" content="{URL}"><span>조회 수 <b>{value}</b></span>'


class SafetyTests(unittest.TestCase):
    def test_hogang_rejects_related_and_hidden_counts(self):
        def payload(identity=123,hidden=False):
            q={'queryKey':[{'entity':'getReviewById','params':{'reviewId':identity}}],
               'state':{'data':{'review':{'reviewId':identity,'viewCount':301,'isDeleted':hidden}}}}
            return '<script id="__HGNN_DATA__" type="application/json">'+json.dumps({'queryState':{'queries':[q]}})+'</script>'
        url='https://hogangnono.com/community/apts/apts-123'
        self.assertEqual(r.hogang_counter(url,payload()),301)
        for body in [payload(999),payload(hidden=True)]:
            with self.assertRaises(ValueError):r.hogang_counter(url,body)

    def test_article_local_blind_counter(self):
        body='<meta property="og:url" content="https://www.teamblind.com/kr/post/x-id123"><span class="pv" data-x><i class="blind">조회수</i>776</span><span>조회수 99999</span>'
        self.assertEqual(r.parse_counter('https://www.teamblind.com/kr/post/x-id123',body),776)
    def test_naver_public_schema(self):
        url = 'https://cafe.naver.com/test/123'
        def fetch(u, json_response=False):
            if not json_response:
                return 'ArticleRead.nhn?articleid=123&clubid=99'
            return json.dumps({'result': {'cafeId':99,'articleId':123,'article':{'id':123,'readCount':31490}}})
        self.assertEqual(r.naver_counter(url, fetch),31490)
        def denied(u,json_response=False):
            return json.dumps({'error':{'errorCode':'NO_AUTH'}}) if json_response else fetch(u)
        with self.assertRaises(ValueError):
            r.naver_counter(url,denied)

    def test_real_repository_partial_plan(self):
        repo = Path(__file__).resolve().parent.parent
        if not ((repo/'src/data/posts.ts').exists() or (repo/'script.js').exists()):
            self.skipTest('integration test runs from repository automation directory')
        items = r.records(repo)
        first = next(i for i in items if i['group']=='posts' and 'fmkorea.com' in i['url'])
        snapshot = {i['url']:{'status':'unavailable'} for i in items}
        self.assertEqual(r.plan(repo,snapshot,NOW),{})
        snapshot[first['url']]={'status':'ok','views':first['views']+1}
        planned=r.plan(repo,snapshot,NOW)
        self.assertTrue(planned)
        for path,content in planned.items():
            if path.suffix=='.mdx':
                self.assertIn('이전 값 유지',content)
                continue
            after=r.ts_records(content,path.stem) if path.suffix=='.ts' else r.html_records(content)
            before={i['url']:i['views'] for i in items}
            for i in after:
                self.assertEqual(i['views'],before[i['url']]+1 if i['url']==first['url'] else before[i['url']])
            if path.name=='index.html':
                direct=[i['views'] for i in after if i['group']=='posts']
                self.assertEqual(direct,sorted(direct,reverse=True))
                self.assertIn(f'data-count="{sum(direct)}">{sum(direct):,}',content)
                self.assertIn('data-auto-summary="true"',content)
    def test_exact_counter_and_identity(self):
        self.assertEqual(r.parse_counter(URL, page()), 1234)
        for body in [page('1.2만'), page('1,23'), page()+page(), page().replace('123456', '888')]:
            with self.assertRaises(ValueError):
                r.parse_counter(URL, body)

    def test_network_failure_retains_value(self):
        items = [{'url': URL, 'views': 100, 'group': 'posts'}]
        snapshot = r.collect(items, lambda _: (_ for _ in ()).throw(TimeoutError()), 0)
        self.assertEqual(r.changes(items, snapshot), {})

    def test_decrease_rejected(self):
        items = [{'url': URL, 'views': 2000, 'group': 'posts'}]
        self.assertEqual(r.changes(items, r.collect(items, lambda _: page(), 0)), {})

    def test_null_and_unsupported_not_fetched(self):
        items = [{'url': URL, 'views': None}, {'url': 'https://www.dogdrip.net/1', 'views': 400}]
        def forbidden(_):
            self.fail('must not request unsupported/private metric')
        self.assertTrue(all(x['status'] == 'unavailable' for x in r.collect(items, forbidden, 0).values()))

    def test_no_change_does_not_timestamp(self):
        items = [{'url': URL, 'views': 1234}]
        self.assertEqual(r.changes(items, {URL: {'status': 'ok', 'views': 1234}}), {})

    def test_calendar_fails_closed(self):
        with self.assertRaises(ValueError):
            r.calendar_gate({'reviewed': False}, NOW)
        self.assertFalse(r.calendar_gate({}, NOW - dt.timedelta(days=1)))

    def test_temporary_holiday_and_source_change(self):
        bodies = {'kasi': 'https://gwanbo.go.kr/test', 'mpm': '<a href="?cntId=123">기존 공휴일</a>'}
        cfg = {'reviewed': True, 'year': 2026, 'reviewed_on': '2026-10-12',
               'valid_from': '2026-10-12', 'valid_through': '2026-12-31',
               'holidays': ['2026-10-12'], 'fingerprints': {k: r.source_fingerprint(v,k) for k,v in bodies.items()}}
        fetch = lambda url: bodies['kasi' if url == r.KASI else 'mpm']
        self.assertFalse(r.calendar_gate(cfg, NOW, fetch))
        bodies['mpm'] = '<a href="?cntId=999">새 임시공휴일</a>'
        with self.assertRaises(ValueError):
            r.calendar_gate(cfg, NOW, fetch)

    def test_expired_calendar(self):
        with self.assertRaises(ValueError):
            r.calendar_gate({'reviewed': True, 'year': 2026, 'valid_from':'2026-01-01', 'valid_through':'2026-10-01'}, NOW)

    def test_ts_failed_record_byte_preservation(self):
        s = "export const posts = [\n  {\n    url: '"+URL+"',\n    views: 100,\n  },\n  {\n    url: 'https://invalid.example/2',\n    views: 7,\n    note: '이전 집계',\n  },\n]"
        out = r.edit_ts(s, {URL: 120}, '2026. 10. 12 09:00')
        self.assertEqual(list(r.BLOCKS.finditer(s))[1][0], list(r.BLOCKS.finditer(out))[1][0])
        self.assertIn('views: 120', out)
        self.assertEqual(r.edit_ts(out, {URL: 120}, '2026. 10. 12 09:00'), out)

    def test_sync_bounded_window(self):
        self.assertTrue(sync.window(NOW))
        self.assertFalse(sync.window(NOW-dt.timedelta(days=1)))
        self.assertFalse(sync.window(NOW+dt.timedelta(hours=2)))

    def test_sync_dirty_skips_network(self):
        root = Path('/example')
        def fake(root, *args):
            return {'rev-parse': '/example', 'branch': 'main', 'status': ' M index.html'}[args[0]]
        with patch.object(sync, 'git', side_effect=fake):
            with self.assertRaises(ValueError):
                sync.sync('viral-report', root, {'index.html'}, NOW, True)


if __name__ == '__main__':
    unittest.main()
