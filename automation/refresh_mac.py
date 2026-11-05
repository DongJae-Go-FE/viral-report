#!/usr/bin/env python3
"""Isolated Mac refresh. No schedule is installed by this program.

Existing collectors retain their holiday, source and coverage guards. Work is
performed in a temporary clone; user checkouts are only fast-forwarded while
clean. Never reset, stash, force push, or export credentials.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from zoneinfo import ZoneInfo

HOME_DIR = Path('/Users/kardongjae')
PROJECTS = {
    'viral-guide': HOME_DIR / 'Development/viral-guide',
    'viral-report': HOME_DIR / 'Development/workshop/viral-report',
}
ALLOWED = {
    'viral-guide': {'src/data/posts.ts', 'src/data/shares.ts', 'src/content/overview.mdx', 'src/content/results.mdx'},
    'viral-report': {'index.html'},
}
PNPM_DIR = HOME_DIR / '.nvm/versions/node/v22.23.4/bin'
ENV = {**os.environ, 'PATH': f'{PNPM_DIR}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
       'GIT_TERMINAL_PROMPT': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
PYTHON = '/opt/homebrew/bin/python3'
STATE = HOME_DIR / 'Library/Application Support/viral-sync/refresh-state.json'
DATA_CHECK = '''
import sys
from pathlib import Path
sys.path.insert(0, 'automation')
from refresh import records
root = Path.cwd()
items = records(root)
posts = [x for x in items if x['group'] == 'posts']
if len(posts) != 164 or len(items) != 211 or len({i['url'] for i in items}) != len(items):
    raise ValueError('unexpected item count or duplicate source')
if not (root / 'src/data/posts.ts').exists():
    values = [x['views'] for x in posts]
    if values != sorted(values, reverse=True):
        raise ValueError('post ordering invalid')
    if f'data-count="{sum(values)}">{sum(values):,}' not in (root / 'index.html').read_text():
        raise ValueError('headline total mismatch')
'''

def run(root, *args, timeout=120):
    return subprocess.check_output(args, cwd=root, env=ENV, text=True,
                                   stderr=subprocess.STDOUT, timeout=timeout).strip()

def git(root, *args):
    return run(root, '/usr/bin/git', *args)

def eligible(now):
    local = now.astimezone(ZoneInfo('Asia/Seoul'))
    return local.weekday() < 5 and local.hour >= 9

def preflight(root, name):
    if git(root, 'rev-parse', '--show-toplevel') != str(root):
        raise ValueError('unexpected checkout')
    if git(root, 'branch', '--show-current') != 'main' or git(root, 'status', '--porcelain'):
        raise ValueError('main must be clean, including untracked files')
    if git(root, 'remote', 'get-url', 'origin') != f'https://github.com/DongJae-Go-FE/{name}.git':
        raise ValueError('unexpected remote')
    gd = Path(git(root, 'rev-parse', '--absolute-git-dir'))
    if any((gd / p).exists() for p in ('index.lock', 'MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'sequencer')):
        raise ValueError('git operation in progress')
    return git(root, 'rev-parse', 'HEAD')

def changed_paths(root, name):
    if git(root, 'diff', '--cached', '--name-only') or git(root, 'ls-files', '--others', '--exclude-standard') or git(root, 'ls-files', '-u'):
        raise ValueError('unexpected staged, untracked, or conflicted files')
    paths = set(git(root, 'diff', '--name-only').splitlines())
    if not paths <= ALLOWED[name]:
        raise ValueError('unexpected changed paths')
    git(root, 'diff', '--check')
    return paths

def refresh(name, apply=False):
    root = PROJECTS[name]
    lockpath = Path(tempfile.gettempdir()) / ('viral-refresh-' + hashlib.sha256(str(root).encode()).hexdigest()[:16] + '.lock')
    with lockpath.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = preflight(root, name)
        remote = git(root, 'remote', 'get-url', 'origin')
        if git(root, 'ls-remote', 'origin', 'refs/heads/main').split()[0] != before:
            raise ValueError('local and remote main differ; reconcile safely before retry')
        identity = (git(root, 'config', 'user.name'), git(root, 'config', 'user.email'))
        # Local clone does not mutate the user's repository or share hardlinks.
        with tempfile.TemporaryDirectory(prefix=name + '-refresh-') as directory:
            work = Path(directory) / name
            run(root, '/usr/bin/git', 'clone', '--no-hardlinks', '--single-branch', '--branch', 'main', str(root), str(work))
            git(work, 'remote', 'set-url', 'origin', remote)
            run(work, PYTHON, '-m', 'unittest', 'discover', '-s', 'automation', '-p', 'test_*.py')
            print(name + ': collecting in isolated checkout', flush=True)
            subprocess.run([PYTHON, 'automation/refresh.py', '--scheduled', '--apply'],
                           cwd=work, env=ENV, check=True, timeout=1200)
            paths = changed_paths(work, name)
            if not paths:
                return 'no changed values'
            run(work, PYTHON, '-c', DATA_CHECK)
            if name == 'viral-guide':
                run(work, str(PNPM_DIR / 'pnpm'), 'install', '--offline', '--frozen-lockfile', timeout=300)
                run(work, str(PNPM_DIR / 'pnpm'), 'lint', timeout=300)
                run(work, str(PNPM_DIR / 'pnpm'), 'build', timeout=300)
            else:
                run(work, 'node', '--check', 'script.js')
            if changed_paths(work, name) != paths:
                raise ValueError('validation changed file set')
            if not apply:
                return 'validated isolated refresh; dry-run: no commit or push'
            if preflight(root, name) != before:
                raise ValueError('user checkout changed during collection')
            if git(work, 'ls-remote', 'origin', 'refs/heads/main').split()[0] != before:
                raise ValueError('remote changed during collection')
            git(work, 'add', '--', *sorted(paths))
            stamp = dt.datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M KST')
            git(work, '-c', 'user.name=' + identity[0], '-c', 'user.email=' + identity[1], 'commit', '-m', f'Refresh public view counts ({stamp})', '-m', 'Viral-Refresh-Verified: true')
            sha = git(work, 'rev-parse', 'HEAD')
            git(work, 'push', 'origin', 'HEAD:refs/heads/main')
            if git(work, 'ls-remote', 'origin', 'refs/heads/main').split()[0] != sha:
                raise ValueError('push outcome not verified; inspect remote before retry')
            # Existing sync agent can also integrate this verified data-only commit.
            if preflight(root, name) == before:
                git(root, 'fetch', '--no-tags', 'origin', 'main')
                if preflight(root, name) == before:
                    git(root, 'merge', '--ff-only', sha)
            return 'verified push ' + sha

def main_unlocked():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--preflight', action='store_true', help='read-only authentication and calendar checks in the launchd environment')
    ap.add_argument('--project', choices=PROJECTS)
    args = ap.parse_args()
    if args.preflight:
        for name in ([args.project] if args.project else PROJECTS):
            root = PROJECTS[name]
            before = preflight(root, name)
            if git(root, 'ls-remote', 'origin', 'refs/heads/main').split()[0] != before:
                raise ValueError('local and remote main differ')
            git(root, 'push', '--dry-run', 'origin', 'HEAD:refs/heads/main')
            print(run(root, PYTHON, 'automation/refresh.py', '--calendar-only'), flush=True)
            print(name + ': launchd preflight passed', flush=True)
        return
    now = dt.datetime.now(dt.timezone.utc)
    if not eligible(now):
        print('skip: before 09:00 KST or weekend')
        return
    day = now.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    failed = False
    for name in ([args.project] if args.project else PROJECTS):
        if args.apply and state.get(name, {}).get('date') == day:
            print(name + ': already completed today', flush=True)
            continue
        try:
            result = refresh(name, args.apply)
            print(name + ': ' + result, flush=True)
            if args.apply:
                state[name] = {'date': day, 'result': result}
                temporary = STATE.with_suffix('.tmp')
                temporary.write_text(json.dumps(state, indent=2) + '\n')
                temporary.replace(STATE)
        except Exception as exc:
            # No credential-bearing command output in unattended logs.
            print(name + ': FAILED ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), flush=True)
            failed = True
    raise SystemExit(1 if failed else 0)

def main():
    with (Path(tempfile.gettempdir()) / 'viral-mac-refresh-global.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('another Mac refresh is running')
        main_unlocked()

if __name__ == '__main__':
    main()
