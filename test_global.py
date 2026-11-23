import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from playwright.sync_api import sync_playwright

from browser_worker import BrowserFlow
from features import prepare_feature
from global_adapter import remaining_quota
from hunyuan_workbench import Workbench
from lifecycle import tick
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
        flow.page.route('**/studio/creation/role/geo', lambda req: req.fulfill(
            content_type='text/html',
            body='<script>history.replaceState(null, "", "/login")</script><button>Start Using</button>'))
        with self.assertRaisesRegex(ValueError, 'HUMAN_ACTION_REQUIRED'):
            dispatch(flow, {'action': 'run'}, job_id)
        self.assertEqual(self.core.get(job_id)['state'], 'PREPARED')

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
