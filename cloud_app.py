"""Bounded WSGI entry point for the hosted deployment; local server stays independent."""
from collections import OrderedDict
import json
import os
import threading
import time
import urllib.parse

import server as app
import email_accounts as accounts

STATIC = {'/': ('index.html', 'text/html; charset=utf-8'), '/workspace.js': ('workspace.js', 'text/javascript; charset=utf-8'),
          '/accounts.js': ('accounts.js', 'text/javascript; charset=utf-8'),
          '/storage.js': ('storage.js', 'text/javascript; charset=utf-8'), '/effects.js': ('effects.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
UPLOADS = threading.BoundedSemaphore(1)
BUCKETS = OrderedDict()
BUCKET_LOCK = threading.Lock()
STATUSES = {200:'OK',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',405:'Method Not Allowed',409:'Conflict',413:'Content Too Large',
            422:'Unprocessable Content',429:'Too Many Requests',500:'Internal Server Error',502:'Bad Gateway',503:'Service Unavailable'}


def rate_limit(key, limit, window=60):
    now = time.monotonic()
    with BUCKET_LOCK:
        entry = BUCKETS.pop(key, None)
        start, used = entry if entry and now - entry[0] < window else (now, 0)
        BUCKETS[key] = (start, used + 1)
        while len(BUCKETS) > 5000:
            BUCKETS.popitem(last=False)
        if used >= limit:
            raise app.AppError('请求过于频繁，请稍后重试。', 429)


def application(environ, start_response):
    status, content_type, cookie, context, acquired = 200, 'application/json; charset=utf-8', None, None, False
    account_cookie, sync_context = None, None
    payload = None
    try:
        host = environ.get('HTTP_HOST', '')
        if host != urllib.parse.urlsplit(app.PUBLIC_ORIGIN).netloc:
            raise app.AppError('请求来源不受支持。', 403)
        origin = environ.get('HTTP_ORIGIN')
        if origin and origin != app.PUBLIC_ORIGIN:
            raise app.AppError('请求来源不受支持。', 403)
        method, path = environ.get('REQUEST_METHOD', 'GET'), environ.get('PATH_INFO', '/')
        if path == '/healthz' and method == 'GET':
            result = {'ok': True}
        elif path.startswith('/api/'):
            guest_workspace, cookie = app.session_cookie(environ.get('HTTP_COOKIE'))
            account, account_cookie = accounts.current_account(environ.get('HTTP_COOKIE'), refresh=path not in {
                '/api/account/login', '/api/account/register', '/api/account/logout', '/api/account/reset-password'})
            workspace = accounts.workspace_id(account) if account and account['verified'] else guest_workspace
            # Render appends the connecting address; never use a caller-supplied first forwarded entry.
            address = (environ.get('HTTP_X_FORWARDED_FOR') or environ.get('REMOTE_ADDR', 'unknown')).split(',')[-1].strip()
            if cookie:
                rate_limit(('new-workspace', address), 20)
            rate_limit(('read', workspace), 600)
            if method in {'POST', 'DELETE'}:
                rate_limit(('write', workspace), 90)
                rate_limit(('ip-write', address), 300)
            if path.startswith('/api/account/') and method == 'POST':
                rate_limit(('account-ip', address), 15)
                rate_limit(('account-browser', guest_workspace), 10)
            if method == 'POST' and path == '/api/materials':
                rate_limit(('upload', workspace), 15)
                acquired = UPLOADS.acquire(blocking=False)
                if not acquired:
                    raise app.AppError('资料正在处理中，请稍后再上传。', 429)
            context = app.WORKSPACE.set(workspace)
            app.ensure_workspace()
            if account and account['verified'] and not path.startswith('/api/account/'):
                accounts.ensure_account_workspace(account)
                if path == '/api/state':
                    accounts.merge_guest(account, guest_workspace)
                sync_context = app.WORKSPACE_SYNC.set(lambda: accounts.sync_workspace(account))
            data = {}
            if method == 'POST':
                try:
                    length = int(environ.get('CONTENT_LENGTH') or 0)
                except ValueError:
                    raise app.AppError('请求数据格式错误。') from None
                if not 0 < length <= app.MAX_BODY:
                    raise app.AppError('请求过大或为空。', 413)
                if not environ.get('CONTENT_TYPE', '').lower().startswith('application/json'):
                    raise app.AppError('请求数据不是有效 JSON。')
                try:
                    data = json.loads(environ['wsgi.input'].read(length))
                except (ValueError, UnicodeError):
                    raise app.AppError('请求数据不是有效 JSON。') from None
                if not isinstance(data, dict):
                    raise app.AppError('请求数据格式错误。')
            if path.startswith('/api/account/'):
                if method != 'POST':
                    raise app.AppError('不支持的请求。', 405)
                response = accounts.route(path, data, account)
                result, proposed_cookie = response[:2]
                if len(response) == 3 and response[2]['verified']:
                    identity = response[2]
                    with app.JOBS_LOCK:
                        if any(owner == guest_workspace for owner in app.JOB_OWNERS.values()):
                            raise app.AppError('请先完成或停止当前出题任务，再绑定邮箱。', 409)
                    account_context = app.WORKSPACE.set(accounts.workspace_id(identity))
                    try:
                        app.ensure_workspace()
                        accounts.ensure_account_workspace(identity)
                        accounts.merge_guest(identity, guest_workspace)
                        accounts.sync_workspace(identity)
                    finally:
                        app.WORKSPACE.reset(account_context)
                account_cookie = proposed_cookie
            else:
                result = app.dispatch(method, path, data)
                if path == '/api/state':
                    result['account'] = accounts.public_status(account)
                if account and account['verified'] and (method in {'POST', 'DELETE'} or path == '/api/state'):
                    try:
                        accounts.sync_workspace(account)
                    except app.AppError as exc:
                        result['sync_warning'] = app.localize_error(str(exc), environ.get('HTTP_ACCEPT_LANGUAGE', 'zh'))
            if isinstance(result, dict) and result.get('error'):
                result['error'] = app.localize_error(result['error'], environ.get('HTTP_ACCEPT_LANGUAGE', 'zh'))
        else:
            if method != 'GET':
                raise app.AppError('不支持的请求。', 405)
            if path not in STATIC:
                raise app.AppError('页面不存在。', 404)
            filename, content_type = STATIC[path]
            payload = (app.ROOT / 'static' / filename).read_bytes()
        if payload is None:
            payload = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except app.AppError as exc:
        status = exc.status
        payload = json.dumps({'error': app.localize_error(str(exc), environ.get('HTTP_ACCEPT_LANGUAGE', 'zh'))}, ensure_ascii=False).encode('utf-8')
    except Exception:
        status = 500
        payload = json.dumps({'error': 'Something went wrong. Please try again.'}).encode()
    finally:
        if acquired:
            UPLOADS.release()
        if context is not None:
            app.WORKSPACE.reset(context)
        if sync_context is not None:
            app.WORKSPACE_SYNC.reset(sync_context)
    headers = [('Content-Type', content_type), ('Content-Length', str(len(payload))), ('Cache-Control', 'no-store'),
               ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'),
               ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
               ('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')]
    if cookie:
        headers.append(('Set-Cookie', cookie))
    if account_cookie:
        headers.append(('Set-Cookie', account_cookie))
    if status == 429:
        headers.append(('Retry-After', '60'))
    start_response(f'{status} {STATUSES.get(status, "Error")}', headers)
    return [payload]


def main():
    from waitress import serve
    if not app.CLOUD or len(app.APP_SECRET) < 32 or not app.PUBLIC_ORIGIN.startswith('https://'):
        raise SystemExit('Hosted mode requires COURSE_QUIZ_CLOUD=1, COURSE_QUIZ_SECRET and an HTTPS public origin.')
    print('Shizhi production server starting.', flush=True)
    serve(application, host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), threads=8, connection_limit=80,
          channel_timeout=30, max_request_body_size=app.MAX_BODY, max_request_header_size=16384,
          expose_tracebacks=False, clear_untrusted_proxy_headers=False)


if __name__ == '__main__':
    main()
