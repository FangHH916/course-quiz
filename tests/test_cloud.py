import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.parse
import server as app


class CloudWorkspaces(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='shizhi-cloud-test-')
        self.patches=[patch.object(app,'DATA',Path(self.tmp.name)),patch.object(app,'CLOUD',True),
                      patch.object(app,'APP_SECRET','local-test-secret-should-never-be-deployed-123456'),
                      patch.object(app,'PUBLIC_ORIGIN','https://study.example.test')]
        for item in self.patches:item.start()
        self.http=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.http.daemon_threads=True
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        for item in reversed(self.patches):item.stop()
        self.tmp.cleanup()

    def request(self,method,path,data=None,cookie=None,origin=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=5)
        headers={'Host':'study.example.test','Accept-Language':'en'}
        if cookie:headers['Cookie']=cookie
        if origin:headers['Origin']=origin
        if data is not None:headers['Content-Type']='application/json'
        connection.request(method,path,body=json.dumps(data).encode() if data is not None else None,headers=headers)
        response=connection.getresponse();body=response.read();result=json.loads(body)
        value=(response.status,result,response.getheader('Set-Cookie'));connection.close();return value

    def workspace(self):
        status,body,cookie=self.request('GET','/api/state')
        self.assertEqual(status,200);self.assertTrue(body['needs_restore'])
        cookie=cookie.split(';')[0]
        self.assertEqual(self.request('POST','/api/workspace/restore',{'snapshot':None},cookie)[0],200)
        return cookie

    def test_separate_browsers_cannot_read_or_delete_each_others_course(self):
        first,second=self.workspace(),self.workspace()
        _,created,_=self.request('POST','/api/courses',{'name':'Private course'},first)
        self.assertEqual(self.request('GET','/api/state',cookie=second)[1]['courses'],[])
        self.request('DELETE','/api/courses/'+created['id'],cookie=second)
        self.assertEqual(len(self.request('GET','/api/state',cookie=first)[1]['courses']),1)

    def test_encrypted_snapshot_restores_after_ephemeral_disk_loss(self):
        cookie=self.workspace();workspace=cookie.split('=',1)[1].split('.')[0]
        self.request('POST','/api/courses',{'name':'Private course, restore me'},cookie)
        backup=self.request('GET','/api/workspace/snapshot',cookie=cookie)[1]['snapshot']
        self.assertNotIn('Private course',backup)
        (app.DATA/'workspaces'/workspace/'study.db').unlink()
        app.INITIALIZED.discard(str(app.DATA/'workspaces'/workspace))
        self.assertTrue(self.request('GET','/api/state',cookie=cookie)[1]['needs_restore'])
        status,_,_=self.request('POST','/api/workspace/restore',{'snapshot':backup},cookie)
        self.assertEqual(status,200)
        state=self.request('GET','/api/state',cookie=cookie)[1]
        self.assertFalse(state['needs_restore']);self.assertEqual(state['courses'][0]['name'],'Private course, restore me')

    def test_snapshot_from_another_workspace_is_rejected(self):
        first=self.workspace();backup=self.request('GET','/api/workspace/snapshot',cookie=first)[1]['snapshot']
        _,_,second_cookie=self.request('GET','/api/state');second=second_cookie.split(';')[0]
        self.assertEqual(self.request('POST','/api/workspace/restore',{'snapshot':backup},second)[0],422)
        self.assertTrue(self.request('GET','/api/state',cookie=second)[1]['needs_restore'])

    def test_foreign_origin_denied_and_cookie_is_signed_httponly(self):
        status,_,cookie=self.request('GET','/api/state')
        self.assertEqual(status,200);self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie);self.assertIn('SameSite=Strict',cookie)
        self.assertEqual(self.request('POST','/api/courses',{'name':'X'},cookie,origin='https://attacker.example')[0],403)
        forged=cookie.split(';')[0].replace('shizhi_workspace=','shizhi_workspace=0')
        _,_,new_cookie=self.request('GET','/api/state',cookie=forged)
        self.assertIsNotNone(new_cookie)

    def test_hosted_model_cannot_connect_to_local_or_private_networks(self):
        for url in ['http://127.0.0.1:1234/v1','https://127.0.0.1/v1','https://169.254.169.254/v1']:
            with self.assertRaises(app.AppError):app.model_request({'base_url':url,'model':'test'},'s','u')

    def test_health_check_does_not_create_workspace(self):
        status,body,cookie=self.request('GET','/healthz')
        self.assertEqual(status,200);self.assertEqual(body,{'ok':True});self.assertIsNone(cookie)
        self.assertFalse((app.DATA/'workspaces').exists())


if __name__=='__main__':unittest.main()
