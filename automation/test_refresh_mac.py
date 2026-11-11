import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import refresh_mac as m

class Safety(unittest.TestCase):
    def test_current_dataset_matches_expected_counts(self):
        root = Path(__file__).resolve().parents[1]
        with patch.object(Path, 'cwd', return_value=root):
            exec(m.DATA_CHECK, {})

    def test_time_gate(self):
        # UTC midnight is 09:00 in Korea.
        self.assertFalse(m.eligible(dt.datetime(2026, 11, 5, 23, 59, tzinfo=dt.timezone.utc) - dt.timedelta(days=1)))

    def test_weekday_and_weekend(self):
        self.assertTrue(m.eligible(dt.datetime.fromisoformat('2026-11-06T09:00:00+09:00')))
        self.assertFalse(m.eligible(dt.datetime.fromisoformat('2026-11-06T08:59:00+09:00')))
        self.assertFalse(m.eligible(dt.datetime.fromisoformat('2026-11-07T09:00:00+09:00')))

    def test_dirty_checkout_refused(self):
        with patch.object(m, 'git', side_effect=['/checkout', 'main', ' M index.html']):
            with self.assertRaisesRegex(ValueError, 'clean'):
                m.preflight(Path('/checkout'), 'viral-report')

    def test_wrong_remote_refused(self):
        with patch.object(m, 'git', side_effect=['/checkout', 'main', '', 'https://example.org/repo.git']):
            with self.assertRaisesRegex(ValueError, 'remote'):
                m.preflight(Path('/checkout'), 'viral-report')

    def test_unrelated_changes_refused(self):
        with patch.object(m, 'git', side_effect=['', '', '', 'index.html\nscript.js']):
            with self.assertRaisesRegex(ValueError, 'paths'):
                m.changed_paths(Path('/checkout'), 'viral-report')

    def test_staged_changes_refused(self):
        with patch.object(m, 'git', return_value='index.html'):
            with self.assertRaisesRegex(ValueError, 'staged'):
                m.changed_paths(Path('/checkout'), 'viral-report')

    def test_allowed_changes(self):
        with patch.object(m, 'git', side_effect=['', '', '', 'index.html', '']):
            self.assertEqual(m.changed_paths(Path('/checkout'), 'viral-report'), {'index.html'})

    def test_remote_movement_stops_before_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(m, 'PROJECTS', {'viral-report': Path(tmp)}), patch.object(m, 'preflight', return_value='old'), patch.object(m, 'git', side_effect=['https://github.com/DongJae-Go-FE/viral-report.git', 'new refs/heads/main']), patch.object(m, 'run') as command:
                with self.assertRaisesRegex(ValueError, 'differ'):
                    m.refresh('viral-report', True)
                command.assert_not_called()

if __name__ == '__main__':
    unittest.main()
