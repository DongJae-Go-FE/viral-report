#!/usr/bin/env python3
"""Validate, commit only expected data files, then make a normal main push.

Run only in GitHub Actions after refresh.py succeeds. Uses the existing job token
configured by checkout; never reads credentials, creates tokens or forces pushes.
"""
import datetime as dt
import os
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo
from refresh import git, records


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('This publishing command is restricted to the approved Actions job')
    root = Path.cwd().resolve()
    repo = os.environ['GITHUB_REPOSITORY']
    guide = repo == 'DongJae-Go-FE/viral-guide'
    if repo not in ('DongJae-Go-FE/viral-guide', 'DongJae-Go-FE/viral-report'):
        raise ValueError('unexpected repository')
    if git(root, 'branch', '--show-current') != 'main':
        raise ValueError('not on main')
    remote = git(root, 'remote', 'get-url', 'origin').removesuffix('.git')
    if remote != 'https://github.com/' + repo:
        raise ValueError('unexpected remote')
    allowed = ({'src/data/posts.ts', 'src/data/shares.ts', 'src/content/overview.mdx', 'src/content/results.mdx'}
               if guide else {'index.html'})
    changed = set(git(root, 'diff', '--name-only').splitlines())
    if git(root, 'diff', '--cached', '--name-only') or git(root, 'ls-files', '--others', '--exclude-standard'):
        raise ValueError('pre-existing staged or untracked files')
    if not changed:
        print('No changed values; no commit or push')
        return
    if not changed <= allowed or git(root, 'ls-files', '-u'):
        raise ValueError('unexpected changes or conflict')
    # Same identities must survive every update; numerical checks are done before publishing.
    items = records(root)
    posts = [x for x in items if x['group'] == 'posts']
    if len(posts) != 151 or len(items) != 190 or len({i['url'] for i in items}) != len(items):
        raise ValueError('unexpected item count/duplicate source')
    git(root, 'diff', '--check')
    if guide:
        subprocess.run(['pnpm', 'lint'], check=True)
        subprocess.run(['pnpm', 'build'], check=True)
    else:
        subprocess.run(['node', '--check', 'script.js'], check=True)
        values = [x['views'] for x in posts]
        if values != sorted(values, reverse=True):
            raise ValueError('post ordering invalid')
        text = (root / 'index.html').read_text()
        if f'data-count="{sum(values)}">{sum(values):,}' not in text:
            raise ValueError('headline total mismatch')
    # Recheck the allowlist after validation/build.
    if set(git(root, 'diff', '--name-only').splitlines()) != changed:
        raise ValueError('validation changed other files')
    git(root, 'add', '--', *sorted(changed))
    when = dt.datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M KST')
    subprocess.run(['git', '-c', 'user.name=github-actions[bot]', '-c',
                    'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                    'commit', '-m', f'Refresh public view counts ({when})',
                    '-m', 'Viral-Refresh-Verified: true'], check=True)
    subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/main'], check=True)
    sha = git(root, 'rev-parse', 'HEAD')
    if git(root, 'ls-remote', 'origin', 'refs/heads/main').split()[0] != sha:
        raise ValueError('remote verification failed')
    print('Verified remote commit: ' + sha)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('changed=true\nsha=' + sha + '\n')


if __name__ == '__main__':
    main()
