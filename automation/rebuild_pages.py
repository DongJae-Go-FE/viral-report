#!/usr/bin/env python3
"""Existing Pages build only. Requires separately approved job pages: write."""
import json
import os
import time
import urllib.request

REPO = 'DongJae-Go-FE/viral-report'
BASE = 'https://api.github.com/repos/' + REPO

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('unexpected API redirect')

def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPO:
        raise ValueError('restricted to viral-report Actions')
    sha = os.environ['EXPECTED_SHA']
    if len(sha) != 40 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('invalid commit')
    token = os.environ['GITHUB_TOKEN']
    def request(path, method='GET'):
        req = urllib.request.Request(BASE + path, method=method, headers={
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as response:
            return json.load(response)
    site = request('/pages')
    if site.get('source') != {'branch':'main','path':'/'} or site.get('build_type', 'legacy') != 'legacy':
        raise ValueError('existing Pages configuration differs; no settings changed')
    if request('/commits/main')['sha'] != sha:
        raise ValueError('main changed before build request')
    request('/pages/builds', 'POST')
    print('Requested rebuild of existing Pages site')
    for _ in range(18):
        time.sleep(10)
        build = request('/pages/builds/latest')
        if build.get('commit') == sha and build.get('status') == 'built':
            print('Verified Pages build for ' + sha)
            return
        if build.get('commit') == sha and build.get('status') == 'errored':
            raise ValueError('Pages build failed')
    raise TimeoutError('Pages build not confirmed within three minutes')

if __name__ == '__main__':
    main()
