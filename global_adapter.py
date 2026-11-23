"""Experimental Global geometry UI. Unknown states stop before any generation click."""
import re
from urllib.parse import urlsplit

from feature_adapter import form_signature, upload_image
from lifecycle import CARD, retain_new_card, watch_config

VIEWS = {
    'front': 'Front', 'back': 'Back', 'left': 'Left', 'right': 'Right',
    'top': 'Top', 'bottom': 'Bottom', 'left_front': 'Front Left', 'right_front': 'Front Right',
}
FACES = {50000: '50k', 500000: '500k', 1000000: '1M', 1500000: '1.5M'}
QUOTA = re.compile(r'^(?:Remaining (?:generations|credits)(?: today)?\s*:\s*(\d+)(?:\s*/\s*\d+)?|(\d+)\s+(?:generations|credits) remaining(?: today)?)$', re.I)


def remaining_quota(text):
    values = {int(match.group(1) or match.group(2)) for line in text.splitlines()
              if (match := QUOTA.fullmatch(line.strip()))}
    return next(iter(values)) if len(values) == 1 else None


def inspect_geometry(flow):
    page = flow.page
    route = urlsplit(page.url).path.rstrip('/')
    expected_route = urlsplit(flow.core.site.route('geometry')).path
    modes = [label for label in ('Single Image', 'Multi-view')
             if page.get_by_text(label, exact=True).filter(visible=True).count() == 1]
    generate = page.get_by_role('button', name='Generate', exact=True).filter(visible=True)
    generate_count = generate.count()
    return {
        'url': flow.core.site.origin + route,
        'geometry_controls_detected': route == expected_route and bool(modes) and generate_count == 1,
        'image_modes': modes,
        'face_count_options': [value for value, label in FACES.items()
                               if page.get_by_role('radio', name=label, exact=True).filter(visible=True).count() == 1],
        'prepared_job_id': getattr(flow, 'prepared_job_id', None),
        'remaining_quota': remaining_quota(page.locator('body').inner_text(timeout=5000)),
        'generate_enabled': generate_count == 1 and generate.is_enabled(),
        'file_inputs': page.locator('input[type=file]').evaluate_all(
            "es => es.map(e => ({accept:e.accept, label:e.getAttribute('aria-label'), files:e.files?.length}))"
        ),
    }


def unique_visible(locator, description):
    visible = locator.filter(visible=True)
    visible.first.wait_for(state='visible', timeout=5000)
    if visible.count() != 1:
        raise ValueError(f'UNVERIFIED_UI: expected one visible {description}')
    return visible


def generate_button(page):
    button = unique_visible(page.get_by_role('button', name='Generate', exact=True), 'Generate button')
    if not button.is_enabled():
        raise ValueError('Generate is disabled. Review the visible form and quota.')
    return button


def prepare(flow, job):
    page, job_id = flow.page, job['id']
    flow.prepared_job_id = None
    flow.core.site.assert_job(job)
    if job.get('feature') != 'geometry' or job.get('mode') not in {'single', 'multiview'}:
        raise ValueError('UNVERIFIED_WORKFLOW: Global supports experimental image geometry only')
    if job['state'] not in {'PREPARED', 'UPLOADING', 'READY'}:
        raise ValueError('Already submitted or uncertain. Inspect the existing task.')
    page.goto(flow.core.site.route('geometry'), wait_until='domcontentloaded', timeout=30000)
    flow.guard()
    mode = 'Single Image' if job['mode'] == 'single' else 'Multi-view'
    unique_visible(page.get_by_text(mode, exact=True), mode + ' control').click(timeout=5000)
    if job['state'] != 'UPLOADING':
        flow.core.transition(job_id, 'UPLOADING', 'Preparing Global geometry form', expected=job['state'])
    images = page.locator('input[type=file][accept*=".png" i]')
    if job['mode'] == 'single':
        if images.count() != 1:
            raise ValueError('UNVERIFIED_UI: no unique single-image file input')
        upload_image(flow, images, job['views']['front'])
    else:
        fields = []
        for view, info in job['views'].items():
            field = images.and_(page.get_by_label(VIEWS[view], exact=True))
            if field.count() != 1:
                raise ValueError('UNVERIFIED_UI: no unique file input for ' + view)
            fields.append((field, info))
        for field, info in fields:
            upload_image(flow, field, info)
    flow.guard()
    face = unique_visible(page.get_by_role('radio', name=FACES[job['face_count']], exact=True), 'face-count radio')
    face.check(timeout=5000)
    if not face.is_checked():
        raise ValueError('Face-count selection could not be verified')
    generate_button(page)
    signature = form_signature(page)
    flow.core.transition(job_id, 'READY', 'Verified Global geometry input previews and face count', expected='UPLOADING')
    flow.prepared_job_id, flow.prepared_signature = job_id, signature
    return {'job_id': job_id, 'state': 'READY', 'submitted': False,
            'mode': job['mode'], 'views': list(job['views']), 'face_count': job['face_count']}


def submit(flow, job_id):
    job = flow.core.get(job_id)
    page = flow.page
    flow.guard()
    flow.core.site.assert_job(job)
    if urlsplit(page.url).path.rstrip('/') != urlsplit(flow.core.site.route('geometry')).path:
        raise ValueError('Prepared Global geometry page is no longer open')
    if job['state'] != 'READY' or getattr(flow, 'prepared_job_id', None) != job_id:
        raise ValueError('Reprepare this job if the browser restarted. Never resubmit an uncertain job.')
    if form_signature(page) != flow.prepared_signature:
        raise ValueError('Prepared form changed. Reprepare and inspect it before submitting.')
    quota = remaining_quota(page.locator('body').inner_text(timeout=5000))
    if quota is None or quota == 0:
        raise ValueError('QUOTA_UNAVAILABLE: remaining generations are missing, ambiguous, or zero')
    button = generate_button(page)
    container = page.locator('#assets-container').filter(visible=True)
    if container.count() != 1:
        raise ValueError('UNVERIFIED_UI: no unique visible asset panel to track submission')
    before = page.locator(CARD).element_handles()
    flow.core.transition(job_id, 'SUBMITTING', 'Reserved one click with confirmed positive visible quota', expected='READY')
    try:
        button.click(timeout=5000)
        result = retain_new_card(flow, job_id, before)
    except Exception:
        if flow.core.get(job_id)['state'] == 'SUBMITTING':
            flow.core.transition(job_id, 'UNCERTAIN', 'Could not conclusively identify the submitted asset', expected='SUBMITTING')
        raise
    result['watch'] = watch_config(flow, job_id)
    return result
