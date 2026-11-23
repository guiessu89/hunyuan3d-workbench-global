"""Site identity and UI boundaries. Global contracts are fixture-tested, not live-certified."""
from dataclasses import dataclass
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError


class GlobalAuthError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code}: {message}')


RATE_LIMIT = re.compile(
    r'operation too often|too many (?:requests|(?:login |sign-in |verification )?attempts)'
    r'|操作过于频繁|操作太频繁|请求过于频繁', re.I
)
AUTH_FAILURE = re.compile(
    r'\b(?:(?:log[ -]?in|sign[ -]?in|authentication|verification) failed'
    r'|(?:unable|failed) to (?:log|sign) in|(?:session|login) (?:has )?expired)\b'
    r'|登录失败|登录已过期|验证失败', re.I
)
CHALLENGE = re.compile(r'captcha|challenge', re.I)
VERIFY = re.compile(r'captcha|verify (?:that )?you(?: are|.re) human|security verification'
                    r'|slide to complete the puzzle|complete (?:the )?verification|安全验证|人机验证', re.I)


def has_visible_text(surface, pattern):
    return surface.get_by_text(pattern).filter(visible=True).count() > 0


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

    def guard(self, page, document_status=None):
        try:
            self.validate_url(page.url)
        except ValueError as error:
            raise GlobalAuthError('HUMAN_ACTION_REQUIRED',
                                  'Return to the official Global Studio in the dedicated browser.') from error
        rate_limited = document_status == 429 or has_visible_text(page, RATE_LIMIT)
        requires_verification = has_visible_text(page, VERIFY)
        for frame in page.frames:
            if rate_limited or frame == page.main_frame:
                continue
            try:
                element = frame.frame_element()
                if not element.is_visible():
                    continue
                # Some verification frames use a generic title and URL.
                rate_limited = has_visible_text(frame, RATE_LIMIT)
                url = urlsplit(frame.url)
                requires_verification = (requires_verification
                                         or CHALLENGE.search(f'{url.netloc}{url.path}')
                                         or CHALLENGE.search(element.get_attribute('title') or '')
                                         or has_visible_text(frame, VERIFY))
            except PlaywrightError:
                if not frame.is_detached():
                    raise  # Fail closed if the frame could not be inspected.

        if rate_limited:
            raise GlobalAuthError('AUTH_RATE_LIMITED',
                                  'Tencent is limiting attempts. Wait until Tencent allows another attempt, '
                                  'then complete verification manually in the same browser.')
        if requires_verification:
            raise GlobalAuthError('HUMAN_ACTION_REQUIRED',
                                  'Complete Tencent verification manually in the dedicated browser.')
        if document_status in (401, 403) or has_visible_text(page, AUTH_FAILURE):
            raise GlobalAuthError('HUMAN_ACTION_REQUIRED',
                                  'Tencent authentication failed or expired. Sign in manually in the same browser.')
        login = page.get_by_role('button', name=re.compile(r'^(log in|sign in|登录)$', re.I))
        if urlsplit(page.url).path.rstrip('/') == '/login' or login.filter(visible=True).count():
            raise GlobalAuthError('HUMAN_ACTION_REQUIRED', 'Sign in to Global in the dedicated browser.')


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
