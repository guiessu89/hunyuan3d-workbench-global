import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from playwright.sync_api import sync_playwright

from browser_worker import BrowserFlow, GlobalAuthPause, atomic_json, enqueue, poll, resolve_job_flow
from features import prepare_feature
from global_adapter import remaining_quota
from hunyuan_workbench import Workbench
from lifecycle import tick, watch_tick
from mcp_config import NAME, update_claude
from site_adapters import get_site
from studio_adapter import dispatch
import test_workbench as fixtures


class GlobalConfigurationTests(unittest.TestCase):
    def test_origin_and_observed_login_redirect(self):
        site = get_site('global')
        for url in ('http://hy3d.tencent.ai/', 'https://hy3d.tencent.ai.bad.test/',
                    'https://hy3d.tencent.ai:8080/', 'https://user@hy3d.tencent.ai/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                site.validate_url(url)
        self.assertEqual(site.validate_url(site.home), site.home)
        with self.assertRaisesRegex(ValueError, 'SITE_MISMATCH'):
            site.assert_job({'id': 'legacy'})

    def test_quota_requires_one_explicit_remaining_count(self):
        self.assertEqual(remaining_quota('Remaining generations today: 8 / 99'), 8)
        self.assertEqual(remaining_quota('0 credits remaining'), 0)
        self.assertIsNone(remaining_quota('Up to 99 generations per day'))
        self.assertIsNone(remaining_quota('Remaining credits: 3\n4 generations remaining'))

    def test_cli_selects_site_at_normal_entrypoint(self):
        with tempfile.TemporaryDirectory() as root:
            for args, expected in (([], 'global'), (['--site', 'china'], 'china')):
                output = subprocess.check_output(
                    [sys.executable, '-m', 'hunyuan_workbench', '--root', root, *args, 'capabilities'],
                    text=True,
                )
                self.assertEqual(json.loads(output)['site'], expected)

    def test_claude_registration_preserves_existing_servers_and_backs_up(self):
        with tempfile.TemporaryDirectory(prefix='MCP Config ') as root:
            path = Path(root) / 'Claude Desktop' / 'claude_desktop_config.json'
            python = Path(root) / 'Global Workbench' / 'python'
            saved = {'mcpServers': {'unity': {'command': 'unity'}, 'image': {'command': 'image'}},
                     'preferences': {'theme': 'system'}}
            path.parent.mkdir()
            path.write_text(json.dumps(saved), encoding='utf-8')
            update_claude(path, python)
            configured = json.loads(path.read_text(encoding='utf-8'))
            entry = configured['mcpServers'].pop(NAME)
            self.assertEqual(entry['command'], str(python))
            self.assertEqual(entry['args'][-3:], ['--site', 'global', 'mcp'])
            self.assertEqual(configured, saved)
            backup, = path.parent.glob('*.bak')
            self.assertEqual(json.loads(backup.read_text(encoding='utf-8')), saved)
            update_claude(path, python, remove=True)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), saved)


class GlobalQueueTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.worker = dict(site='global', pid=123, instance_id='first', state='IDLE')
        self.update_worker()

    def update_worker(self, **changes):
        self.worker.update(heartbeat=time.time(), **changes)
        atomic_json(self.root / 'browser-status.json', self.worker)

    def enqueue_inspection(self):
        return enqueue(self.root, 'inspect', site='global')['request_id']

    def test_poll_reports_stopped_and_stale_worker_for_pending_requests(self):
        request_id = self.enqueue_inspection()
        self.assertEqual(poll(self.root, request_id)['state'], 'QUEUED')
        self.update_worker(state='STOPPED')
        self.assertEqual(poll(self.root, request_id)['state'], 'WORKER_UNRESPONSIVE')
        self.worker.update(state='IDLE', heartbeat=time.time() - 60)
        atomic_json(self.root / 'browser-status.json', self.worker)
        self.assertEqual(poll(self.root, request_id)['state'], 'WORKER_UNRESPONSIVE')

    def test_restarted_worker_rejects_pending_request_even_with_same_pid(self):
        old = self.enqueue_inspection()
        self.update_worker(instance_id='second')
        self.assertEqual(poll(self.root, old)['state'], 'ERROR')
        self.assertEqual(poll(self.root, self.enqueue_inspection())['state'], 'QUEUED')

    def test_completed_result_survives_worker_shutdown(self):
        request_id = self.enqueue_inspection()
        queue = self.root / 'queue'
        (queue / (request_id + '.json')).rename(queue / (request_id + '.running'))
        self.assertEqual(poll(self.root, request_id)['state'], 'RUNNING')
        result = dict(state='COMPLETE', request_id=request_id, result={'ok': True})
        atomic_json(queue / (request_id + '.result.json'), result)
        self.update_worker(state='STOPPED')
        self.assertEqual(poll(self.root, request_id), result)


class GlobalStudioFixture(unittest.TestCase):
    setUp = fixtures.LedgerTests.setUp
    tearDown = fixtures.LedgerTests.tearDown

    @classmethod
    def setUpClass(cls):
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        cls.browser = fixtures.launch_fixture_browser(playwright)
        cls.addClassCleanup(cls.browser.close)

    def fixture(self, mode):
        self.core = Workbench(self.root / 'global', site='global')
        spec = dict(feature='geometry', name='Test prop', mode=mode)
        if mode == 'single':
            spec['image'] = self.views['front']
        else:
            spec['views'] = self.views
        job = prepare_feature(self.core, spec)
        self.assertEqual(prepare_feature(self.core, spec)['id'], job['id'])
        glb = base64.b64encode(fixtures.LedgerTests.glb(self).read_bytes()).decode('ascii')
        fields = ['Front'] if mode == 'single' else ['Front', 'Right', 'Back']
        inputs = ''.join(f'<label>{v}<input aria-label="{v}" type=file accept=".png"><img></label>'
                         for v in fields)
        html = f"""
        <button>Single Image</button><button>Multi-view</button>
        {inputs}
        <label><input name=faces type=radio>50k</label>
        <p id=quota>Remaining generations: 0</p>
        <button id=generate>Generate</button>
        <button onclick="document.querySelector('#export').hidden=false">Download</button>
        <a id=export hidden download="prop.glb">GLB</a>
        <div id=assets-container style="min-height: 20px"></div>
        <script>
        window.submits = 0;
        document.querySelector('#export').href = URL.createObjectURL(new Blob([
          Uint8Array.from(atob('{glb}'), c => c.charCodeAt(0))
        ], {{type: 'model/gltf-binary'}}));
        for (const input of document.querySelectorAll('input[type=file]'))
          input.onchange = () => input.nextElementSibling.src = URL.createObjectURL(input.files[0]);
        document.querySelector('#generate').onclick = () => {{
          window.submits++;
          document.querySelector('#assets-container').insertAdjacentHTML('beforeend',
              '<div>Queued <span class="bg-gradient-to-r"></span><img></div>');
        }};
        </script>"""
        context = self.browser.new_context(service_workers='block')
        self.addCleanup(context.close)
        context.route('**/*', lambda req: req.fulfill(body=html, content_type='text/html'))
        page = context.new_page()
        return BrowserFlow(page, self.core), job['id']

    def test_single_image_prepare_quota_submit_once_and_archive(self):
        flow, job_id = self.fixture('single')
        page = flow.page
        self.assertEqual(dispatch(flow, {'action': 'run'}, job_id)['state'], 'READY')
        form = flow.inspect()
        self.assertTrue(form['geometry_controls_detected'])
        self.assertEqual(form['prepared_job_id'], job_id)
        self.assertEqual(form['remaining_quota'], 0)
        self.assertEqual(form['file_inputs'][0]['files'], 1)
        self.assertEqual(page.evaluate('window.submits'), 0)
        with self.assertRaisesRegex(ValueError, 'QUOTA_UNAVAILABLE'):
            dispatch(flow, {'action': 'submit'}, job_id)
        page.locator('#quota').evaluate("e => e.textContent = 'Remaining generations: 1'")
        self.assertEqual(dispatch(flow, {'action': 'submit_and_watch'}, job_id)['state'], 'RUNNING')
        with self.assertRaises(ValueError):
            dispatch(flow, {'action': 'submit'}, job_id)
        self.assertEqual(page.evaluate('window.submits'), 1)
        page.locator('#assets-container > div').evaluate(
            "e => {e.firstChild.textContent = 'Complete'; e.querySelector('img').src = '/prop.png'}")
        self.assertEqual(tick(flow, job_id)['state'], 'SUCCEEDED')
        result = dispatch(flow, {'action': 'download_job'}, job_id)
        self.assertEqual(result['state'], 'DOWNLOADED')
        self.assertEqual(result['format'], 'glb')
        self.assertTrue(Path(result['archive']['path']).is_file())
        self.assertTrue(dispatch(flow, {'action': 'download_job'}, job_id)['cached'])

    def test_multiview_prepare_and_changed_form_stop_before_click(self):
        flow, job_id = self.fixture('multiview')
        with self.assertRaisesRegex(ValueError, 'separate form'):
            dispatch(flow, {'action': 'run', 'submit': True}, job_id)
        self.assertEqual(dispatch(flow, {'action': 'run'}, job_id)['state'], 'READY')
        self.assertEqual(flow.page.locator('input[type=file]').evaluate_all(
            'es => es.map(e => e.files.length)'), [1, 1, 1])
        flow.page.get_by_role('radio', name='50k').evaluate('e => e.checked = false')
        with self.assertRaisesRegex(ValueError, 'form changed'):
            dispatch(flow, {'action': 'submit'}, job_id)
        self.assertEqual(flow.page.evaluate('window.submits'), 0)

    def test_login_route_blocks_before_upload(self):
        flow, job_id = self.fixture('single')
        requests = []

        def show_login(request):
            requests.append(request.request.url)
            request.fulfill(content_type='text/html',
                            body='<script>history.replaceState(null, "", "/login")</script><button>Start Using</button>')

        flow.page.route('**/studio/creation/role/geo', show_login)
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'HUMAN_ACTION_REQUIRED'):
                dispatch(flow, {'action': 'run'}, job_id)
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.core.get(job_id)['state'], 'PREPARED')

    def test_global_start_waits_for_manual_navigation_without_contacting_tencent(self):
        flow, job_id = self.fixture('single')
        states = []
        flow.auth_pause = GlobalAuthPause(lambda state, detail='': states.append(state))
        navigations = []
        flow.page.on('request', lambda req: navigations.append(req.url) if req.is_navigation_request() else None)

        flow.open_start_page()
        with self.assertRaisesRegex(ValueError, r'HUMAN_ACTION_REQUIRED: Open https://hy3d.tencent.ai/ yourself'):
            flow.auth_pause.check(flow, inspecting=True)
        self.assertEqual(navigations, [])
        self.assertEqual(states, ['HUMAN_ACTION_REQUIRED'])
        self.assertEqual(self.core.get(job_id)['state'], 'PREPARED')

        flow.page.goto(flow.core.site.home)  # Simulate the user's navigation.
        with self.assertRaisesRegex(ValueError, 'HUMAN_ACTION_REQUIRED'):
            flow.auth_pause.check(flow)
        flow.auth_pause.check(flow, inspecting=True)
        self.assertEqual(navigations, [flow.core.site.home])
        self.assertTrue(flow.inspect()['geometry_controls_detected'])
        self.assertEqual(states[-1], 'IDLE')

    def test_resume_waits_for_geometry_form_even_when_studio_url_matches(self):
        flow, job_id = self.fixture('single')
        flow.auth_pause = GlobalAuthPause(flow.status)
        flow.open_start_page()
        page = flow.page
        page.goto(flow.core.site.home)
        page.set_content('<p role="status">Loading Studio</p>')
        requests = []
        page.on('request', lambda request: requests.append(request.url))
        with self.assertRaisesRegex(ValueError, 'Wait for Geometry Generation to show its image form'):
            flow.auth_pause.check(flow, inspecting=True)
        with self.assertRaisesRegex(ValueError, 'HUMAN_ACTION_REQUIRED'):
            resolve_job_flow(flow, {}, job_id, preparing=True)
        self.assertEqual(len(page.context.pages), 1)
        self.assertEqual(requests, [])
        self.assertEqual(self.core.get(job_id)['state'], 'PREPARED')
        page.set_content('<button>Single Image</button><button disabled>Generate</button>')
        flow.auth_pause.check(flow, inspecting=True)
        self.assertIsNone(flow.auth_pause.error)

    def test_job_inspection_does_not_open_a_tab_and_preparation_navigates_once(self):
        home, job_id = self.fixture('single')
        home.page.goto(home.core.site.home)
        context = home.page.context
        navigations = []
        context.on('request', lambda request: navigations.append(request.url) if request.is_navigation_request() else None)
        tabs = {}
        with self.assertRaisesRegex(ValueError, 'No open Studio tab'):
            resolve_job_flow(home, tabs, job_id, inspecting=True)
        self.assertEqual(len(context.pages), 1)
        target = resolve_job_flow(home, tabs, job_id, preparing=True)
        self.assertEqual(navigations, [])
        self.assertEqual(dispatch(target, {'action': 'run'}, job_id)['state'], 'READY')
        self.assertEqual(navigations, [home.core.site.home])
        self.assertIs(resolve_job_flow(home, tabs, job_id, inspecting=True), target)
        self.assertTrue(target.inspect()['geometry_controls_detected'])
        self.assertEqual(navigations, [home.core.site.home])
        self.assertEqual(target.page.evaluate('window.submits'), 0)

    def test_global_start_preserves_a_restored_rate_limit_page_without_reloading(self):
        flow, _ = self.fixture('single')
        flow.auth_pause = GlobalAuthPause(flow.status)
        requests = []

        def show_rate_limit(route):
            requests.append(route.request.url)
            route.fulfill(content_type='text/html', body='<p>Operation too often. Please retry later.</p>')

        flow.page.route('**/login', show_rate_limit)
        login = flow.core.site.origin + '/login'
        flow.page.goto(login)
        flow.open_start_page()
        self.assertEqual(flow.auth_pause.error.code, 'AUTH_RATE_LIMITED')
        self.assertEqual(flow.page.url, login)
        self.assertEqual(requests, [login])

    def test_captcha_rate_limit_pauses_until_manual_resolution_and_inspection(self):
        flow, job_id = self.fixture('single')
        states = []
        pause = GlobalAuthPause(lambda state, detail='': states.append(state))
        flow.auth_pause = pause
        page = flow.page
        page.route('**/captcha', lambda req: req.fulfill(
            content_type='text/html', body='<p>Operation too often. Please retry later.</p>'))
        page.goto(flow.core.site.home)
        page.locator('body').evaluate(
            """e => e.insertAdjacentHTML('beforeend','<iframe title="Tencent CAPTCHA" src="/captcha"></iframe>')""")
        page.frame_locator('iframe').get_by_text('Operation too often. Please retry later.').wait_for()
        before = self.core.get(job_id)
        with self.assertRaisesRegex(ValueError, 'AUTH_RATE_LIMITED'):
            pause.check(flow)
        with self.assertRaisesRegex(ValueError, 'AUTH_RATE_LIMITED'):
            pause.check(flow, inspecting=True)
        self.assertEqual(states[-1], 'AUTH_RATE_LIMITED')
        self.assertFalse(page.is_closed())
        self.assertEqual(self.core.get(job_id), before)
        page.locator('iframe').evaluate('e => e.remove()')  # Simulate completion outside the worker.
        with self.assertRaisesRegex(ValueError, 'AUTH_RATE_LIMITED'):
            pause.check(flow)
        pause.check(flow, inspecting=True)
        self.assertIsNone(pause.error)
        self.assertEqual(states[-1], 'IDLE')

    def test_rate_limit_http_status_without_ui_message(self):
        flow, job_id = self.fixture('single')
        flow.page.route('**/studio/creation/role/geo', lambda req: req.fulfill(
            status=429, content_type='text/html', body='<p>Please wait.</p>'))
        flow.page.goto(flow.core.site.home)
        with self.assertRaisesRegex(ValueError, 'AUTH_RATE_LIMITED'):
            flow.inspect()
        self.assertEqual(self.core.get(job_id)['state'], 'PREPARED')
        flow.page.unroute('**/studio/creation/role/geo')
        flow.page.goto(flow.core.site.home)
        self.assertTrue(flow.inspect()['geometry_controls_detected'])

    def test_verification_and_auth_failure_are_distinct_from_rate_limits(self):
        flow, _ = self.fixture('single')
        flow.page.goto(flow.core.site.home)
        for message in ('Security verification', 'Login failed', 'Your session has expired'):
            with self.subTest(message=message):
                flow.page.set_content(f'<div role="alert">{message}</div>')
                with self.assertRaisesRegex(ValueError, 'HUMAN_ACTION_REQUIRED'):
                    flow.inspect()

    def test_visible_challenge_frame_requires_manual_action_but_hidden_frame_does_not(self):
        flow, _ = self.fixture('single')
        page = flow.page
        page.goto(flow.core.site.home)
        page.locator('body').evaluate(
            """e => e.insertAdjacentHTML('beforeend','<iframe title="Tencent CAPTCHA" hidden></iframe>')""")
        self.assertTrue(flow.inspect()['geometry_controls_detected'])
        page.locator('iframe').evaluate('e => e.hidden = false')
        with self.assertRaisesRegex(ValueError, 'HUMAN_ACTION_REQUIRED: Complete Tencent verification'):
            flow.inspect()

    def test_generic_verification_frame_detects_slider_and_rate_limit_without_navigation(self):
        flow, job_id = self.fixture('single')
        page = flow.page
        page.goto(flow.core.site.home)
        flow.auth_pause = GlobalAuthPause(flow.status)
        requests = []
        page.on('request', lambda request: requests.append(request.url))
        page.locator('body').evaluate("""body => {
            const frame = document.createElement('iframe');
            frame.title = 'Verification';
            frame.srcdoc = '<h2>Slide to complete the puzzle</h2>';
            body.append(frame);
        }""")
        challenge = page.frame_locator('iframe')
        challenge.get_by_text('Slide to complete the puzzle', exact=True).wait_for()
        with self.assertRaisesRegex(ValueError, 'HUMAN_ACTION_REQUIRED: Complete Tencent verification'):
            flow.inspect()
        challenge.locator('body').evaluate(
            """body => body.insertAdjacentHTML('beforeend', '<p>Operation too often. Please retry later.</p>')""")
        with self.assertRaisesRegex(ValueError, 'AUTH_RATE_LIMITED'):
            flow.auth_pause.check(flow, inspecting=True)
        self.assertEqual(flow.auth_pause.error.code, 'AUTH_RATE_LIMITED')
        self.assertEqual(self.core.get(job_id)['state'], 'PREPARED')
        self.assertEqual(requests, [])

    def test_auth_block_leaves_running_job_and_watch_unchanged(self):
        flow, job_id = self.fixture('single')
        dispatch(flow, {'action': 'run'}, job_id)
        flow.page.locator('#quota').evaluate("e => e.textContent = 'Remaining generations: 1'")
        self.assertEqual(dispatch(flow, {'action': 'submit'}, job_id)['state'], 'RUNNING')
        flow.auth_pause = GlobalAuthPause(lambda *args: None)
        flow.page.set_content('<div role="alert">Operation too often. Please retry later.</div>')
        watch = self.core.root / 'watches' / f'{job_id}.json'
        job, watch_record = self.core.get(job_id), watch.read_bytes()
        watch_tick(flow)
        self.assertEqual(flow.auth_pause.error.code, 'AUTH_RATE_LIMITED')
        self.assertEqual(self.core.get(job_id), job)
        self.assertEqual(watch.read_bytes(), watch_record)

    def test_unrecognized_new_card_never_allows_another_click(self):
        flow, job_id = self.fixture('single')
        dispatch(flow, {'action': 'run'}, job_id)
        page = flow.page
        page.locator('#quota').evaluate("e => e.textContent = 'Remaining generations: 1'")
        page.locator('#generate').evaluate("""button => {
            const submit = button.onclick;
            button.onclick = () => {
                submit();
                document.querySelector('#assets-container > div').firstChild.textContent = 'Unknown';
            };
        }""")
        with self.assertRaisesRegex(ValueError, 'no confirmed generation indicator'):
            dispatch(flow, {'action': 'submit'}, job_id)
        self.assertEqual(self.core.get(job_id)['state'], 'UNCERTAIN')
        with self.assertRaises(ValueError):
            dispatch(flow, {'action': 'submit'}, job_id)
        self.assertEqual(page.evaluate('window.submits'), 1)
