import sys,io,json,tempfile,unittest,base64,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from media_plan_io import parse_file,MediaPlanStore
import openpyxl
class Tests(unittest.TestCase):
 def test_xlsx_provenance_and_formula(self):
  w=openpyxl.Workbook();s=w.active;s.title='DE';s.append(['产品','素材链接','优惠']);s.append(['E1','下载素材','=10+20']);s['B2'].hyperlink='https://example.com/files';b=io.BytesIO();w.save(b)
  d=parse_file('plan.xlsx',b.getvalue());r=d['sheets'][0]['rows'][1];self.assertEqual(r['row'],2);self.assertEqual(r['cells'][1],'https://example.com/files');self.assertTrue(r['cells'][2].startswith('[公式未计算]'))
 def test_csv_quoted_newline(self):
  d=parse_file('plan.csv','产品,文案\nE1,"Hallo\nWelt"'.encode());self.assertEqual(d['sheets'][0]['rows'][1]['cells'][1],'Hallo\nWelt')
 def test_zip_does_not_extract_paths(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('../test.png',b'not-an-image')
  d=parse_file('test.zip',b.getvalue());self.assertEqual(d['inventory'],['../test.png']);self.assertTrue(d['gaps'])
 def test_state_revision_and_demo_isolation(self):
  with tempfile.TemporaryDirectory() as p:
   st=MediaPlanStore(p);s={'demo':False,'project':'demo','account':'demo-DE'}
   self.assertEqual(st.save({'revision':0,'state':s})['revision'],1)
   with self.assertRaises(ValueError):st.save({'revision':0,'state':s})
   with self.assertRaises(ValueError):st.save({'revision':1,'state':{**s,'demo':True}})
   self.assertEqual(len(list((st.folder/'history').glob('*.json'))),1)
if __name__=='__main__':unittest.main()
