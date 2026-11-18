"""Run: python -m unittest discover -s tests -v (uses disposable copies only)."""
import contextlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import datetime

from docx import Document
from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parents[1]


def workbook(path, rows):
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    wb.save(path)


class Regressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='pharmadesk_regression_')
        cls.scratch = Path(cls.temp.name)
        cls.root = cls.scratch/'application'
        shutil.copytree(ROOT, cls.root, ignore=shutil.ignore_patterns('__pycache__'))
        (cls.root/'Excel_xuat').mkdir(exist_ok=True)
        staged = cls.root/'Excel_xuat'/'prior_session.xlsx'
        staged.write_bytes(b'prior session fixture')
        sys.path.insert(0, str(cls.root))
        with patch.dict(os.environ, {'LOCALAPPDATA': str(cls.scratch/'user_data')}):
            import app, abcven, adr, tdm, ttt, common
        cls.appmod, cls.abc, cls.adr, cls.tdm, cls.ttt, cls.common = app, abcven, adr, tdm, ttt, common
        cls.staging_survived_import = staged.exists()
        app.app.config['TESTING'] = True
        cls.client = app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def post(self, path, **kwargs):
        kwargs.setdefault('headers', {})['X-PharmaDesk-Token'] = self.appmod.SESSION_TOKEN
        return self.client.post(path, **kwargs)

    def test_01_existing_staging_survives_import(self):
        self.assertTrue(self.staging_survived_import)

    def test_02_mutations_require_token_and_origin(self):
        self.assertEqual(self.client.post('/api/reset-session').status_code, 403)
        response = self.post('/api/reset-session', headers={'Origin':'https://review.invalid'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get('/api/state', headers={'Host':'review.invalid'}).status_code, 403)

    def test_03_cleanup_preserves_originals(self):
        source = self.scratch/'source'
        source.mkdir(exist_ok=True)
        original = source/'preserve.rpt'
        original.write_bytes(b'original')
        self.common.atomic_write_json(self.appmod.FOLDER_CONFIG, {'folder':str(source)})
        staged = self.appmod.RPT/'copy.rpt'
        staged.write_bytes(b'copy')
        response = self.post('/api/reset-session')
        self.assertTrue(response.json['ok'])
        self.assertTrue(original.exists())
        self.assertFalse(staged.exists())

    def test_clear_rpt_deletes_only_confirmed_source_rpt(self):
        source = self.scratch/'clear-source'
        source.mkdir()
        original = source/'original.RPT'
        original.write_bytes(b'original')
        spreadsheet = source/'keep.xlsx'
        spreadsheet.write_bytes(b'excel')
        child = source/'nested'
        child.mkdir()
        nested = child/'keep.rpt'
        nested.write_bytes(b'nested')
        outside = self.scratch/'outside.rpt'
        outside.write_bytes(b'outside')
        if os.name != 'nt':
            (source/'linked.rpt').symlink_to(outside)
        staged = self.appmod.RPT/'copy.rpt'
        staged.write_bytes(b'copy')
        self.common.atomic_write_json(self.appmod.FOLDER_CONFIG, {'folder':str(source)})
        try:
            self.assertEqual(self.post('/api/clear-rpt', json={'folder':str(child)}).status_code, 409)
            self.assertTrue(original.exists())
            response = self.post('/api/clear-rpt', json={'folder':str(source)})
            self.assertTrue(response.json['ok'])
            self.assertEqual(response.json['removed_source'], 2)
            self.assertFalse(original.exists())
            self.assertFalse(staged.exists())
            self.assertTrue(spreadsheet.exists())
            self.assertFalse(nested.exists())
            self.assertTrue(outside.exists())
        finally:
            self.appmod.FOLDER_CONFIG.unlink(missing_ok=True)

    def test_04_cleanup_respects_merge_lock(self):
        staged = self.appmod.XLS/'locked.xlsx'
        staged.write_bytes(b'locked')
        self.appmod.LOCK.acquire()
        try:
            self.assertEqual(self.post('/api/reset-session').status_code, 409)
            self.assertTrue(staged.exists())
        finally:
            self.appmod.LOCK.release()
            staged.unlink(missing_ok=True)

    def test_05_json_null_is_a_json_client_error(self):
        response = self.post('/api/run', data='null', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)

    def test_06_session_token_is_in_the_served_page(self):
        response = self.client.get('/tools')
        self.assertIn(self.appmod.SESSION_TOKEN.encode(), response.data)
        self.assertNotIn(b'__PHARMADESK_TOKEN__', response.data)

    def test_07_number_formats(self):
        for text, value in [('0,5',.5),('1.234,56',1234.56),('1,234.56',1234.56),('12.5',12.5),(None,0)]:
            with self.subTest(text=text):
                self.assertAlmostEqual(self.abc.num(text),value)
        for value in ['NaN','Infinity','bad',float('nan')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.abc.num(value)

    def test_08_one_drug_classifies_without_crashing(self):
        rows=[{'tt':100,'hang':'','ven':'E'}]
        self.abc.classify(rows)
        self.assertEqual(rows[0]['hang'],'A')
        self.assertTrue(self.abc.abc_rule_warnings(self.abc.analyze(rows)))

    def test_09_classification_matches_reference_cases(self):
        for index, case in enumerate(json.loads((ROOT/'tests/abc_reference_cases.json').read_text())):
            with self.subTest(case=index):
                rows=[{'tt':v,'hang':'','ven':'E'} for v in case['values']]
                self.abc.classify(rows,False,case['a'],case['b'])
                self.assertEqual(''.join(r['hang'] for r in rows),case['expected'])

    def four_files(self, packaging, vens=('V','N'), concentration=False):
        folder=self.scratch/('input_'+str(len(list(self.scratch.glob('input_*')))))
        folder.mkdir()
        catalog=[]
        for code,ven in zip(('ABCD','EFGH'),vens):
            row=[None]*27
            for i,v in {1:code,2:'Review drug',4:'Review active',5:'10mg/1ml' if concentration else '10mg',8:'Vien',10:packaging,26:ven}.items():row[i]=v
            catalog.append(row)
        workbook(folder/'dm.xlsx',catalog)
        if concentration:
            data=[[None,'ZZZZ','Review drug 10mg/1ml','Vien',10,None,1000]]
        else:
            data=[[None,'ABCD','Review drug','Vien',10,None,1000],[None,'EFGH','Review drug','Vien',10,None,1000]]
        workbook(folder/'khu.xlsx',data)
        workbook(folder/'bhyt.xlsx',[]);workbook(folder/'noi.xlsx',[])
        return self.abc.prepare_four_files(*(folder/f'{name}.xlsx' for name in ('khu','bhyt','noi','dm')))

    def test_10_missing_packaging_preserves_codes_and_ven(self):
        rows,info=self.four_files(None)
        self.assertEqual(len(rows),2)
        self.assertEqual({r['ven'] for r in rows},{'V','N'})
        self.assertEqual(sum(r['tt'] for r in rows),20000)

    def test_11_conflicting_ven_is_not_silently_merged(self):
        rows,info=self.four_files('Hop')
        self.assertEqual(len(rows),2)
        self.assertTrue(any(r['status']=='VEN không thống nhất' for r in info['reviews']))

    def test_12_concentration_lookup_uses_normalized_units(self):
        rows,info=self.four_files('Hop',('V','V'),concentration=True)
        self.assertEqual(rows[0]['ven'],'V')
        self.assertEqual(rows[0]['hl'],'10mg/1ml')

    @staticmethod
    def drug(**kwargs):
        r={'ma':'REVIEW','ten':'Review drug','hc':'Review active','hl':'10mg','qc':'Hop','dvt':'Vien',
           'ven':'E','hang':'A','nhom':'I','gia':100,'sl':1,'tt':100}
        r.update(kwargs)
        return r

    def test_13_excel_formulas_are_exported_as_literal_data(self):
        name=self.abc.export_month_xlsx([self.drug(ten='=1+1')],11,2026)
        wb=load_workbook(self.abc.CFG['data']/'Bao_cao'/name,data_only=False)
        try:
            self.assertEqual(wb['Du_lieu_ABC_VEN']['B2'].value,'=1+1')
            self.assertEqual(wb['Du_lieu_ABC_VEN']['B2'].data_type,'s')
        finally:wb.close()

    def test_14_comparison_does_not_merge_unknown_packaging(self):
        a=self.drug(ma='AAAA',qc='');b=self.drug(ma='BBBB',qc='')
        result=self.abc.compare_month_rows([a,b],[a,b])
        self.assertEqual(result['cur_n'],2)
        self.assertEqual(result['prev_n'],2)
        a=self.drug(ma='AAAA',ven='V');b=self.drug(ma='BBBB',ven='N')
        result=self.abc.compare_month_rows([a,b],[a,b])
        self.assertEqual(result['cur_n'],2)
        self.assertEqual({r['cur_ven'] for r in result['details']},{'V','N'})

    def test_15_report_updates_template_and_does_not_claim_compliance(self):
        folder=self.scratch/'word_input';folder.mkdir(exist_ok=True)
        cur=folder/'current.xlsx'
        workbook(cur,[['Ma duoc','Ten thuoc','Hoat chat','Ham luong','Quy cach','VEN','DVT','Don gia','So luong','Thanh tien','Phan hang ABC'],
                      ['ABCD','AN review','Active','10mg','Hop','N','Vien',100,1,100,'A'],
                      ['EFGH','AV review','Active','10mg','Hop','V','Vien',100,1,100,'A']])
        result=self.abc.generate(cur,12,2026,mode='file',watch=[])
        doc=Document(result['path']);text='\n'.join(p.text for p in doc.paragraphs)
        self.assertIn('THÁNG 12/2026',text)
        self.assertIn('Cần kiểm tra lại phân loại ABC',text)
        self.assertNotIn('Phù hợp với Thông tư 21',text)
        self.assertNotIn('36.025.550.225',text)
        self.assertEqual(len(doc.tables),7)
        header=doc.tables[0].rows[0].cells[1].text
        self.assertIn('tháng 1 năm 2027',header)

    def test_16_failed_report_preserves_history(self):
        self.abc.save_period(5,2026,rows=[self.drug()],stats={'noitru':123})
        before=self.abc._hist_path(5,2026).read_bytes()
        file=self.scratch/'failing.xlsx'
        workbook(file,[['Ten thuoc','VEN','Thanh tien'],['Review','E',100]])
        with patch.object(self.abc,'make_report',side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):self.abc.generate(file,5,2026,watch=[])
        self.assertEqual(self.abc._hist_path(5,2026).read_bytes(),before)

    def test_17_distinct_drafts_and_explicit_update(self):
        patient='Patient Name With At Least Forty Characters For Review'
        first=self.post('/api/adr/draft',json={'data':{'ten_bn':patient,'mo_ta':'first'}}).json
        second=self.post('/api/adr/draft',json={'data':{'ten_bn':patient,'mo_ta':'second'}}).json
        self.assertNotEqual(first['name'],second['name'])
        response=self.post('/api/adr/draft',json={'name':first['name'],'data':{'ten_bn':patient,'mo_ta':'updated'}})
        self.assertTrue(response.json['ok'])
        for name,text in [(first['name'],'updated'),(second['name'],'second')]:
            response=self.client.get('/api/adr/draft',query_string={'name':name})
            self.assertEqual(response.json['data']['mo_ta'],text)
        self.assertEqual(self.client.get('/api/adr/draft?name=../bad').status_code,400)

    def test_18_auc_windows_match_the_concentration_model(self):
        for doses,t12 in [([(0,1000,0)],12), ([(0,1000,1),(12,1000,1),(24,1000,1),(36,1000,1)],1),
                          ([(-12,500,.1),(0,1000,.1),(16,700,1),(32,800,1)],2)]:
            k=math.log(2)/t12;V=50
            iv=[r for r in self.tdm.intervals(doses,k,V,t12,48) if r['ts']>=0]
            for which in (0,1):
                start=24*which;step=.005;n=int(24/step)
                numerical=sum(self.tdm.conc(start+(i+.5)*step,doses,k,V,False,t12=t12)*step for i in range(n))
                self.assertAlmostEqual(self.tdm.window_auc(iv,48,which),numerical,delta=max(.001,numerical*1e-5))
        first=self.tdm.intervals([(0,1000,0)],math.log(2)/12,50,12,48)
        self.assertGreater(self.tdm.window_auc(first,48,0),self.tdm.window_auc(first,48,1))

    def test_19_nonfinite_tdm_inputs_are_rejected(self):
        response=self.post('/api/tdm/vanco/empiric',json={'age':60,'weight':70,'height':170,'scr':1,'thr_peak':'NaN'})
        self.assertEqual(response.status_code,400)
        self.assertFalse(response.json['ok'])
        self.assertNotIn(b': NaN',response.data)

    def test_20_valid_tdm_inputs_remain_successful(self):
        response=self.post('/api/tdm/vanco/empiric',json={'age':60,'weight':70,'height':170,'scr':1})
        self.assertTrue(response.json['ok'])
        self.assertGreater(response.json['with_ld']['auc0_24'],0)
        self.assertGreater(response.json['without_ld']['auc24_48'],0)

    def test_21_invalid_dates_are_skipped_consistently(self):
        self.assertIsNone(self.ttt.to_date('2026-02-30'))
        self.assertIsNone(self.ttt.to_date('30/02/2026',True))
        self.assertEqual(self.ttt.to_date('2026-10-01'),datetime.date(2026,10,1))

    def test_22_inpatient_and_outpatient_events_remain_distinct(self):
        rules={'drugs':{'a':{'ten':'A','codes':['a']},'b':{'ten':'B','codes':['b']}},'pairs':[['a','b']]}
        rows=[]
        for day,encounter in [(datetime.date(2026,10,1),'BA01'),(datetime.date(2026,10,2),'')]:
            for drug in ('a','b'):
                rows.append({'mabn':'PATIENT01','so_ba':encounter,'ten':'Synthetic patient','ns':'1980','day':day,'khoa':'Review','thuoc':drug,'hc':drug,'ma':drug})
        events,_=self.ttt.detect(rows,rules)
        result=self.ttt.aggregate(events,rows,rules,[])
        self.assertEqual(result['n_noi'],1)
        self.assertEqual(result['n_ngoai'],1)
        self.assertEqual(result['noi'][0]['id'],'BA01')

    def test_23_corrupt_input_blocks_partial_merge(self):
        self.appmod.clean_staging()
        workbook(self.appmod.XLS/'valid.xlsx',[['STT','Mã','Tên thuốc','ĐVT','Đơn giá','Thành tiền'],[1,'REVIEW01','Review drug','Vien',10,1000]])
        (self.appmod.XLS/'corrupt.xlsx').write_bytes(b'not an Excel file')
        out=self.appmod.OUTS['boi'];out.write_bytes(b'last good report')
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            response=self.post('/api/run',json={'export':False,'mode':'boi'})
        self.assertFalse(response.json['ok'])
        self.assertIn('corrupt.xlsx',response.json['log'])
        self.assertEqual(out.read_bytes(),b'last good report')
        (self.appmod.XLS/'corrupt.xlsx').unlink()
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            response=self.post('/api/run',json={'export':False,'mode':'boi'})
        self.assertTrue(response.json['ok'],response.json.get('log'))
        wb=load_workbook(out,read_only=True);self.assertIn('In',wb.sheetnames);wb.close()


if __name__=='__main__':
    unittest.main()
