"""Local Media Plan import. No remote requests, OCR or ad-account mutations."""
import base64, csv, hashlib, io, json, mimetypes, os, zipfile
from pathlib import Path
from datetime import datetime, timezone, date

MAX_BYTES=12_000_000

def parse_file(name, raw):
    if len(raw)>MAX_BYTES: raise ValueError('单个文件最多 12 MB')
    digest=hashlib.sha256(raw).hexdigest()
    ext=Path(name).suffix.lower()
    result={'name':Path(name).name,'sha256':digest,'sheets':[],'assets':[],'gaps':[]}
    def asset(filename,data,anchor=None):
        mime=mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        safe=mime in ['image/png','image/jpeg','image/webp','image/gif']
        return {'name':filename,'sha256':hashlib.sha256(data).hexdigest(),'anchor':anchor,
                'preview':f'data:{mime};base64,'+base64.b64encode(data).decode() if safe and len(data)<2_000_000 else '',
                'size':len(data),'ocr':'NOT_IMPLEMENTED'}
    if ext in ['.xlsx','.zip']:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if len(z.infolist())>2500 or sum(i.file_size for i in z.infolist())>80_000_000:
                raise ValueError('文件展开后过大，请拆分后导入')
    if ext=='.xlsx':
        import openpyxl
        wb=openpyxl.load_workbook(io.BytesIO(raw),data_only=False)
        for ws in wb.worksheets:
            if ws.max_row>10000 or ws.max_column>150: raise ValueError('工作表过大，请导出相关工作表后导入')
            rows=[]
            for row in ws.iter_rows():
                vals=[]
                for c in row:
                    value='' if c.value is None else c.value.date().isoformat() if isinstance(c.value,datetime) else c.value.isoformat() if isinstance(c.value,date) else str(c.value)
                    if c.data_type=='f':
                        value='[公式未计算] '+value
                    elif c.hyperlink and c.hyperlink.target:
                        value=str(c.hyperlink.target)
                    vals.append(value)
                if any(vals): rows.append({'row':row[0].row,'cells':vals})
            result['sheets'].append({'name':ws.title,'rows':rows})
            if ws.merged_cells.ranges: result['gaps'].append(ws.title+' 有合并单元格：未自动向下填充，请核对行归属')
            for i,img in enumerate(ws._images):
                try:
                    a=img.anchor._from
                    result['assets'].append(asset(f'{ws.title}-图片{i+1}.{img.format}',img._data(),{'sheet':ws.title,'row':a.row+1,'column':a.col+1}))
                except Exception: result['gaps'].append(ws.title+' 有嵌入图片读取失败')
    elif ext in ['.csv','.tsv','.txt']:
        try: text=raw.decode('utf-8-sig')
        except UnicodeDecodeError: text=raw.decode('gb18030')
        try: dialect=csv.Sniffer().sniff(text[:8000],delimiters=',\t;')
        except csv.Error: dialect=csv.excel_tab if '\t' in text else csv.excel
        rows=[{'row':i+1,'cells':r} for i,r in enumerate(csv.reader(io.StringIO(text),dialect)) if any(r)]
        result['sheets']=[{'name':'数据','rows':rows}]
    elif ext=='.json':
        items=json.loads(raw)
        if not isinstance(items,list) or not items or not all(isinstance(x,dict) for x in items): raise ValueError('JSON 需要是非空对象数组')
        headers=list(dict.fromkeys(k for r in items for k in r))
        result['sheets']=[{'name':'数据','rows':[{'row':1,'cells':headers}]+[{'row':i+2,'cells':['' if r.get(k) is None else str(r.get(k,'')) for k in headers]} for i,r in enumerate(items)]}]
    elif ext in ['.png','.jpg','.jpeg','.webp','.gif']:
        result['assets']=[asset(Path(name).name,raw)]
        result['gaps'].append('图片已接收；压字 OCR 和产品识别尚未接通')
    elif ext=='.zip':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            files=[x for x in z.infolist() if not x.is_dir() and not x.filename.startswith('__MACOSX/')]
            for x in files:
                if Path(x.filename).suffix.lower() in ['.png','.jpg','.jpeg','.webp','.gif']:
                    result['assets'].append(asset(x.filename,z.read(x)))
            result['inventory']=[x.filename for x in files]
        result['gaps'].append('压缩包仅整理图片目录；不会默认把所有图片与每条文案配对。包内表格请单独上传')
    else:
        result['gaps'].append('该格式只留原文件，本版不解析；可导出 XLSX / CSV，或复制表格粘贴')
    for a in result['assets']: a['source_hash']=digest
    if len(result['assets'])>100: raise ValueError('单次最多 100 张图片，请拆分导入')
    return result

class MediaPlanStore:
    def __init__(self,folder):
        self.folder=Path(folder)/'media-plan';self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/'files').mkdir(exist_ok=True);(self.folder/'history').mkdir(exist_ok=True)
    def state(self):
        p=self.folder/'state.json'
        return json.loads(p.read_text()) if p.exists() else {'revision':0,'state':None}
    def upload(self,body):
        raw=base64.b64decode(body['data'],validate=True)
        obj=parse_file(body['name'],raw)
        # Content addressed files never execute or share originals through HTTP.
        p=self.folder/'files'/obj['sha256']
        if not p.exists(): p.write_bytes(raw)
        obj['stored_locally']=True
        return obj
    def save(self,body):
        old=self.state()
        if body.get('revision')!=old['revision']: raise ValueError('另一页面已更新，请刷新后继续')
        s=body.get('state')
        if not isinstance(s,dict) or s.get('demo') or s.get('project')!='demo' or s.get('account')!='demo-DE':
            raise ValueError('本地真实测试区仅用于 demo / demo-DE；演示与其他账户不能写入')
        value={'revision':old['revision']+1,'state':s,'saved_at':datetime.now(timezone.utc).isoformat()}
        raw=json.dumps(value,ensure_ascii=False,indent=2)
        with (self.folder/'history'/f"{value['revision']:06d}.json").open('x') as f:f.write(raw)
        temp=self.folder/'state.tmp';temp.write_text(raw);os.replace(temp,self.folder/'state.json')
        return value
