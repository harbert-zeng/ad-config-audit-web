"""Fail closed on unexpected tracked files or common credential/data patterns."""
from pathlib import Path
import json,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'SOURCE_FILES.json').read_text())
allowed=set(manifest['source_files'])|{'SOURCE_FILES.json','.gitignore','README.md','PRIVACY.md','requirements-dev.txt','dist/data.json','tools/generate_demo.py','tools/check_share.py'}
tracked=subprocess.run(['git','ls-files','-z'],cwd=ROOT,text=True,capture_output=True)
paths=set(tracked.stdout.split('\0'))-{''} if tracked.returncode==0 else {str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'local-data' not in p.parts}
errors=[]
patterns={
 'credential':r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|EA[A-Za-z0-9]{60,}|sk-[A-Za-z0-9_-]{20,})',
 'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
 'long_object_id':r'(?<!\d)\d{11,}(?!\d)',
 'machine_path':'/'+r'(?:Users|home|var/folders)/[^\s]+',
 'private_source':r'(?i)(?:feishu\.cn|larksuite\.com|fbcdn\.net|cdninstagram\.com)',
}
for path in sorted(paths):
 if path not in allowed: errors.append(f'Unexpected file: {path}');continue
 s=(ROOT/path).read_text()
 for label,pattern in patterns.items():
  if re.search(pattern,s):errors.append(f'{path}: {label}')
d=json.loads((ROOT/'dist/data.json').read_text())
assert d['demo'] is True and d['account_id']=='DEMO-ACCOUNT'
for group in ['campaigns','adsets','ads']:
 for obj in d[group]: assert obj['id'].startswith('DEMO-')
for ad in d['ads']: assert all(url.startswith('https://example.com/') for url in ad['landing_urls'])
if errors: print('\n'.join(errors));sys.exit(1)
print(f'PASS: {len(paths)} files checked against allowlist and privacy patterns; synthetic fixture verified.')
