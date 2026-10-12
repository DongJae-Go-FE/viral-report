#!/usr/bin/env python3
"""Bounded local fast-forward sync, disabled until the server protocol is active.

Uses existing git authentication without reading/exporting credentials. Never
stashes, resets, changes branches, rebases or forces a push. A dirty or diverged
checkout is left untouched. Dry-run unless --apply is supplied.
"""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
from zoneinfo import ZoneInfo

PROJECTS = {
    'viral-guide': (Path('/Users/kardongjae/Development/viral-guide'),
                    {'src/data/posts.ts', 'src/data/shares.ts', 'src/content/overview.mdx', 'src/content/results.mdx'}),
    'viral-report': (Path('/Users/kardongjae/Development/workshop/viral-report'), {'index.html'}),
}


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True,
                                   timeout=40, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'}).strip()


def window(now):
    local = now.astimezone(ZoneInfo('Asia/Seoul'))
    # One launch at :20 and one bounded retry at :40, never replay old days.
    return local.weekday() < 5 and local.hour in (9, 15) and 15 <= local.minute <= 50


def validate_checkout(root, name):
    if git(root, 'rev-parse', '--show-toplevel') != str(root) or git(root, 'branch', '--show-current') != 'main':
        raise ValueError('wrong repository or branch')
    if git(root, 'status', '--porcelain'):
        raise ValueError('uncommitted or untracked changes')
    if git(root, 'remote', 'get-url', 'origin') != f'https://github.com/DongJae-Go-FE/{name}.git':
        raise ValueError('unexpected remote')
    gd = Path(git(root, 'rev-parse', '--absolute-git-dir'))
    for marker in ['index.lock', 'MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'sequencer']:
        if (gd / marker).exists():
            raise ValueError('git operation in progress')


def sync(name, root, allowed, now, apply=False):
    validate_checkout(root, name)
    before = git(root, 'rev-parse', 'HEAD')
    if not apply:
        return 'dry-run: local preflight passed; no fetch or merge'
    # The same lock is used by refresh.py to avoid refresh/pull overlap.
    git(root, 'fetch', '--no-tags', 'origin', 'main')
    target = git(root, 'rev-parse', 'FETCH_HEAD')
    if target == before:
        return 'already current'
    git(root, 'merge-base', '--is-ancestor', before, target)
    # Every incoming commit must be a scheduled validated refresh, not unrelated work.
    for sha in git(root, 'rev-list', f'{before}..{target}').splitlines():
        message = git(root, 'show', '-s', '--format=%B', sha)
        if 'Viral-Refresh-Verified: true' not in message:
            raise ValueError('server completion marker missing')
        changed = set(git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', sha).splitlines())
        if not changed or not changed <= allowed:
            raise ValueError('server commit contains unrelated paths')
    committed = dt.datetime.fromisoformat(git(root, 'show', '-s', '--format=%cI', target))
    age = (now - committed).total_seconds()
    if not 0 <= age <= 3600:
        raise ValueError('stale server update; no catch-up')
    # Recheck after the network operation; integrate exactly the inspected SHA.
    validate_checkout(root, name)
    if git(root, 'rev-parse', 'HEAD') != before:
        raise ValueError('checkout changed during fetch')
    git(root, 'merge', '--ff-only', target)
    return 'fast-forwarded to ' + target


def main():
    import hashlib
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    if not window(now):
        print('skip: outside current weekday sync window')
        return
    for name, (root, allowed) in PROJECTS.items():
        lockpath = Path(tempfile.gettempdir()) / ('viral-refresh-' + hashlib.sha256(str(root).encode()).hexdigest()[:16] + '.lock')
        try:
            with lockpath.open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                config = json.loads((root / 'automation/calendar.json').read_text())
                if not config.get('collector_ready'):
                    raise ValueError('server activation not approved/validated')
                local_date = now.astimezone(ZoneInfo('Asia/Seoul')).date()
                if (not config.get('reviewed') or config.get('year') != local_date.year
                        or not config['valid_from'] <= local_date.isoformat() <= config['valid_through']
                        or local_date.isoformat() in config['holidays']):
                    raise ValueError('holiday or unverified calendar date')
                print(name + ': ' + sync(name, root, allowed, now, args.apply))
        except Exception as exc:
            print(name + ': skipped (' + type(exc).__name__ + ')')


if __name__ == '__main__':
    main()
