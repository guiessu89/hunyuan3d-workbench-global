"""Local persistent Playwright runner, explicitly requested for fast web automation.

Uses a dedicated Chrome profile and visible official UI only. No cookies are
exported and no private web endpoints are called. IPC is local files, no port.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
import threading
from urllib.parse import urlsplit

from hunyuan_workbench import Workbench, FACE_LABELS, digest, dump
from site_adapters import GlobalAuthError, browser_options, get_site

HOME = "https://3d.hunyuan.tencent.com/"
HEARTBEAT_TIMEOUT = 15


def read_worker_status(root):
    try:
        return json.loads((Path(root) / "browser-status.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def worker_is_responsive(status):
    return (status.get("state") != "STOPPED"
            and time.time() - status.get("heartbeat", 0) < HEARTBEAT_TIMEOUT)

def atomic_json(path, data):
    temp = path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(dump(data), encoding="utf-8")
    temp.replace(path)

def start(root, site=None):
    adapter = get_site(site)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    status = root / "browser-status.json"
    saved = read_worker_status(root)
    if worker_is_responsive(saved):
        if saved.get("site", "china") != adapter.name:
            raise ValueError("A worker for another site uses this root. Use a separate --root.")
        return saved
    with (root / "browser-worker.log").open("a", encoding="utf-8") as log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(root)],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         env={**os.environ, 'HUNYUAN_WORKBENCH_SITE': adapter.name},
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return {"state": "STARTING", "status_file": str(status), "note": "Dedicated Chrome window; sign in to the same Hunyuan account once."}

def enqueue(root, op, job_id=None, submit=False, text=None, site=None):
    adapter = get_site(site)
    if op not in {"inspect", "run", "stop", "click_text", "hover_text", "research", "probe", "download", "studio"}:
        raise ValueError("Unsupported worker operation")
    job = Workbench(root, site=adapter.name).get(job_id) if job_id else None
    if job is not None:
        adapter.assert_job(job)
    if op == "run":
        if job is None:
            raise ValueError("A job id is required")
        if job["state"] not in {"PREPARED", "UPLOADING", "READY"}:
            raise ValueError("Job is already submitted or uncertain; inspect it instead")
    root = Path(root)
    saved = read_worker_status(root)
    if not worker_is_responsive(saved):
        raise ValueError("Browser worker is not running. Run web-start before enqueueing browser work.")
    if saved.get("site", "china") != adapter.name:
        raise ValueError("Worker belongs to another site. Select its site or use a separate --root.")
    if adapter.name == "global" and not saved.get("instance_id"):
        raise ValueError("Restart the Global browser worker to use this version.")
    queue = root / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    atomic_json(queue / (request_id + ".json"), {"id": request_id, "op": op, "job_id": job_id,
                                                 "submit": bool(submit), "text": text, "site": adapter.name,
                                                 "worker_instance_id": saved.get("instance_id"), "created": time.time()})
    return {"request_id": request_id, "state": "QUEUED", "result_file": str(queue / (request_id + ".result.json"))}

def request_matches_worker(request, status):
    site = request.get("site", "china")
    instance = status.get("instance_id")
    return site == status.get("site", "china") and (
        site != "global" or bool(instance and request.get("worker_instance_id") == instance)
    )


def poll(root, request_id):
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise ValueError("Invalid request id")
    root = Path(root)
    queue = root / "queue"
    result = queue / (request_id + ".result.json")
    # The queue only moves forward, through these successive filenames.
    for suffix, state in ((".result.json", None), (".json", "QUEUED"), (".running", "RUNNING")):
        try:
            record = json.loads((queue / (request_id + suffix)).read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        if state is None:
            return record
        worker = read_worker_status(root)
        if result.is_file():
            return json.loads(result.read_text(encoding="utf-8"))
        if not worker_is_responsive(worker):
            return {"request_id": request_id, "state": "WORKER_UNRESPONSIVE", "worker": worker}
        if not request_matches_worker(record, worker):
            return {"request_id": request_id, "state": "ERROR",
                    "error": "Browser worker or site changed. Inspect the job before making a new request."}
        response = {"request_id": request_id, "state": state}
        if state == "RUNNING":
            response["worker"] = worker
        return response
    raise ValueError("Unknown request id")

class GlobalAuthPause:
    """Keep the blocked tab open and resume only after an explicit inspection."""

    def __init__(self, status):
        self.status = status
        self.error = self.flow = None

    def block(self, flow, error):
        self.error, self.flow = error, flow
        self.status(error.code, str(error))

    def check(self, home, *, inspecting=False):
        if self.error:
            if not inspecting:
                raise self.error
            blocked = self.flow if not self.flow.page.is_closed() else home
            blocked.guard()
            if urlsplit(blocked.page.url).path.rstrip('/') != urlsplit(home.core.site.home).path:
                raise self.error
            if blocked is not home:
                home.guard()
            self.error = self.flow = None
            self.status('IDLE')
        else:
            home.guard()


class BrowserFlow:
    def __init__(self, page, core, status_callback=lambda *args: None, auth_pause=None):
        self.page, self.core, self.status = page, core, status_callback
        self.auth_pause = auth_pause
        self.document_status = None
        if page is not None and core.site.name == 'global':
            page.on('response', self.record_navigation_status)

    def record_navigation_status(self, response):
        if response.request.is_navigation_request() and response.frame == self.page.main_frame:
            self.document_status = response.status

    def guard(self):
        if self.core.site.name != 'global':
            self.core.site.guard(self.page)
            return
        try:
            self.core.site.guard(self.page, self.document_status)
        except GlobalAuthError as error:
            if self.auth_pause is not None:
                self.auth_pause.block(self, error)
            raise

    def navigate(self, url, *, timeout):
        is_global = self.core.site.name == 'global'
        try:
            self.page.goto(url, wait_until='domcontentloaded', timeout=timeout)
        except Exception:
            if is_global and not self.page.is_closed() and self.page.url != 'about:blank':
                self.guard()
            raise
        if is_global:
            self.guard()

    def inspect(self):
        self.guard()
        safe_url = urlsplit(self.page.url)
        if self.core.site.name == 'global':
            from global_adapter import inspect_geometry
            return inspect_geometry(self)
        self.page.screenshot(path=str(self.core.root / "browser-current.png"))
        return {"url": safe_url.scheme + "://" + safe_url.netloc + safe_url.path, "title": self.page.title(),
                "body": self.page.locator("body").inner_text(timeout=5000)[:18000],
                "buttons": self.page.get_by_role("button").all_text_contents(),
                "links": self.page.locator("a[href]").evaluate_all("es=>es.map(e=>({text:e.innerText,href:(()=>{try{const u=new URL(e.href);return u.origin+u.pathname}catch{return ''}})()}))"),
                "screenshot": str(self.core.root / "browser-current.png"),
                "uploads": self.page.locator(".hy-upload-card").evaluate_all("es => es.map(e => ({class:e.className,text:e.textContent,images:[...e.querySelectorAll('img')].map(i=>i.getAttribute('src'))}))")}

    def open_panel(self):
        self.guard()
        if self.page.get_by_role("button", name="登录", exact=True).is_visible():
            raise ValueError("HUMAN_ACTION_REQUIRED: sign in to your existing Hunyuan account")
        start_button = self.page.get_by_text("立即开始", exact=True)
        if start_button.count() == 1 and start_button.is_visible():
            start_button.click()
        image_radio = self.page.get_by_role("radio", name="图生3D", exact=True)
        if image_radio.count() and not image_radio.is_checked():
            image_radio.check()
        multi = self.page.get_by_text("多张图片", exact=True)
        multi.wait_for(state="visible", timeout=12000)
        multi.click()
        cards = self.page.locator(".hy-upload-card--front")
        if not cards.is_visible():
            self.page.locator("button.hy-multiple-views-upload-v2").click()
        cards.wait_for(state="visible", timeout=8000)

    def run(self, job_id, submit=False):
        start_time = time.monotonic()
        job = self.core.get(job_id)
        if job["state"] not in {"PREPARED", "UPLOADING", "READY"}:
            raise ValueError("Do not resubmit an existing or uncertain task")
        self.open_panel()
        # Refuse a shared form containing unrelated views. Replace all requested views.
        extra = self.page.locator(".hy-upload-card.isSuccess").evaluate_all("es => es.map(e=>[...e.classList].find(c=>c.startsWith('hy-upload-card--')).replace('hy-upload-card--','').replaceAll('-','_'))")
        if set(extra) - set(job["views"]):
            raise ValueError("Unexpected populated view slots; clear them in Chrome before running this job")
        if job["state"] != "UPLOADING":
            self.core.transition(job_id, "UPLOADING", "Local Playwright upload started")
        uploaded = {}
        for view, info in job["views"].items():
            self.guard()
            if digest(Path(info["path"])) != info["sha256"]:
                raise ValueError("Prepared reference was changed")
            self.status("UPLOADING", f"{job['name']}: {view}")
            card = self.page.locator(".hy-upload-card--" + view.replace("_", "-"))
            card.locator('input[type="file"]').set_input_files(info["path"])
            self.page.wait_for_function("selector => {const e=document.querySelector(selector); const i=e?.querySelector('img'); return e?.classList.contains('isSuccess') && i?.complete && i.naturalWidth>0 && /resourceId=/.test(i.src)}", arg=".hy-upload-card--" + view.replace("_", "-"), timeout=45000)
            uploaded[view] = card.locator("img").first.get_attribute("src")
        # Outside click closes this popover without relying on an off-screen close icon.
        self.page.get_by_text("模型面数", exact=True).click()
        self.page.locator(".hy-upload-card--front").wait_for(state="hidden", timeout=5000)
        if not self.page.get_by_text("3D生成 - V3.1", exact=True).is_visible():
            raise ValueError("Select model V3.1 in Chrome before continuing")
        face = self.page.get_by_text(FACE_LABELS[job["face_count"]], exact=True)
        face.click()
        face_evidence = face.evaluate("e => {let a=e;for(let i=0;i<3&&a;i++,a=a.parentElement){if(a.textContent.trim()===e.textContent.trim() && /active|selected|checked/i.test(a.className)) return {selected:true,html:a.outerHTML};}return {selected:false,html:e.parentElement.outerHTML}}")
        if not face_evidence["selected"]:
            raise ValueError("Cannot verify selected face count; inspect the current UI")
        self.core.transition(job_id, "READY", dump({"uploaded_views": list(uploaded), "model": "3.1", "face_count": job["face_count"]}), expected="UPLOADING")
        evidence_dir = Path(job["folder"]) / "browser"
        evidence_dir.mkdir(exist_ok=True)
        atomic_json(evidence_dir / "upload.json", {"views": uploaded, "face_evidence": face_evidence, "elapsed_seconds": time.monotonic()-start_time})
        self.page.screenshot(path=str(evidence_dir / "ready.png"))
        if not submit:
            return {"state": "READY", "job_id": job_id, "elapsed_seconds": time.monotonic()-start_time, "submitted": False}
        self.guard()
        before = self.page.locator("body").inner_text()
        self.core.transition(job_id, "SUBMITTING", "Single generation click reserved by local worker", expected="READY")
        try:
            self.status("SUBMITTING", job["name"])
            self.page.get_by_text("立即生成", exact=True).click(timeout=8000)
            # A click alone is never success. Retain evidence and stop if the UI is ambiguous.
            self.page.wait_for_function("before => {const t=document.body.innerText; return t!==before && /提交成功|任务创建成功/.test(t)}", arg=before, timeout=15000)
            after = self.page.locator("body").inner_text()
            (evidence_dir / "submitted.txt").write_text(after, encoding="utf-8")
            self.core.transition(job_id, "SUBMITTED", "Observed a new submission-success message after one click", expected="SUBMITTING")
            return {"state": "SUBMITTED", "job_id": job_id, "elapsed_seconds": time.monotonic()-start_time,
                    "next": "Capture and bind the actual task card before automated completion/download; never submit again."}
        except Exception:
            self.core.transition(job_id, "UNCERTAIN", "Submission result ambiguous; inspect task list before any further action", expected="SUBMITTING")
            raise

def worker(root):
    from playwright.sync_api import sync_playwright
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / "browser.lock").open("a+b")
    if os.name == "nt":
        import msvcrt
        lock.seek(0)
        if lock.read(1) == b"":
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
    else:
        import fcntl
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
    core = Workbench(root)
    site = core.site
    identity = {"pid": os.getpid(), "site": site.name, "instance_id": uuid.uuid4().hex}
    status_data={'state':'STARTING','detail':''}
    status_lock=threading.Lock()
    stop_heartbeat=threading.Event()
    def status(state=None, detail=""):
        with status_lock:
            if state is not None: status_data.update(state=state,detail=detail)
            atomic_json(root / "browser-status.json", {**status_data, **identity, "heartbeat": time.time()})
    def pulse():
        while not stop_heartbeat.wait(2): status()
    threading.Thread(target=pulse,daemon=True).start()
    status("STARTING")
    queue = root / "queue"
    queue.mkdir(exist_ok=True)
    try:
        # Record ambiguous reservations before writing the terminal queue result.
        for claim in queue.glob('*.running'):
            result = claim.with_suffix('.result.json')
            if result.exists():
                continue
            req = json.loads(claim.read_text(encoding='utf-8'))
            job_id = req.get('job_id')
            if job_id and core.get(job_id)['state'] == 'SUBMITTING':
                core.transition(job_id, 'UNCERTAIN', 'Worker interrupted after submission reservation',
                                expected='SUBMITTING')
            atomic_json(result, {'state': 'ERROR', 'request_id': req['id'],
                                 'error': 'Worker interrupted. Action not replayed; inspect the job before continuing.'})
        with sync_playwright() as pw:
            profile = root / ("chrome-profile" if site.name == "china" else "global/chrome-profile")
            context = pw.chromium.launch_persistent_context(str(profile), headless=False,
                viewport={"width": 1440, "height": 1000}, accept_downloads=True, **browser_options())
            page = context.pages[0] if context.pages else context.new_page()
            auth_pause = GlobalAuthPause(status) if site.name == 'global' else None
            flow = BrowserFlow(page, core, status, auth_pause)
            try:
                if auth_pause is not None and page.url not in ('about:blank', 'chrome://newtab/'):
                    # A restored login or challenge tab belongs to the user.
                    flow.guard()
                flow.navigate(site.home, timeout=45000)
                status("READY", "Dedicated Chrome is open; complete first sign-in there")
            except GlobalAuthError:
                pass  # Keep the browser and its profile open for manual verification.
            job_flows={}
            def job_flow(job_id):
                if auth_pause is not None:
                    auth_pause.check(flow)
                if job_id in job_flows and not job_flows[job_id].page.is_closed(): return job_flows[job_id]
                from lifecycle import read_binding
                job=flow.core.get(job_id)
                site.assert_job(job)
                route=site.validate_url(read_binding(flow,job_id).get('route') or site.route(job.get('feature','geometry')))
                target=BrowserFlow(context.new_page(),flow.core,status,auth_pause)
                job_flows[job_id]=target
                try:
                    target.navigate(route, timeout=30000)
                except GlobalAuthError:
                    raise  # Keep this tab open for manual verification.
                except Exception:
                    target.page.close()
                    raise
                return target
            running = True
            heartbeat = 0
            while running and not page.is_closed():
                if time.monotonic() - heartbeat > 2:
                    if auth_pause is None or auth_pause.error is None:
                        status("IDLE")
                    heartbeat = time.monotonic()
                for source in sorted(queue.glob("*.json"), key=lambda p: p.stat().st_mtime_ns):
                    if source.name.endswith(".result.json"):
                        continue
                    claim = source.with_suffix(".running")
                    try:
                        source.rename(claim)
                    except FileNotFoundError:
                        continue
                    req = json.loads(claim.read_text(encoding="utf-8"))
                    target = None
                    try:
                        if not request_matches_worker(req, identity):
                            raise ValueError("Browser worker or site changed. Inspect the job before making a new request.")
                        if auth_pause is not None and req["op"] != "stop":
                            auth_pause.check(flow, inspecting=req["op"] == "inspect")
                        status("BUSY", req["op"])
                        target=job_flow(req['job_id']) if req.get('job_id') else flow
                        if req["op"] == "inspect": result = target.inspect()
                        elif site.name == "global" and req["op"] not in {"studio", "run", "stop"}:
                            raise ValueError("This research operation is limited to China")
                        elif req["op"] in {"click_text", "hover_text"}:
                            flow.guard()
                            loc = page.get_by_text(req["text"], exact=True)
                            if req["op"] == "click_text": loc.click(timeout=8000)
                            else: loc.hover(timeout=8000)
                            result = flow.inspect()
                        elif req["op"] == "run":
                            import importlib, studio_adapter
                            result=importlib.reload(studio_adapter).dispatch(target,{'action':'run','submit':req.get('submit',False)},req['job_id'])
                        elif req["op"] == "research":
                            import importlib, studio_adapter
                            result = importlib.reload(studio_adapter).research(flow)
                        elif req["op"] == "probe":
                            import importlib, studio_adapter
                            result = importlib.reload(studio_adapter).probe(flow, req.get("text"))
                        elif req["op"] == "download":
                            import importlib, studio_adapter
                            result = importlib.reload(studio_adapter).download_current(flow, req.get("text") or "glb", req.get("job_id"))
                        elif req["op"] == "studio":
                            import importlib, studio_adapter
                            result = importlib.reload(studio_adapter).dispatch(target, json.loads(req.get("text") or "{}"), req.get("job_id"))
                        elif req["op"] == "stop": result, running = {"state": "STOPPED"}, False
                        else: raise ValueError("Unknown operation")
                        response = {"state": "COMPLETE", "request_id": req["id"], "result": result}
                    except Exception as error:
                        if auth_pause is not None and target is not None and not isinstance(error, GlobalAuthError):
                            try:
                                target.guard()
                            except GlobalAuthError as auth_error:
                                error = auth_error
                            except Exception:
                                pass  # Keep the original error if the page is unavailable.
                        response = {"state": "ERROR", "request_id": req["id"], "error": str(error)[:4000]}
                        if isinstance(error, GlobalAuthError):
                            response["code"] = error.code
                        try:
                            if site.name == 'china' and target is not None:
                                target.page.screenshot(path=str(queue / (req["id"] + "-error.png")))
                                response["screenshot"] = str(queue / (req["id"] + "-error.png"))
                        except Exception:
                            pass
                    atomic_json(queue / (req["id"] + ".result.json"), response)
                    if not running:
                        break
                if running and (auth_pause is None or auth_pause.error is None):
                    import lifecycle
                    lifecycle.watch_tick(flow,job_flow)
                if not page.is_closed(): page.wait_for_timeout(200)
            context.close()
    except Exception as error:
        status("STOPPED", str(error)[:1000])
        raise
    finally:
        stop_heartbeat.set()
        if status_data["state"] != "STOPPED": status("STOPPED")
        lock.close()

if __name__ == "__main__":
    worker(sys.argv[1])
