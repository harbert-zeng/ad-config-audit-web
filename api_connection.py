"""Local connection setup; credentials live in process memory only."""
import json
import re
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlparse, parse_qsl, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Connection:
    def __init__(self, folder):
        self.path = folder / 'api-connection.json'
        self.config = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.secret = ''

    def view(self):
        return {'config': self.config, 'credential_loaded': bool(self.secret)}

    def save(self, body):
        mode = body.get('mode', 'meta')
        auth = body.get('auth', 'bearer')
        if mode not in ('meta', 'custom') or auth not in ('bearer', 'api-key'):
            raise ValueError('请选择接口类型和认证方式。')
        config = {'mode': mode, 'auth': auth}
        if mode == 'meta':
            version = body.get('version', '').strip()
            creative = body.get('creative_id', '').strip()
            if not re.fullmatch(r'v\d+\.\d+', version):
                raise ValueError('请按接口提供方说明填写版本，例如 v26.0。')
            if not re.fullmatch(r'\d+', creative):
                raise ValueError('请填写数字格式的 Creative ID。')
            config.update(version=version, creative_id=creative, auth='bearer')
            config['url'] = f'https://graph.facebook.com/{version}/{creative}?' + urlencode({'fields': 'id,degrees_of_freedom_spec'})
        else:
            url = body.get('url', '').strip()
            parsed = urlparse(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError('填写完整 HTTPS 只读接口地址；认证信息请放在密钥栏。')
            if any(k.lower() in ('access_token', 'token', 'api_key', 'apikey', 'key', 'secret', 'authorization') for k, _ in parse_qsl(parsed.query)):
                raise ValueError('请移除地址里的密钥，改填下方密钥栏。')
            config['url'] = url
        secret = body.get('secret', '').strip()
        if any(c in secret for c in ('\r', '\n')):
            raise ValueError('密钥不能包含换行。')
        # Changing destinations must never carry an old credential to a new service.
        if self.config.get('url') != config['url'] or self.config.get('auth') != config['auth']:
            self.secret = ''
        if secret:
            self.secret = secret
        self.config = config
        self.path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
        self.path.chmod(0o600)
        return self.view()

    def clear(self):
        self.secret = ''
        return self.view()

    def probe(self, body):
        """Read Graph configuration only; never accepts URLs, tokens or mutations."""
        if not self.secret or self.config.get('mode') != 'meta':
            raise ValueError('请先在配置页载入 Meta API 密钥。')
        node = str(body.get('node', ''))
        if not re.fullmatch(r'(?:\d+|act_\d+)(?:/(?:ads|adcreatives|previews))?', node):
            raise ValueError('只允许读取广告对象、广告列表、素材列表或预览。')
        params = body.get('params', {})
        allowed = {'fields', 'limit', 'after', 'filtering', 'metadata', 'ad_format', 'creative_feature'}
        if not isinstance(params, dict) or set(params) - allowed:
            raise ValueError('只允许配置查询参数。')
        if any(not isinstance(v, (str, int)) or len(str(v)) > 15000 for v in params.values()):
            raise ValueError('查询参数格式有误。')
        version = body.get('version', self.config['version'])
        if not re.fullmatch(r'v\d+\.\d+', version):
            raise ValueError('API 版本格式有误。')
        url = f'https://graph.facebook.com/{version}/{node}?' + urlencode(params)
        req = Request(url, headers={'Authorization': 'Bearer ' + self.secret, 'Accept': 'application/json'}, method='GET')
        http_status = 200
        try:
            with build_opener(NoRedirect()).open(req, timeout=30) as response:
                http_status = response.status
                raw = response.read(8_000_001)
        except HTTPError as e:
            http_status = e.code
            raw = e.read(8_000_001)
        except (URLError, TimeoutError, OSError):
            return {'ok': False, 'http_status': None, 'error': '网络错误或超时；未判定为权限/字段限制。'}
        if len(raw) > 8_000_000:
            raise ValueError('返回过大，请减小读取数量。')
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {'ok': False, 'http_status': http_status, 'error': '非 JSON 响应，未记录正文。'}
        def sanitize(value):
            if isinstance(value, dict):
                # Graph pagination URLs can embed access tokens; retain cursors, not URLs.
                return {k: sanitize(v) for k, v in value.items() if k.lower() not in ('access_token', 'authorization', 'secret', 'token', 'previous', 'next')}
            if isinstance(value, list):
                return [sanitize(v) for v in value]
            if isinstance(value, str):
                value = value.replace(self.secret, '[REDACTED]')
                value = re.sub(r'(?i)(access_token|appsecret_proof|api_key)=([^&\s"<>]+)', r'\1=[REDACTED]', value)
            return value
        result = {'ok': 200 <= http_status < 300 and not (isinstance(data, dict) and data.get('error')),
                  'captured_at': datetime.now(timezone.utc).isoformat(), 'api_version': version,
                  'node': node, 'params': sanitize(params), 'http_status': http_status,
                  'has_next': bool(isinstance(data, dict) and data.get('paging', {}).get('next')),
                  'response': sanitize(data)}
        folder = self.path.parent / 'api-probes'
        folder.mkdir(exist_ok=True, mode=0o700)
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8] + '.json'
        path = folder / name
        with path.open('x') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        path.chmod(0o600)
        result['evidence_file'] = name
        return result

    def test(self):
        if not self.secret:
            raise ValueError('请填写密钥并保存；重启本地服务后需要重新填写。')
        header = {'Authorization': 'Bearer ' + self.secret} if self.config['auth'] == 'bearer' else {'X-API-Key': self.secret}
        req = Request(self.config['url'], headers={**header, 'Accept': 'application/json'}, method='GET')
        try:
            with build_opener(NoRedirect()).open(req, timeout=20) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError('返回内容过大；请使用单条素材的测试接口。')
                data = json.loads(raw)
        except HTTPError as e:
            messages = {401:'认证失败，请检查密钥。', 403:'接口拒绝访问，请检查账户权限。', 429:'请求过于频繁，请稍后再试。'}
            return {'ok': False, 'message': messages.get(e.code, f'接口返回 HTTP {e.code}；未保存响应正文。')}
        except (URLError, TimeoutError, OSError):
            return {'ok': False, 'message': '连接失败或超时，请检查接口地址和网络。'}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {'ok': False, 'message': '接口返回的不是 JSON 数据，请检查读取地址。'}
        if isinstance(data, dict) and data.get('error'):
            return {'ok': False, 'message': '接口返回业务错误，请在接口提供方核对认证和请求参数。'}
        spec = data.get('degrees_of_freedom_spec', {}) if isinstance(data, dict) else {}
        features = spec.get('creative_features_spec', {}) if isinstance(spec, dict) else {}
        rows = []
        if isinstance(features, dict):
            for key, value in features.items():
                state = value.get('enroll_status') if isinstance(value, dict) else None
                # Do not return arbitrary server content or credentials to the browser.
                if re.fullmatch(r'[a-z_0-9]{1,100}', key) and self.secret not in key:
                    rows.append({'field': key, 'state': state if state in ('OPT_IN', 'OPT_OUT') else 'UNKNOWN'})
        return {'ok': True, 'message': '连接成功，已读取增强功能字段。' if rows else '连接成功，但本次未读到标准路径下的增强功能字段；不能视为全部关闭。', 'features': rows, 'scope': '仅测试单次接口读取，尚未接入每日报告；字段与九项后台名称仍需核验。'}
