import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import cloud_app
import server as app


class ProductionServer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='shizhi-production-test-')
        self.patches=[patch.object(app,'DATA',Path(self.tmp.name)),patch.object(app,'CLOUD',True),
                      patch.object(app,'APP_SECRET','local-only-test-secret-for-production-tests-123456'),
                      patch.object(app,'PUBLIC_ORIGIN','https://study.example.test')]
        for p in self.patches:p.start()
        cloud_app.BUCKETS.clear()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def request(self,method,path,data=None,cookie=None,**extra):
        payload=json.dumps(data).encode() if data is not None else b''
        environ={'REQUEST_METHOD':method,'PATH_INFO':path,'HTTP_HOST':'study.example.test','HTTP_ACCEPT_LANGUAGE':'en',
                 'REMOTE_ADDR':'203.0.113.20','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(payload)),
                 'wsgi.input':io.BytesIO(payload)}
        if cookie:environ['HTTP_COOKIE']=cookie
        environ.update(extra);result={}
        def respond(status,headers):result.update(status=int(status.split()[0]),headers=dict(headers))
        body=b''.join(cloud_app.application(environ,respond));result['body']=json.loads(body)
        return result

    def test_production_session_isolation_and_headers(self):
        first=self.request('GET','/api/state');second=self.request('GET','/api/state')
        a=first['headers']['Set-Cookie'].split(';')[0];b=second['headers']['Set-Cookie'].split(';')[0]
        self.request('POST','/api/workspace/restore',{'snapshot':None},a)
        self.request('POST','/api/workspace/restore',{'snapshot':None},b)
        self.request('POST','/api/courses',{'name':'Private'},a)
        self.assertEqual(self.request('GET','/api/state',cookie=b)['body']['courses'],[])
        self.assertEqual(len(self.request('GET','/api/state',cookie=a)['body']['courses']),1)
        self.assertIn("frame-ancestors 'none'",first['headers']['Content-Security-Policy'])

    def test_foreign_origin_size_limit_and_rate_limit(self):
        self.assertEqual(self.request('GET','/api/state',HTTP_ORIGIN='https://other.example')['status'],403)
        self.assertEqual(self.request('POST','/api/courses',{},CONTENT_LENGTH=str(app.MAX_BODY+1))['status'],413)
        cloud_app.BUCKETS.clear()
        for i in range(20):self.assertEqual(self.request('GET','/api/state')['status'],200)
        result=self.request('GET','/api/state');self.assertEqual(result['status'],429);self.assertEqual(result['headers']['Retry-After'],'60')

    def test_https_transport_pins_public_ip_and_preserves_tls_hostname(self):
        connection=app.PublicHTTPSConnection('api.example.test')
        connection._context=Mock();raw=Mock()
        addresses=[(2,1,6,'',('1.1.1.1',443))]
        with patch.object(app.socket,'getaddrinfo',return_value=addresses) as dns,patch.object(app.socket,'create_connection',return_value=raw) as tcp:
            connection.connect()
        self.assertEqual(dns.call_count,1)
        self.assertEqual(tcp.call_args.args[0],('1.1.1.1',443))
        connection._context.wrap_socket.assert_called_once_with(raw,server_hostname='api.example.test')
        connection.sock=None

    def test_private_dns_answer_rejected_at_connection_time(self):
        connection=app.PublicHTTPSConnection('api.example.test')
        with patch.object(app.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch.object(app.socket,'create_connection') as tcp:
            with self.assertRaises(app.AppError):connection.connect()
            tcp.assert_not_called()

    def test_waitress_configuration_is_supported(self):
        from waitress.adjustments import Adjustments
        options=Adjustments(host='0.0.0.0',port=10000,threads=8,connection_limit=80,channel_timeout=30,
                            max_request_body_size=app.MAX_BODY,max_request_header_size=16384,
                            expose_tracebacks=False,clear_untrusted_proxy_headers=False)
        self.assertEqual(options.threads,8)


if __name__=='__main__':unittest.main()
