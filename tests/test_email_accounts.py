import copy
import io
import json
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.parse

import cloud_app
import email_accounts as accounts
import server as app


class FakeFirebase:
    """Explicit test double; sends no email and never contacts a real account provider."""
    def __init__(self):
        self.users={};self.tokens={};self.refresh={};self.docs={};self.emails=[];self.writes=0;self.fail_writes=False

    def issue(self,user):
        token='test-token-'+secrets.token_hex(10);refresh='test-refresh-'+user['localId']
        self.tokens[token]=user['localId'];self.refresh[refresh]=user['localId']
        return {'idToken':token,'refreshToken':refresh,'expiresIn':'3600'}

    def __call__(self,url,payload=None,token=None,method=None,form=False,missing_ok=False):
        if 'identitytoolkit.googleapis.com' in url:
            action=url.split('accounts:')[1].split('?')[0]
            if action=='signUp':
                if payload['email'] in self.users:raise app.AppError('该邮箱无法完成注册，请尝试登录或找回密码。',409)
                user={'localId':'user_'+secrets.token_hex(8),'email':payload['email'],'emailVerified':False,'password':payload['password']}
                self.users[user['email']]=user;return self.issue(user)
            if action=='signInWithPassword':
                user=self.users.get(payload['email'])
                if not user or user['password']!=payload['password']:raise app.AppError('邮箱或密码不正确，或登录已失效，请重新登录。',401)
                return self.issue(user)
            if action=='lookup':
                uid=self.tokens.get(payload.get('idToken'))
                return {'users':[{k:v for k,v in user.items() if k!='password'} for user in self.users.values() if user['localId']==uid]}
            if action=='sendOobCode':
                self.emails.append(copy.deepcopy(payload));return {'email':'test@example.test'}
            raise AssertionError(action)
        if 'securetoken.googleapis.com' in url:
            uid=self.refresh[payload['refresh_token']];user=next(u for u in self.users.values() if u['localId']==uid)
            result=self.issue(user);return {'id_token':result['idToken'],'refresh_token':result['refreshToken'],'expires_in':'3600'}
        if 'firestore.googleapis.com' in url:
            uid=self.tokens.get(token);user=next((u for u in self.users.values() if u['localId']==uid),None)
            if not user or not user['emailVerified']:raise app.AppError('账号云同步权限未配置或邮箱尚未验证，请联系维护者。',503)
            root=accounts.firestore_root()+'/users/'+uid
            if url.endswith(':commit'):
                if self.fail_writes:raise app.AppError('账号服务暂时不可用，请稍后重试。',503)
                for write in payload['writes']:
                    path=write['update']['name'] if 'update' in write else write['delete']
                    assert path==root or path.startswith(root+'/'), 'wrong account owner'
                    if 'delete' in write:self.docs.pop(path,None)
                    else:self.docs[path]=copy.deepcopy(write['update'])
                    self.writes+=1
                return {'writeResults':[]}
            path=url.split('/v1/',1)[1]
            assert path==root or path.startswith(root+'/'), 'cross-account read'
            return copy.deepcopy(self.docs.get(path))
        raise AssertionError(url)


class EmailAccounts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='shizhi-email-test-')
        self.fake=FakeFirebase()
        self.patches=[patch.object(app,'DATA',Path(self.tmp.name)),patch.object(app,'CLOUD',True),
                      patch.object(app,'APP_SECRET','test-only-email-session-secret-never-for-production'),
                      patch.object(app,'PUBLIC_ORIGIN','https://study.example.test'),patch.object(accounts,'PROJECT','shizhi-test-project'),
                      patch.object(accounts,'API_KEY','test-public-firebase-key'),patch.object(accounts,'provider',side_effect=self.fake)]
        for p in self.patches:p.start()
        cloud_app.BUCKETS.clear()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def request(self,path,data=None,cookie='',method=None):
        body=json.dumps(data).encode() if data is not None else b''
        environ={'REQUEST_METHOD':method or ('POST' if data is not None else 'GET'),'PATH_INFO':path,
                 'HTTP_HOST':'study.example.test','HTTP_ORIGIN':'https://study.example.test','HTTP_ACCEPT_LANGUAGE':'en',
                 'HTTP_COOKIE':cookie,'REMOTE_ADDR':'198.51.100.5','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(body)),
                 'wsgi.input':io.BytesIO(body)}
        captured={}
        def start(status,headers):captured.update(status=int(status.split()[0]),headers=headers)
        result=json.loads(b''.join(cloud_app.application(environ,start)))
        cookie_map=dict(pair.strip().split('=',1) for pair in cookie.split(';') if '=' in pair)
        for key,value in captured['headers']:
            if key.lower()=='set-cookie':
                name,content=value.split(';')[0].split('=',1)
                if content:cookie_map[name]=content
                else:cookie_map.pop(name,None)
        captured.update(body=result,cookie='; '.join(k+'='+v for k,v in cookie_map.items()))
        return captured

    def guest(self):
        result=self.request('/api/state');cookie=result['cookie']
        self.assertEqual(self.request('/api/workspace/restore',{'snapshot':None},cookie)['status'],200)
        return cookie

    def register(self,email='student@example.test',cookie=''):
        result=self.request('/api/account/register',{'email':email,'password':'a-long-test-password'},cookie)
        self.assertEqual(result['status'],200,result['body']);return result

    def verify(self,registration):
        user=self.fake.users[registration['body']['user']['email']];user['emailVerified']=True
        result=self.request('/api/account/check-verification',{},registration['cookie'])
        self.assertEqual(result['status'],200,result['body']);return result

    def test_registration_requires_verification_and_keeps_tokens_out_of_json(self):
        cookie=self.guest();result=self.register(cookie=cookie)
        self.assertFalse(result['body']['user']['verified']);self.assertTrue(result['body']['verification_sent'])
        self.assertEqual(self.fake.emails[0]['requestType'],'VERIFY_EMAIL')
        wire=json.dumps(result['body']);self.assertNotIn('idToken',wire);self.assertNotIn('refresh',wire);self.assertNotIn('password',wire)
        auth_cookie=next(v for k,v in result['headers'] if k=='Set-Cookie' and v.startswith('shizhi_account='))
        self.assertIn('HttpOnly',auth_cookie);self.assertIn('Secure',auth_cookie);self.assertNotIn('student@example.test',auth_cookie)
        self.assertNotIn('test-token',auth_cookie)
        state=self.request('/api/state',cookie=result['cookie'])['body'];self.assertFalse(state['account']['user']['verified'])
        self.assertEqual(self.fake.docs,{})

    def test_verification_migrates_guest_and_cloud_restores_on_a_second_browser(self):
        guest=self.guest();cid=self.request('/api/courses',{'name':'My original course'},guest)['body']['id']
        self.request('/api/materials',{'course_id':cid,'name':'notes.txt','text':'Simple interest is principal times annual rate times years.'},guest)
        registration=self.register(cookie=guest);verified=self.verify(registration)
        state=self.request('/api/state',cookie=verified['cookie'])['body']
        self.assertTrue(state['account']['user']['verified']);self.assertEqual(state['courses'][0]['name'],'My original course')
        self.assertEqual(self.request('/api/state',cookie=guest)['body']['courses'],[])
        encrypted=json.dumps(self.fake.docs);self.assertNotIn('My original course',encrypted);self.assertNotIn('Simple interest',encrypted)
        account,_=accounts.current_account(verified['cookie']);directory=app.DATA/'workspaces'/accounts.workspace_id(account)
        (directory/'study.db').unlink();app.INITIALIZED.discard(str(directory))
        second=self.guest();login=self.request('/api/account/login',{'email':'student@example.test','password':'a-long-test-password'},second)
        self.assertEqual(login['status'],200,login['body'])
        restored=self.request('/api/state',cookie=login['cookie'])['body']
        self.assertEqual(restored['courses'][0]['id'],cid)

    def test_two_email_accounts_are_isolated_and_signout_removes_access(self):
        first=self.verify(self.register(cookie=self.guest()))
        second=self.verify(self.register('another@example.test',cookie=self.guest()))
        self.request('/api/courses',{'name':'Private account course'},first['cookie'])
        self.assertEqual(self.request('/api/state',cookie=second['cookie'])['body']['courses'],[])
        signed_out=self.request('/api/account/logout',{},first['cookie'])
        self.assertNotIn('shizhi_account=',signed_out['cookie'])
        self.assertEqual(self.request('/api/state',cookie=signed_out['cookie'])['body']['courses'],[])

    def test_sync_deduplicates_unchanged_data(self):
        session=self.verify(self.register(cookie=self.guest()))
        self.request('/api/courses',{'name':'Course'},session['cookie']);writes=self.fake.writes
        self.request('/api/state',cookie=session['cookie']);self.request('/api/state',cookie=session['cookie'])
        self.assertEqual(self.fake.writes,writes)

    def test_guest_write_finishing_after_login_is_moved_on_next_refresh(self):
        guest=self.guest();session=self.verify(self.register(cookie=guest))
        self.request('/api/courses',{'name':'Late guest upload'},guest)
        state=self.request('/api/state',cookie=session['cookie'])['body']
        self.assertEqual(state['courses'][0]['name'],'Late guest upload')
        self.assertEqual(self.request('/api/state',cookie=guest)['body']['courses'],[])

    def test_remote_failure_does_not_clear_guest_or_issue_verified_session(self):
        guest=self.guest();self.request('/api/courses',{'name':'Preserve me'},guest)
        registration=self.register(cookie=guest);self.fake.users['student@example.test']['emailVerified']=True
        self.fake.fail_writes=True
        failure=self.request('/api/account/check-verification',{},registration['cookie'])
        self.assertEqual(failure['status'],503)
        self.assertFalse(any(k=='Set-Cookie' and v.startswith('shizhi_account=') for k,v in failure['headers']))
        self.assertEqual(self.request('/api/state',cookie=guest)['body']['courses'][0]['name'],'Preserve me')

    def test_invalid_cookie_and_wrong_password_do_not_authenticate(self):
        account,clear=accounts.current_account('shizhi_account=forged-token')
        self.assertIsNone(account);self.assertIn('Max-Age=0',clear)
        self.register(cookie=self.guest())
        result=self.request('/api/account/login',{'email':'student@example.test','password':'incorrect'},self.guest())
        self.assertEqual(result['status'],401)

    def test_expired_access_token_refreshes_without_exposing_refresh_token(self):
        session=self.verify(self.register(cookie=self.guest()))
        account,_=accounts.current_account(session['cookie']);account['expires_at']=time.time()-1
        expired=accounts.cookie(account).split(';')[0]
        refreshed,replacement=accounts.current_account(expired)
        self.assertEqual(refreshed['uid'],account['uid']);self.assertGreater(refreshed['expires_at'],time.time())
        self.assertIsNotNone(replacement);self.assertNotIn('test-refresh',replacement)

    def test_unknown_password_reset_is_neutral(self):
        with patch.object(accounts,'auth_request',side_effect=app.AppError('invalid',401)):
            result=accounts.route('/api/account/reset-password',{'email':'unknown@example.test'},None)
        self.assertTrue(result[0]['ok'])

    def test_pending_verification_does_not_silently_switch_workspace_on_refresh(self):
        session=self.register(cookie=self.guest())
        account,_=accounts.current_account(session['cookie']);account['expires_at']=time.time()-1
        self.fake.users['student@example.test']['emailVerified']=True
        expired=accounts.cookie(account).split(';')[0]
        renewed,_=accounts.current_account(expired)
        self.assertFalse(renewed['verified'])
        explicit=accounts.route('/api/account/check-verification',{},renewed)
        self.assertTrue(explicit[2]['verified'])

    def test_missing_provider_keeps_guest_functional(self):
        with patch.object(accounts,'API_KEY',''):
            state=self.request('/api/state');self.assertEqual(state['status'],200);self.assertFalse(state['body']['account']['configured'])
            self.assertEqual(self.request('/api/account/register',{'email':'x@example.test','password':'a-long-test-password'},state['cookie'])['status'],503)


if __name__=='__main__':unittest.main()
