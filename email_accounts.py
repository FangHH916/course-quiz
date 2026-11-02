"""Optional Firebase email accounts. Tokens stay in encrypted HttpOnly cookies.

Firebase's verified user ID owns an encrypted Firestore snapshot; no admin key is used.
"""
import base64
from contextvars import ContextVar
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import server as app

PROJECT = os.environ.get('FIREBASE_PROJECT_ID', '')
API_KEY = os.environ.get('FIREBASE_API_KEY', '')
ACCOUNT = ContextVar('email_account', default=None)
CHUNK_SIZE = 450_000
LOCKS = [threading.RLock() for _ in range(64)]


def configured():
    return bool(app.CLOUD and re.fullmatch(r'[a-z][a-z0-9-]{4,61}', PROJECT) and API_KEY)


def account_lock(uid):
    return LOCKS[int(hashlib.sha256(uid.encode()).hexdigest()[:8], 16) % len(LOCKS)]


def cipher():
    from cryptography.fernet import Fernet
    key = hmac.new(app.APP_SECRET.encode(), b'email-session-v1', hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def cookie(account=None):
    value = cipher().encrypt(json.dumps(account).encode()).decode() if account else ''
    if len(value) > 3800:
        raise app.AppError('登录会话过大，请联系维护者。', 502)
    age = 30 * 86400 if account else 0
    secure = '; Secure' if app.PUBLIC_ORIGIN.startswith('https://') else ''
    return f'shizhi_account={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}{secure}'


def provider(url, payload=None, token=None, method=None, form=False, missing_ok=False):
    headers = {'Accept': 'application/json'}
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        body = urllib.parse.urlencode(payload).encode() if form else json.dumps(payload).encode()
    if token:
        headers['Authorization'] = 'Bearer ' + token
    transport = app.PublicHTTPSHandler(context=app.ssl.create_default_context())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), app.NoRedirect(), transport)
    try:
        request = urllib.request.Request(url, data=body, headers=headers, method=method or ('POST' if body else 'GET'))
        with opener.open(request, timeout=25) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise app.AppError('账号服务响应过大，请稍后重试。', 502)
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        try:
            result = json.loads(exc.read(20000))
            code = str(result.get('error', {}).get('message', ''))[:100]
        except (ValueError, TypeError, AttributeError):
            code = ''
        if any(term in code for term in ('INVALID_LOGIN_CREDENTIALS', 'INVALID_PASSWORD', 'EMAIL_NOT_FOUND', 'USER_DISABLED', 'INVALID_REFRESH_TOKEN', 'TOKEN_EXPIRED', 'USER_NOT_FOUND')):
            raise app.AppError('邮箱或密码不正确，或登录已失效，请重新登录。', 401) from None
        if 'EMAIL_EXISTS' in code:
            raise app.AppError('该邮箱无法完成注册，请尝试登录或找回密码。', 409) from None
        if 'TOO_MANY_ATTEMPTS' in code or exc.code == 429:
            raise app.AppError('账号操作过于频繁，请稍后再试。', 429) from None
        if exc.code == 403 or 'PERMISSION_DENIED' in code:
            raise app.AppError('账号云同步权限未配置或邮箱尚未验证，请联系维护者。', 503) from None
        raise app.AppError('账号服务暂时不可用，请稍后重试。', 503) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise app.AppError('无法连接账号服务，请稍后重试。', 503) from None


def auth_request(action, payload):
    return provider('https://identitytoolkit.googleapis.com/v1/accounts:' + action + '?key=' + urllib.parse.quote(API_KEY, safe=''), payload)


def valid_email(value):
    if not isinstance(value, str) or len(value) > 254 or not re.fullmatch(r'[^\s@<>\x00-\x1f]+@[^\s@<>\x00-\x1f]+\.[^\s@<>\x00-\x1f]+', value):
        raise app.AppError('请输入有效的邮箱地址。')
    return value.strip().lower()


def credentials(data, signup=False):
    email = valid_email(data.get('email'))
    password = data.get('password')
    if not isinstance(password, str) or not 1 <= len(password) <= 128 or (signup and len(password) < 12):
        raise app.AppError('注册密码至少 12 个字符，最多 128 个字符。' if signup else '请输入密码。')
    return email, password


def checked_account(tokens, started=None):
    token = tokens.get('idToken') or tokens.get('id_token')
    refresh = tokens.get('refreshToken') or tokens.get('refresh_token')
    info = auth_request('lookup', {'idToken': token})
    users = info.get('users', [])
    if len(users) != 1:
        raise app.AppError('无法验证登录身份，请重试。', 401)
    user = users[0]
    uid = user.get('localId', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', uid) or not isinstance(token, str) or not isinstance(refresh, str):
        raise app.AppError('账号服务返回了无效的登录信息。', 502)
    return {'uid': uid, 'email': valid_email(user.get('email')), 'verified': user.get('emailVerified') is True,
            'id_token': token, 'refresh_token': refresh, 'expires_at': time.time() + int(tokens.get('expiresIn', tokens.get('expires_in', 3600))),
            'started': started or time.time()}


def current_account(cookie_header, refresh=True):
    if not configured():
        return None, None
    from cryptography.fernet import InvalidToken
    try:
        cookies = SimpleCookie(); cookies.load(cookie_header or '')
        token = cookies['shizhi_account'].value
        account = json.loads(cipher().decrypt(token.encode(), ttl=30 * 86400))
        if not isinstance(account, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', account['uid']):
            raise ValueError('identity')
        if time.time() - account['started'] > 30 * 86400:
            raise ValueError('age')
    except KeyError:
        return None, None
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        return None, cookie()
    replacement = None
    if refresh and account['expires_at'] < time.time() + 90:
        with account_lock(account['uid']):
            tokens = provider('https://securetoken.googleapis.com/v1/token?key=' + urllib.parse.quote(API_KEY, safe=''),
                              {'grant_type': 'refresh_token', 'refresh_token': account['refresh_token']}, form=True)
            refreshed = checked_account(tokens, started=account['started'])
            if refreshed['uid'] != account['uid']:
                raise app.AppError('登录身份不一致，请重新登录。', 401)
            if not account['verified']:
                refreshed['verified'] = False  # Explicit verification completion performs the guest-data migration.
            account = refreshed
            replacement = cookie(account)
    return account, replacement


def workspace_id(account):
    return hashlib.sha256(('email-account:' + account['uid']).encode()).hexdigest()[:32]


def renew_account(account):
    with account_lock(account['uid']):
        tokens = provider('https://securetoken.googleapis.com/v1/token?key=' + urllib.parse.quote(API_KEY, safe=''),
                          {'grant_type': 'refresh_token', 'refresh_token': account['refresh_token']}, form=True)
        renewed = checked_account(tokens, started=account['started'])
        if renewed['uid'] != account['uid']:
            raise app.AppError('登录身份不一致，请重新登录。', 401)
        return renewed


def public_status(account):
    return {'configured': configured(), 'user': {'email': account['email'], 'verified': account['verified']} if account else None}


def firestore_root():
    return f'projects/{PROJECT}/databases/(default)/documents'


def firestore_path(account):
    return firestore_root() + '/users/' + urllib.parse.quote(account['uid'], safe='')


def document_get(account, path):
    return provider('https://firestore.googleapis.com/v1/' + path, token=account['id_token'], missing_ok=True)


def commit(account, writes):
    for start in range(0, len(writes), 10):
        provider('https://firestore.googleapis.com/v1/' + firestore_root() + ':commit', {'writes': writes[start:start + 10]}, token=account['id_token'])


def read_cloud_snapshot(account):
    doc = document_get(account, firestore_path(account))
    if not doc:
        return None, None
    try:
        fields = doc['fields']; version = fields['version']['stringValue']; count = int(fields['parts']['integerValue'])
        digest = fields['digest']['stringValue']
        if not re.fullmatch(r'[a-f0-9]{32}', version) or not 1 <= count <= 128 or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('manifest')
        parts = []
        for index in range(count):
            chunk = document_get(account, firestore_path(account) + f'/snapshots/{version}/chunks/{index:04d}')
            parts.append(chunk['fields']['data']['stringValue'])
        snapshot = ''.join(parts)
        if len(snapshot) > 64 * 1024 * 1024:
            raise ValueError('size')
        # Authentication and workspace binding are also enforced by the snapshot cipher.
        raw = app.snapshot_cipher().decrypt(snapshot.encode())
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('digest')
        return snapshot, {'version': version, 'parts': count, 'digest': digest}
    except Exception as exc:
        if isinstance(exc, app.AppError):
            raise
        raise app.AppError('账号云端备份不完整，请稍后重试，勿清除浏览器备份。', 503) from None


def ensure_account_workspace(account):
    if not account or not account['verified']:
        return
    with account_lock(account['uid']):
        with app.connect() as db:
            ready = db.execute("SELECT 1 FROM workspace_meta WHERE key='initialized'").fetchone()
        if ready:
            return
        snapshot, manifest = read_cloud_snapshot(account)
        with app.connect() as db:
            app.restore_snapshot(db, snapshot)
            if manifest:
                for key, value in {'cloud_digest': manifest['digest'], 'cloud_version': manifest['version'], 'cloud_parts': str(manifest['parts'])}.items():
                    db.execute('INSERT OR REPLACE INTO workspace_meta VALUES(?,?)', (key, value))


def sync_workspace(account):
    if not account or not account['verified']:
        return
    with account_lock(account['uid']):
        if account['expires_at'] < time.time() + 90:
            account.update(renew_account(account))
        with app.connect() as db:
            snapshot = app.create_snapshot(db)
            previous = {row['key']: row['value'] for row in db.execute("SELECT * FROM workspace_meta WHERE key LIKE 'cloud_%'")}
        digest = hashlib.sha256(app.snapshot_cipher().decrypt(snapshot.encode())).hexdigest()
        if previous.get('cloud_digest') == digest:
            return
        version = secrets.token_hex(16)
        parts = [snapshot[i:i + CHUNK_SIZE] for i in range(0, len(snapshot), CHUNK_SIZE)]
        if len(parts) > 128:
            raise app.AppError('账号备份数据过大，请整理资料后重试。', 413)
        root = firestore_path(account)
        writes = [{'update': {'name': root + f'/snapshots/{version}/chunks/{i:04d}', 'fields': {'data': {'stringValue': part}}}} for i, part in enumerate(parts)]
        commit(account, writes)
        commit(account, [{'update': {'name': root, 'fields': {'version': {'stringValue': version}, 'parts': {'integerValue': str(len(parts))}, 'digest': {'stringValue': digest}}}}])
        with app.connect() as db:
            for key, value in {'cloud_digest': digest, 'cloud_version': version, 'cloud_parts': str(len(parts))}.items():
                db.execute('INSERT OR REPLACE INTO workspace_meta VALUES(?,?)', (key, value))
        if previous.get('cloud_version') and previous['cloud_version'] != version:
            try:
                commit(account, [{'delete': root + f'/snapshots/{previous["cloud_version"]}/chunks/{i:04d}'} for i in range(int(previous.get('cloud_parts', '0')))])
            except app.AppError:
                pass  # An old encrypted version is safer than losing the newly committed snapshot.


def merge_guest(account, guest_workspace):
    """Copy only this browser's guest records, save remotely, then clear the guest copy."""
    if guest_workspace == workspace_id(account):
        return
    context = app.WORKSPACE.set(guest_workspace)
    try:
        app.ensure_workspace()
        source = app.connect()
    finally:
        app.WORKSPACE.reset(context)
    with source:
        source.execute('BEGIN IMMEDIATE')
        rows = {table: [dict(row) for row in source.execute(f'SELECT * FROM {table}')] for table in app.SNAPSHOT_TABLES}
        if not rows['courses']:
            return
        with app.connect() as db:
            for table in app.SNAPSHOT_TABLES:
                for row in rows[table]:
                    columns = list(row)
                    db.execute(f'INSERT OR IGNORE INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', list(row.values()))
        sync_workspace(account)
        source.execute('DELETE FROM courses')


def route(path, data, account):
    if not configured():
        raise app.AppError('邮箱账号服务尚未配置，当前仍可使用浏览器工作区。', 503)
    if path == '/api/account/logout':
        return {'ok': True}, cookie()
    if path == '/api/account/reset-password':
        email = valid_email(data.get('email'))
        try:
            auth_request('sendOobCode', {'requestType': 'PASSWORD_RESET', 'email': email, 'continueUrl': app.PUBLIC_ORIGIN})
        except app.AppError as exc:
            if exc.status != 401:
                raise
        return {'ok': True}, None
    if path == '/api/account/resend':
        if not account:
            raise app.AppError('请先登录需要验证的邮箱账号。', 401)
        if account['verified']:
            return {'ok': True}, None
        auth_request('sendOobCode', {'requestType': 'VERIFY_EMAIL', 'idToken': account['id_token'], 'continueUrl': app.PUBLIC_ORIGIN})
        return {'ok': True}, None
    if path == '/api/account/check-verification':
        if not account:
            raise app.AppError('请先登录需要验证的邮箱账号。', 401)
        identity = renew_account(account)
        return {'user': {'email': identity['email'], 'verified': identity['verified']}}, cookie(identity), identity
    if path not in {'/api/account/register', '/api/account/login'}:
        raise app.AppError('接口不存在。', 404)
    signup = path.endswith('/register')
    if account and account['verified']:
        raise app.AppError('请先退出当前账号，再登录其他邮箱。', 409)
    email, password = credentials(data, signup)
    tokens = auth_request('signUp' if signup else 'signInWithPassword', {'email': email, 'password': password, 'returnSecureToken': True})
    identity = checked_account(tokens)
    result = {'user': {'email': identity['email'], 'verified': identity['verified']}}
    if signup and not identity['verified']:
        try:
            auth_request('sendOobCode', {'requestType': 'VERIFY_EMAIL', 'idToken': identity['id_token'], 'continueUrl': app.PUBLIC_ORIGIN})
            result['verification_sent'] = True
        except app.AppError:
            result['verification_sent'] = False
    # Identity is returned internally for the WSGI layer only; the browser never receives tokens.
    return result, cookie(identity), identity
