import base64
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import zipfile
import server as app


DEMO_TEXT = '''单利利息 I = P × r × t，其中 P 为本金，r 为年利率，t 为年数。本息合计 A = P + I。
复利终值 A = P × (1 + r)^t。复利中每期利息会在下期计入本金。
投资收益率 = (期末价值 - 期初价值) / 期初价值 × 100%。正收益率表示期末价值高于期初价值。
现值 PV = FV / (1 + r)^t。当未来金额和期数不变时，折现率越高，现值越低。
净现值 NPV = 未来现金流的现值之和 - 初始投资。NPV 大于零表示按给定折现率计算的价值增加。'''


def make_fixture(db):
    cid = app.uid()
    db.execute('INSERT INTO courses VALUES(?,?,?)', (cid, '示例 · 金融基础', app.time.time()))
    mid = app.uid()
    segments = [{'location': '示例资料', 'text': DEMO_TEXT}]
    db.execute('INSERT INTO materials VALUES(?,?,?,?,?,?)', (mid, cid, '金融基础示例.txt', json.dumps(segments, ensure_ascii=False), len(DEMO_TEXT), app.time.time()))
    sources = app.source_blocks(db, cid)
    specs = [
        ('calculation', '本金 10,000 元，年利率 5%，存入 2 年，按单利计算利息。填写金额，保留两位小数，允许误差 ±0.01 元。', 1000, 'I = 10,000 × 0.05 × 2 = 1,000 元。', '单利利息 I = P × r × t，其中 P 为本金，r 为年利率，t 为年数。', '单利', '元'),
        ('calculation', '本金 2,000 元，年利率 10%，每年复利，2 年后的本息合计是多少？保留两位小数，允许误差 ±0.01 元。', 2420, 'A = 2,000 × (1 + 0.10)^2 = 2,420 元。', '复利终值 A = P × (1 + r)^t。', '复利', '元'),
        ('calculation', '投资期初价值 800 元，期末价值 920 元，收益率是多少？以百分数填写，例如 8% 填 8，保留两位小数，误差 ±0.01 个百分点。', 15, '(920 - 800) / 800 × 100% = 15%。填写 15。', '投资收益率 = (期末价值 - 期初价值) / 期初价值 × 100%。', '收益率', '%'),
        ('calculation', '一年后可收到 1,100 元，年折现率为 10%，现值是多少？保留两位小数，允许误差 ±0.01 元。', 1000, 'PV = 1,100 / (1 + 0.10) = 1,000 元。', '现值 PV = FV / (1 + r)^t。', '现值', '元'),
        ('calculation', '某项目未来现金流现值之和为 12,500 元，初始投资为 10,000 元，NPV 是多少？保留两位小数，允许误差 ±0.01 元。', 2500, 'NPV = 12,500 - 10,000 = 2,500 元。', '净现值 NPV = 未来现金流的现值之和 - 初始投资。', '净现值', '元'),
        ('true_false', '其他条件不变时，按单利计算的利息与存入年数成正比。', True, 'I = P × r × t，当 P 和 r 不变时，I 与 t 成正比。', '单利利息 I = P × r × t，其中 P 为本金，r 为年利率，t 为年数。', '单利', ''),
        ('true_false', '复利计算中，每期利息不会计入下期本金。', False, '复利会将每期利息计入下期本金，这是复利与单利的重要区别。', '复利中每期利息会在下期计入本金。', '复利', ''),
        ('true_false', '如果投资收益率为正，则期末价值高于期初价值。', True, '收益率为正说明期末价值减去期初价值大于零。', '正收益率表示期末价值高于期初价值。', '收益率', ''),
        ('true_false', '未来金额和期数固定时，折现率越高，现值越高。', False, 'PV = FV / (1 + r)^t，折现率增大时分母增大，现值降低。', '当未来金额和期数不变时，折现率越高，现值越低。', '现值', ''),
        ('true_false', 'NPV 大于零表示按给定折现率计算的价值增加。', True, '净现值为正意味着未来现金流现值之和大于初始投资。', 'NPV 大于零表示按给定折现率计算的价值增加。', '净现值', '')]
    raw = {'questions': [{'type': k, 'stem': stem, 'answer': answer, 'explanation': exp, 'source': {'id': sources[0]['id'], 'quote': quote}, 'topic': topic, 'unit': unit, 'tolerance': .01}
                         for k, stem, answer, exp, quote, topic, unit in specs]}
    questions = app.validate_questions(raw, {'calculation': 5, 'true_false': 5, 'choice': 0}, sources)
    return app.save_quiz(db, cid, '金融基础 · 示例测验', questions, True)



class StudyWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='shizhi-test-')
        self.old = app.DATA
        app.DATA = Path(self.tmp.name)
        app.init_db()
        api_patch = patch.object(app, 'load_api_config', return_value={'base_url': 'https://test.example/v1', 'model': 'test', 'api_key': 'test-secret-never-persist'})
        api_patch.start()
        self.addCleanup(api_patch.stop)

    def tearDown(self):
        app.DATA = self.old
        self.tmp.cleanup()

    def demo(self):
        with app.connect() as db:
            return make_fixture(db)

    def quiz(self, qid):
        return app.dispatch('GET', '/api/quizzes/' + qid, {})

    def saved(self, qid):
        with app.connect() as db:
            return json.loads(db.execute('SELECT questions FROM quizzes WHERE id=?', (qid,)).fetchone()[0])

    def test_demo_submission_hidden_answers_and_saved_results(self):
        qid = self.demo()
        quiz = self.quiz(qid)
        self.assertEqual(len(quiz['questions']), 10)
        self.assertTrue(quiz['demo'])
        for q in quiz['questions']:
            self.assertFalse({'answer', 'explanation', 'source'} & q.keys())
        answers = {q['id']: q['answer'] for q in self.saved(qid)}
        result = app.dispatch('POST', f'/api/quizzes/{qid}/submit', {'answers': answers})
        self.assertEqual(result['result']['score'], 100)
        self.assertEqual(result['result']['breakdown']['calculation']['correct'], 5)
        self.assertIn('source', result['questions'][0])
        again = app.dispatch('POST', f'/api/quizzes/{qid}/submit', {'answers': {}})
        self.assertEqual(again['result']['score'], 100)
        self.assertEqual(self.quiz(qid)['result']['score'], 100)

    def test_empty_and_false_answers(self):
        qid = self.demo()
        result = app.dispatch('POST', f'/api/quizzes/{qid}/submit', {'answers': {'7': False, '9': False}})
        self.assertEqual(result['result']['score'], 20)
        self.assertEqual(result['result']['correct'], 2)

    def test_wrong_only_retry_has_new_id_and_no_answers(self):
        qid = self.demo()
        app.dispatch('POST', f'/api/quizzes/{qid}/submit', {'answers': {'1': '1000'}})
        retry = app.dispatch('POST', f'/api/quizzes/{qid}/retry', {'wrong_only': True})['id']
        quiz = self.quiz(retry)
        self.assertNotEqual(qid, retry)
        self.assertEqual(len(quiz['questions']), 9)
        self.assertEqual([q['id'] for q in quiz['questions']], [str(i) for i in range(1, 10)])
        self.assertIsNone(quiz['result'])
        self.assertNotIn('answer', quiz['questions'][0])

    def test_numeric_formats_and_strict_absolute_tolerance(self):
        for text in ['1,000.01', '1000.01', '1.00001e3']:
            result = app.grade([{'id':'1','type':'calculation','answer':1000,'tolerance':.01,'unit':'元'}], {'1':text})
            self.assertEqual(result['score'], 100, text)
        for text in ['1,00', '1000.0101', 'NaN', 'inf', '1/2', '1000 元', True]:
            result = app.grade([{'id':'1','type':'calculation','answer':1000,'tolerance':.01,'unit':'元'}], {'1':text})
            self.assertEqual(result['score'], 0, str(text))
        q = {'id':'1','type':'calculation','answer':1_000_000_000,'tolerance':.01,'unit':'元'}
        self.assertEqual(app.grade([q], {'1':'1000000000.02'})['score'], 0)
        self.assertEqual(app.grade([{'id':'1','type':'calculation','answer':8,'tolerance':.01,'unit':'%'}], {'1':'8%'})['score'],100)

    def test_choice_and_boolean_type_checks(self):
        questions = [{'id':'1','type':'true_false','answer':False}, {'id':'2','type':'choice','answer':'B'}]
        self.assertEqual(app.grade(questions, {'1':False,'2':'b'})['score'],100)
        self.assertEqual(app.grade(questions, {'1':'false','2':'A'})['score'],0)

    def test_upload_persist_preview_delete(self):
        cid = app.dispatch('POST','/api/courses',{'name':'测试课程'})['id']
        content = '现金流折现公式：PV = FV / (1+r)^t，r 是折现率，t 是期数。'
        mid = app.dispatch('POST','/api/materials',{'course_id':cid,'name':'notes.txt','content':base64.b64encode(content.encode()).decode()})['id']
        preview = app.dispatch('GET',f'/api/materials/{mid}',{})
        self.assertEqual(preview['segments'][0]['text'],content)
        self.assertEqual(app.dispatch('GET','/api/state',{})['courses'][0]['materials'][0]['chars'],len(content))
        app.dispatch('DELETE',f'/api/materials/{mid}',{})
        self.assertEqual(app.dispatch('GET','/api/state',{})['courses'][0]['materials'],[])

    def test_course_delete_cascades(self):
        qid = self.demo();cid = self.quiz(qid)['course_id']
        app.dispatch('DELETE',f'/api/courses/{cid}',{})
        self.assertEqual(app.dispatch('GET','/api/state',{}),{'courses':[],'history':[]})

    def test_office_extracts_docx_and_pptx_in_slide_order(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for number in [10,2,1]:
                z.writestr(f'ppt/slides/slide{number}.xml',f'<s xmlns:a="urn:draw"><a:p><a:r><a:t>Slide {number}: sample learning material.</a:t></a:r></a:p></s>')
            z.writestr('word/document.xml','<d xmlns:w="urn:word"><w:p><w:r><w:t>Paragraph one, course material.</w:t></w:r></w:p><w:p><w:r><w:t>Table cell text.</w:t></w:r></w:p></d>')
        raw = stream.getvalue()
        slides = app.read_office(raw,'.pptx')
        self.assertEqual([s['text'].split(':')[0] for s in slides],['Slide 1','Slide 2','Slide 10'])
        self.assertIn('Table cell text.',app.read_office(raw,'.docx')[0]['text'])

    def test_upload_errors(self):
        for payload in [{'name':'old.doc','content':'AA=='},{'name':'notes.txt','content':'not base64'},
                        {'name':'bad.pdf','content':base64.b64encode(b'bad pdf').decode()},
                        {'name':'bad.pptx','content':base64.b64encode(b'bad zip').decode()},
                        {'name':'short.txt','text':'tiny'}]:
            with self.assertRaises(app.AppError):
                app.extract_material(payload)

    def test_pdf_scanned_page_message(self):
        from pypdf import PdfWriter
        writer = PdfWriter();writer.add_blank_page(width=200,height=200)
        stream=io.BytesIO();writer.write(stream)
        with self.assertRaisesRegex(app.AppError,'OCR'):
            app.extract_material({'name':'scan.pdf','content':base64.b64encode(stream.getvalue()).decode()})

    def generated_fixture(self):
        qid = self.demo()
        quiz = self.quiz(qid)
        with app.connect() as db:
            sources = app.source_blocks(db,quiz['course_id'])
        question = self.saved(qid)[0]
        question['source']={'id':sources[0]['id'],'quote':question['source']['quote']}
        return quiz['course_id'], {'questions':[question]}, sources

    def test_model_output_rejects_invented_citation(self):
        cid,raw,sources=self.generated_fixture()
        raw['questions'][0]['source']['quote']='This quotation was never in the course material.'
        with self.assertRaisesRegex(app.AppError,'引用'):
            app.validate_questions(raw,{'calculation':1,'true_false':0,'choice':0},sources)

    def test_model_output_rejects_wrong_counts_and_nonfinite(self):
        cid,raw,sources=self.generated_fixture()
        with self.assertRaisesRegex(app.AppError,'题数'):
            app.validate_questions(raw,{'calculation':2,'true_false':0,'choice':0},sources)
        raw['questions'][0]['answer']=float('inf')
        with self.assertRaisesRegex(app.AppError,'有限数值'):
            app.validate_questions(raw,{'calculation':1,'true_false':0,'choice':0},sources)

    def test_model_generation_and_no_key_in_database(self):
        cid,raw,sources=self.generated_fixture()
        plan={'counts':{'calculation':1,'true_false':0,'choice':0},'difficulty':'基础'}
        with patch.object(app,'model_request',side_effect=[json.dumps(plan),json.dumps(raw,ensure_ascii=False)]) as mock:
            created=app.dispatch('POST','/api/generate',{'course_id':cid,'requirements':'只考一道单利计算题','api':{'base_url':'https://test.example/v1','model':'test','api_key':'test-secret-never-persist'}})
            job=self.wait_job(created['job_id'])
        self.assertEqual(job['status'],'complete')
        self.assertEqual(len(self.quiz(job['quiz_id'])['questions']),1)
        self.assertIn('materials',mock.call_args.args[2])
        self.assertNotIn(b'test-secret-never-persist',(app.DATA/'study.db').read_bytes())

    def test_insufficient_material_and_invalid_counts(self):
        cid,raw,sources=self.generated_fixture()
        for counts in [{'calculation':-1,'true_false':0,'choice':0},{'calculation':True,'true_false':0,'choice':0}]:
            with self.assertRaises(app.AppError):app.read_counts({'counts':counts})
        plan={'counts':{'calculation':1,'true_false':0,'choice':0},'difficulty':'基础'}
        with patch.object(app,'model_request',side_effect=[json.dumps(plan),'{"error":"没有计算公式"}']):
            result=app.dispatch('POST','/api/generate',{'course_id':cid,'requirements':'一道计算题','api':{'base_url':'https://test.example','model':'test'}})
            job=self.wait_job(result['job_id'])
            self.assertEqual(job['status'],'error')
            self.assertIn('资料不足',job['error'])

    def wait_job(self,jid):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            job=app.dispatch('GET',f'/api/jobs/{jid}',{})
            with app.JOBS_LOCK:
                active=jid in app.JOBS
            if not active:return job
            time.sleep(.02)
        self.fail('Generation worker did not finish')

    def test_more_than_twenty_questions_batched_without_total_limit(self):
        cid,raw,sources=self.generated_fixture();calls=[]
        def model(config,system,user,max_tokens=14000):
            payload=json.loads(user);calls.append(payload)
            if system==app.PLAN_SYSTEM:return json.dumps({'counts':{'calculation':25,'true_false':0,'choice':0},'difficulty':'适中'})
            batch=[]
            for i in range(payload['counts']['calculation']):
                question=copy.deepcopy(raw['questions'][0]);question['stem']=f'Batch {len(calls)} question {i}. '+question['stem'];batch.append(question)
            return json.dumps({'questions':batch},ensure_ascii=False)
        with patch.object(app,'model_request',side_effect=model):
            response=app.dispatch('POST','/api/generate',{'course_id':cid,'requirements':'25 calculation questions','language':'en','api':{'base_url':'https://test.example','model':'test'}})
            job=self.wait_job(response['job_id'])
        self.assertEqual(job['status'],'complete')
        self.assertEqual(job['completed'],25)
        self.assertEqual(len(self.quiz(job['quiz_id'])['questions']),25)
        self.assertEqual(len(calls),6)
        self.assertTrue(all(p['output_language']=='en' for p in calls))
        self.assertEqual(app.read_counts({'counts':{'calculation':10000,'true_false':0,'choice':0}})['calculation'],10000)

    def test_cancel_keeps_finished_batch_and_erases_config_memory(self):
        cid,raw,sources=self.generated_fixture();cancel=threading.Event();jid=app.uid()
        config={'base_url':'https://test.example','model':'test','api_key':'private-test-key'}
        with app.connect() as db:
            db.execute('INSERT INTO generation_jobs(id,course_id,status,created,updated) VALUES(?,?,?,?,?)',(jid,cid,'planning',time.time(),time.time()))
        def model(cfg,system,user,max_tokens=14000):
            if system==app.PLAN_SYSTEM:return json.dumps({'counts':{'calculation':30,'true_false':0,'choice':0},'difficulty':'适中'})
            cancel.set();batch=[]
            for i in range(6):
                q=copy.deepcopy(raw['questions'][0]);q['stem']=f'Question {i}: '+q['stem'];batch.append(q)
            return json.dumps({'questions':batch},ensure_ascii=False)
        with patch.object(app,'model_request',side_effect=model):
            app.generate_worker(jid,cid,'Test course','30 calculations','zh',sources,config,cancel)
        job=app.dispatch('GET',f'/api/jobs/{jid}',{})
        self.assertEqual(job['status'],'cancelled')
        self.assertEqual(job['completed'],6)
        self.assertEqual(len(self.quiz(job['quiz_id'])['questions']),6)
        self.assertEqual(config,{})

    def test_json_fence_and_malformed_output(self):
        self.assertEqual(app.json_from_model('```json\n{"questions":[]}\n```'),{'questions':[]})
        with self.assertRaises(app.AppError):app.json_from_model('not JSON')

    def test_real_http_adapter_and_headers_against_local_stub(self):
        received=[]
        class Stub(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path,self.headers.get('Authorization'),body))
                response=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'OK'}}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(response)));self.end_headers();self.wfile.write(response)
        http=ThreadingHTTPServer(('127.0.0.1',0),Stub)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            value=app.model_request({'base_url':f'http://127.0.0.1:{http.server_port}/v1','model':'stub-model','api_key':'test-key'},'system','hello',64)
            self.assertEqual(value,'OK')
            self.assertEqual(received[0][0],'/v1/chat/completions')
            self.assertEqual(received[0][1],'Bearer test-key')
            self.assertEqual(received[0][2]['messages'][1]['content'],'hello')
        finally:http.shutdown();http.server_close();thread.join()

    def test_remote_http_and_embedded_credentials_rejected(self):
        for url in ['http://example.com/v1','https://secret@example.com/v1','https://example.com/v1?key=secret']:
            with self.assertRaises(app.AppError):app.model_request({'base_url':url,'model':'x'},'s','u')

    def test_english_error_messages(self):
        self.assertEqual(app.localize_error('请填写课程名称。','en'),'Please enter a course name.')
        self.assertIn('authentication',app.localize_error('模型鉴权失败，请检查 API Key 和模型访问权限。','en'))
        self.assertEqual(app.localize_error('请填写课程名称。','zh'),'请填写课程名称。')


if __name__=='__main__':unittest.main()
