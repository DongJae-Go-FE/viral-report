import copy
import datetime as dt
import json
from pathlib import Path
import unittest
import urllib.error
import refresh as r

class ReviewedYears(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(Path(__file__).with_name('calendar.json').read_text())
        self.year = self.config['reviewed_years']['2027']
        self.bodies = {'kasi': 'https://www.gwanbo.go.kr/ezpdf/test2027',
                       'mpm': '<a href="?cntId=123">검토한 공휴일 공지</a>'}
        self.year['fingerprints'] = {k:r.source_fingerprint(v,k) for k,v in self.bodies.items()}
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        return self.bodies['kasi' if url == self.year['source_urls']['kasi'] else 'mpm']

    def date(self, value):
        return dt.datetime.fromisoformat(value + 'T09:00:00+09:00')

    def test_all_365_days_match_reviewed_national_holidays(self):
        holidays = set(self.year['holidays'])
        self.assertEqual(len(holidays), 24)
        days_off = 0
        for offset in range(365):
            date = dt.date(2027,1,1) + dt.timedelta(days=offset)
            expected = date.weekday() < 5 and date.isoformat() not in holidays
            result = r.calendar_gate(self.config, self.date(date.isoformat()), self.fetch)
            self.assertEqual(result, expected, date.isoformat())
            days_off += not result
        self.assertEqual(days_off, 119)  # Official KASA five-day-workweek total.
        self.assertIn(self.year['source_urls']['kasi'], self.urls)
        self.assertNotIn(r.KASI, self.urls)

    def test_substitute_holidays_and_regular_weekday(self):
        for date in ['2027-02-09','2027-05-03','2027-07-19','2027-08-16','2027-10-04','2027-10-11','2027-12-27']:
            self.assertFalse(r.calendar_gate(self.config,self.date(date),self.fetch), date)
        self.assertTrue(r.calendar_gate(self.config,self.date('2027-01-04'),self.fetch))

    def test_unreviewed_year_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'not reviewed'):
            r.calendar_gate(self.config,self.date('2028-01-03'),self.fetch)

    def test_changed_official_announcement_blocks(self):
        self.bodies['mpm'] = '<a href="?cntId=999">새 임시공휴일</a>'
        with self.assertRaisesRegex(ValueError, 'changed'):
            r.calendar_gate(self.config,self.date('2027-01-04'),self.fetch)

    def test_changed_gazette_link_blocks(self):
        self.bodies['kasi'] = 'https://www.gwanbo.go.kr/ezpdf/revised2027'
        with self.assertRaisesRegex(ValueError, 'changed'):
            r.calendar_gate(self.config,self.date('2027-01-04'),self.fetch)

    def test_network_failure_cannot_use_2026_review_in_2027(self):
        def fail(_): raise urllib.error.URLError('offline')
        with self.assertRaisesRegex(ValueError, 'offline review expired'):
            r.calendar_gate(self.config,self.date('2027-01-04'),fail)

    def test_missing_source_blocks(self):
        del self.year['source_urls']['mpm']
        with self.assertRaisesRegex(ValueError,'both official'):
            r.calendar_gate(self.config,self.date('2027-01-04'),self.fetch)

    def test_www_and_original_gazette_hosts(self):
        self.assertTrue(r.source_fingerprint('https://gwanbo.go.kr/a','kasi'))
        self.assertTrue(r.source_fingerprint('https://www.gwanbo.go.kr/a','kasi'))
        with self.assertRaises(ValueError):
            r.source_fingerprint('https://fake-gwanbo.go.kr/a','kasi')

if __name__ == '__main__':
    unittest.main()
