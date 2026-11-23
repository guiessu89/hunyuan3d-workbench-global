"""Site identity and UI boundaries. Global contracts are fixture-tested, not live-certified."""
from dataclasses import dataclass
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class HunyuanChinaAdapter:
    name: str = 'china'
    origin: str = 'https://3d.hunyuan.tencent.com'

    @property
    def home(self):
        return self.origin + '/'

    def route(self, feature):
        from studio_adapter import ROUTES
        return self.origin + ROUTES[feature][1]

    def validate_url(self, url):
        try:
            value = urlsplit(url)
            valid = (value.scheme == 'https' and value.hostname == urlsplit(self.origin).hostname
                     and value.port in (None, 443) and value.username is None and value.password is None)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('HUMAN_ACTION_REQUIRED: browser is outside the selected official site')
        return url

    def guard(self, page):
        self.validate_url(page.url)
        for frame in page.frames:
            if re.search(r'captcha|challenge', frame.url, re.I):
                raise ValueError('HUMAN_ACTION_REQUIRED: complete verification in the browser')

    def assert_job(self, job):
        # Jobs made before site adapters belong to China, never silently migrate them.
        site = job.get('site', 'china')
        if site != self.name:
            raise ValueError(f'SITE_MISMATCH: job belongs to {site}; use --site {site}')


@dataclass(frozen=True)
class HunyuanGlobalAdapter(HunyuanChinaAdapter):
    name: str = 'global'
    origin: str = 'https://hy3d.tencent.ai'

    @property
    def home(self):
        return self.route('geometry')

    def route(self, feature):
        if feature != 'geometry':
            raise ValueError(f'UNVERIFIED_WORKFLOW: Global {feature} navigation has not been observed')
        return self.origin + '/studio/creation/role/geo'

    def guard(self, page):
        super().guard(page)
        if urlsplit(page.url).path.rstrip('/') == '/login':
            raise ValueError('HUMAN_ACTION_REQUIRED: sign in to Global in the dedicated browser')
        login = page.get_by_role('button', name=re.compile(r'^(log in|sign in|登录)$', re.I))
        if login.filter(visible=True).count():
            raise ValueError('HUMAN_ACTION_REQUIRED: sign in to Global in the dedicated browser')
        if page.get_by_role('dialog').filter(has_text=re.compile(r'verify|captcha|验证', re.I)).filter(visible=True).count():
            raise ValueError('HUMAN_ACTION_REQUIRED: complete verification manually')


def get_site(name=None):
    name = name or os.environ.get('HUNYUAN_WORKBENCH_SITE') or 'global'
    if name not in {'global', 'china'}:
        raise ValueError('Site must be global or china')
    return HunyuanGlobalAdapter() if name == 'global' else HunyuanChinaAdapter()


def browser_options():
    """Allow an installed browser location without weakening its sandbox."""
    path = os.environ.get('HUNYUAN_CHROME_EXECUTABLE')
    options = {'chromium_sandbox': True}
    if path:
        executable = Path(path).expanduser().resolve(strict=True)
        if not executable.is_file():
            raise ValueError('HUNYUAN_CHROME_EXECUTABLE must be a browser executable')
        options['executable_path'] = str(executable)
    else:
        options['channel'] = 'chrome'
    return options
