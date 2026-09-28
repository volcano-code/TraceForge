"""Real Chromium E2E for the native diagnostic workbench, not the React frontend.

Uses throwaway credentials and fixture data; creates no remote PR and invokes no
model. Browser downloads and screenshots contain fixture evidence, never tokens.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    reports = ROOT / 'reports' / 'm1'
    reports.mkdir(parents=True, exist_ok=True)
    browser_path = shutil.which('chromium') or shutil.which('google-chrome')
    if not browser_path:
        raise SystemExit('System Chromium is required; browser test NOT run.')
    checks = []
    browser_errors = []
    with tempfile.TemporaryDirectory(prefix='traceforge-browser-') as tmp:
        data = Path(tmp)
        reviewer, developer = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'),
               'TF_DATABASE_URL': 'sqlite:///' + str(data / 'control.sqlite'), 'TF_DATA_DIR': str(data),
               'TF_DEVELOPER_TOKEN': developer, 'TF_REVIEWER_TOKEN': reviewer,
               'TF_WEBHOOK_SECRET': secrets.token_urlsafe(36)}
        subprocess.run([sys.executable, '-m', 'traceforge.cli', 'init'], cwd=ROOT, env=env,
                       check=True, capture_output=True, timeout=30)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        server_log = (data / 'server.log').open('w')
        worker_log = (data / 'worker.log').open('w')
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'traceforge.api:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT)
        worker = subprocess.Popen([sys.executable, '-m', 'traceforge.worker'], cwd=ROOT, env=env, stdout=worker_log, stderr=subprocess.STDOUT)
        try:
            base = f'http://127.0.0.1:{port}'
            with httpx.Client(base_url=base, timeout=20, trust_env=False) as client:
                for _ in range(100):
                    try:
                        if client.get('/healthz').status_code == 200: break
                    except httpx.TransportError: pass
                    time.sleep(.1)
                else: raise RuntimeError('API did not start')
                headers = {'Authorization': 'Bearer ' + reviewer}
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=browser_path, headless=True,
                                                         args=['--no-sandbox', '--disable-dev-shm-usage'])
                    page = browser.new_page(viewport={'width': 1440, 'height': 1100}, device_scale_factor=1)
                    page.on('pageerror', lambda error: browser_errors.append(str(error)))
                    page.goto(base + '/workbench', wait_until='networkidle')
                    page.locator('#token').fill(reviewer)
                    page.locator('#login-form button').click()
                    expect(page.locator('#authenticated')).to_be_visible()
                    expect(page.locator('#token')).to_have_value('')
                    checks.append('real_browser_login_token_cleared')
                    page.locator('#project').select_option(label='删除后分页越界')
                    page.locator('#task-form button').click()
                    expect(page.locator('#run-status')).to_have_text('等待审阅', timeout=45000)
                    checks.append('browser_create_to_separate_worker_verification')
                    run_id = page.url.split('#')[1]
                    page.locator('#audit-evidence').click()
                    expect(page.locator('#evidence-status')).to_contain_text('10 项证据检查通过')
                    checks.append('browser_evidence_audit')
                    with page.expect_download() as download:
                        page.locator('#export-evidence').click()
                    download.value.save_as(reports / 'browser-evidence-bundle.json')
                    verify = subprocess.run([sys.executable, '-m', 'traceforge.cli', 'verify-bundle',
                                             str(reports / 'browser-evidence-bundle.json')], cwd=ROOT, env=env,
                                            capture_output=True, text=True, timeout=15)
                    assert verify.returncode == 0, verify.stdout + verify.stderr
                    assert json.loads(verify.stdout)['authenticity_proven'] is False
                    checks.append('browser_download_and_offline_bundle_verification')
                    page.locator('#delivery-kind').select_option('SIMULATED_PR')
                    page.locator('#reviewed').check()
                    expect(page.locator('#approve')).to_be_enabled()
                    page.locator('#delivery-kind').select_option('LOCAL_RECEIPT')
                    expect(page.locator('#reviewed')).not_to_be_checked()
                    expect(page.locator('#approve')).to_be_disabled()
                    checks.append('changed_action_clears_review_confirmation')
                    page.locator('#delivery-kind').select_option('SIMULATED_PR')
                    page.locator('#reviewed').check()
                    page.locator('#approve').click()
                    expect(page.locator('#run-status')).to_have_text('已批准')
                    expect(page.locator('#deliver')).to_have_text('提交到独立模拟端')
                    page.locator('#deliver').click()
                    expect(page.locator('#run-status')).to_have_text('模拟交付已核实', timeout=15000)
                    expect(page.locator('#artifact-content')).to_contain_text('"real_github_pr_created": false')
                    checks.append('scoped_approval_and_simulator_receipt_in_browser')
                    detail = client.get(f'/api/v1/runs/{run_id}', headers=headers).json()
                    request = {'approval_id': detail['approval']['id']}
                    replay = client.post(f'/api/v1/runs/{run_id}/deliveries/simulated', headers=headers, json=request)
                    assert replay.status_code == 200 and replay.json()['id'] == detail['operation']['id']
                    checks.append('http_duplicate_submission_returns_same_operation')
                    assert client.post(f'/api/v1/runs/{run_id}/deliveries/pr', headers=headers, json=request).status_code == 503
                    checks.append('live_github_stays_disabled')
                    page.screenshot(path=str(reports / 'workbench-desktop.png'), full_page=True)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.wait_for_timeout(200)
                    overflow = page.evaluate('document.documentElement.scrollWidth > window.innerWidth + 1')
                    assert not overflow, 'Mobile layout horizontally overflows'
                    page.screenshot(path=str(reports / 'workbench-mobile.png'), full_page=True)
                    checks.append('mobile_layout_no_horizontal_overflow')
                    assert not browser_errors, browser_errors
                    checks.append('no_uncaught_browser_javascript_errors')
                    browser_version = browser.version
                    browser.close()
        except Exception:
            # No trace recordings: they can contain authorization headers.
            (reports / 'browser-failure.log').write_text('Browser E2E failed; inspect script output. No tokens are exported.\n')
            raise
        finally:
            for process in (worker, server):
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            worker_log.close(); server_log.close()
    result = {'passed': True, 'tested_frontend': 'native diagnostic workbench', 'react_build_tested': False,
              'browser': browser_version, 'check_count': len(checks), 'checks': checks,
              'real_llm_called': False, 'real_github_pr_created': False, 'page_errors': browser_errors}
    (reports / 'browser-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
