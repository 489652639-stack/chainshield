"""Signed data-only maintenance policy. No downloaded Python/JavaScript is executed."""
import copy
import json
import re
import threading
import time

VERSION_CODE = 7
DEFAULT = {
    'paths': {'goplus_evm': '/api/v1/token_security/{chain}',
              'goplus_sol': '/api/v1/solana/token_security',
              'honeypot': '/v2/IsHoneypot',
              'rugcheck': '/v1/tokens/{address}/report'},
    'disabled': [], 'aliases': {}, 'translations': {}, 'sol_fee_unit': 'ratio',
}
_lock = threading.RLock()
_config = copy.deepcopy(DEFAULT)
_health = {}
_revision = '内置配置'
PATHS = {
    'goplus_evm': r'/api/v[1-9][0-9]?/token_security/\{chain\}',
    'goplus_sol': r'/api/v[1-9][0-9]?/solana/token_security',
    'honeypot': r'/v[1-9][0-9]?/IsHoneypot',
    'rugcheck': r'/v[1-9][0-9]?/tokens/\{address\}/report',
}
PROVIDERS = ('GoPlus', 'Honeypot.is', 'RugCheck')


def chinese(value):
    return isinstance(value, str) and bool(re.search(r'[\u3400-\u9fff]', value))


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT):
        raise ValueError('维护配置格式不受支持')
    config = copy.deepcopy(DEFAULT)
    paths = value.get('paths', {})
    if not isinstance(paths, dict) or set(paths) - set(PATHS):
        raise ValueError('接口路径不受支持')
    for key, path in paths.items():
        if not isinstance(path, str) or not re.fullmatch(PATHS[key], path):
            raise ValueError('接口路径校验失败')
        config['paths'][key] = path
    disabled = value.get('disabled', [])
    if not isinstance(disabled, list) or any(x not in PROVIDERS for x in disabled):
        raise ValueError('停用来源配置无效')
    config['disabled'] = list(dict.fromkeys(disabled))
    aliases = value.get('aliases', {})
    if not isinstance(aliases, dict) or len(aliases) > 4:
        raise ValueError('字段适配配置无效')
    for scope, mapping in aliases.items():
        if scope not in ('evm', 'sol', 'honeypot', 'rugcheck') or not isinstance(mapping, dict) or len(mapping) > 40:
            raise ValueError('字段适配范围无效')
        for old, new in mapping.items():
            if not all(isinstance(x, str) and re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', x) for x in (old, new)):
                raise ValueError('字段名称无效')
        config['aliases'][scope] = dict(mapping)
    translations = value.get('translations', {})
    if not isinstance(translations, dict) or len(translations) > 200:
        raise ValueError('中文词库配置无效')
    for key, text in translations.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 120 or not chinese(text) or len(text) > 400:
            raise ValueError('中文词库内容无效')
    config['translations'] = dict(translations)
    unit = value.get('sol_fee_unit', DEFAULT['sol_fee_unit'])
    if unit not in ('ratio', 'basis_points', 'unknown'):
        raise ValueError('费率单位配置无效')
    config['sol_fee_unit'] = unit
    return config


def validate_channel(payload, version_code=VERSION_CODE, floor=0, now=None):
    """Called only AFTER native RSA verification of the exact UTF-8 payload bytes."""
    if not isinstance(payload, str) or len(payload.encode('utf-8')) > 65536:
        raise ValueError('维护数据过大')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('维护数据包含重复字段')
            result[key] = value
        return result
    obj = json.loads(payload, object_pairs_hook=unique)
    if not isinstance(obj, dict) or obj.get('schema') != 1:
        raise ValueError('维护数据版本不兼容')
    for key in ('sequence', 'issued_at', 'expires_at', 'minimum_app_code'):
        if type(obj.get(key)) is not int: raise ValueError('维护数据缺少有效版本或时间')
    timestamp = int(time.time()) if now is None else now
    if obj['sequence'] < floor or obj['sequence'] <= 0:
        raise ValueError('已拒绝旧版维护配置')
    if obj['minimum_app_code'] > version_code:
        raise ValueError('请先安装新版应用再更新维护配置')
    if not obj['issued_at'] <= timestamp + 300 or not obj['issued_at'] < obj['expires_at'] <= obj['issued_at'] + 31 * 86400 or obj['expires_at'] <= timestamp:
        raise ValueError('维护配置已过期或设备时间不正确')
    obj['config'] = validate_config(obj.get('config', {}))
    app = obj.get('app', {})
    if not isinstance(app, dict): raise ValueError('应用更新信息无效')
    if app:
        if type(app.get('version_code')) is not int or app['version_code'] <= 0:
            raise ValueError('应用版本信息无效')
        if not isinstance(app.get('version_name'), str) or len(app['version_name']) > 30:
            raise ValueError('应用版本名称无效')
        if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/tag/[A-Za-z0-9_.-]+', str(app.get('release_url', ''))):
            raise ValueError('应用发布地址不受支持')
        if not re.fullmatch(r'[a-f0-9]{64}', str(app.get('sha256', ''))):
            raise ValueError('安装包校验信息无效')
        notes = app.get('notes_zh', '')
        if not chinese(notes) or len(notes) > 1500: raise ValueError('更新说明必须为中文')
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def configure(raw='{}', revision='内置配置'):
    global _config, _revision
    new = validate_config(json.loads(raw))
    with _lock:
        changed = new != _config
        _config, _revision = new, str(revision)
    return changed


def snapshot():
    with _lock: return copy.deepcopy(_config)


def path(key, **parts):
    return snapshot()['paths'][key].format(**parts)


def enabled(provider):
    if provider in snapshot()['disabled']:
        raise ValueError('该数据源正在维护，相关结果保持未知')


def adapt(scope, data):
    result = copy.deepcopy(data)
    for canonical, alias in snapshot()['aliases'].get(scope, {}).items():
        # A new field never overwrites an existing value or a known risk.
        if canonical not in result and alias in result: result[canonical] = result[alias]
    if scope == 'sol': result['_fee_unit'] = snapshot()['sol_fee_unit']
    return result


def before_request(host):
    with _lock:
        state = _health.get(host, {})
        if state.get('until', 0) > time.monotonic():
            raise ValueError('该接口连续失败，正在短暂冷却，请稍后重试')


def record(host, ok):
    with _lock:
        old = _health.get(host, {})
        failures = 0 if ok else old.get('failures', 0) + 1
        _health[host] = {'failures': failures,
                         'until': time.monotonic() + 30 if failures >= 3 else 0,
                         'state': '可用' if ok else '暂不可用'}


def health_json():
    with _lock:
        return json.dumps({'revision': _revision, 'sources': {
            host: {'state': row['state'], 'failures': row['failures'],
                   'cooling': row['until'] > time.monotonic()} for host, row in _health.items()
        }}, ensure_ascii=False)


TRANSLATIONS = {
    'Mint Authority still enabled': ('增发权限仍然启用', '管理员仍可能增发代币，影响持有比例。'),
    'Freeze Authority still enabled': ('冻结权限仍然启用', '管理员可能冻结代币账户，影响转账。'),
    'Mutable metadata': ('代币资料可修改', '名称、图标或资料仍可能被修改，请核对项目身份。'),
    'Token metadata mutable': ('代币资料可修改', '代币资料仍可修改，请防范名称或标识冒用。'),
    'LP Unlocked': ('流动性未锁定', '检测来源报告流动性未锁定，需关注撤出流动性的风险。'),
    'Large Amount of LP Unlocked': ('大量流动性未锁定', '检测来源报告较多流动性未锁定，请核实撤池风险。'),
    'Low Liquidity': ('流动性较低', '交易深度可能不足，买卖可能出现较大滑点。'),
    'Low LP Providers': ('流动性提供者较少', '流动性集中于较少提供者，请关注撤池风险。'),
    'Top 10 holders high ownership': ('前十大持有人占比较高', '筹码较集中，请关注大额抛售风险。'),
    'Single holder ownership': ('单一持有人占比较高', '持币集中于单一地址，请核查地址身份。'),
    'High transfer fee': ('转账手续费较高', '检测来源报告较高转账费用，请核实实际扣费。'),
    'High amount of LP unlocked': ('大量流动性未锁定', '流动性可能被撤出，请核实交易池情况。'),
    'HIGH_BUY_TAX': ('买入税较高', '模拟报告提示买入税较高，请核对交易费用。'),
    'HIGH_SELL_TAX': ('卖出税较高', '模拟报告提示卖出税较高，请核对实际卖出条件。'),
    'high': ('高风险提示', '检测来源报告一项高风险，请核对完整报告。'),
}


def localize_checks(checks):
    terms = {'Hook': '钩子', 'RugPull': '撤池跑路', 'delegatecall': '委托调用', 'Gas': '网络执行费', 'detectedAt': '记录时间字段', 'Token-2022': '代币扩展标准', 'Solana': '索拉纳', 'Mint': '铸币', 'EVM': '兼容以太坊', 'DEX': '去中心化交易池', 'LP': '流动性凭证'}
    custom = snapshot()['translations']
    for row in checks:
        raw_title = str(row.get('title', ''))
        entry = TRANSLATIONS.get(raw_title)
        if raw_title in custom:
            row['title'] = custom[raw_title]
            row['detail'] = custom.get(str(row.get('detail', '')), entry[1] if entry else '检测来源返回此风险项，请打开原始报告核对具体条件。')
        elif entry:
            row['title'], row['detail'] = entry
        elif not chinese(raw_title):
            row['title'] = '第三方风险提示（类型待核实）'
            row['detail'] = '检测来源返回未收录的风险类型，暂无法提供经过核验的中文说明，请打开原始报告核对。'
        elif not chinese(row.get('detail')):
            row['detail'] = '检测来源未提供可核验的中文说明，请打开原始报告核对。'
        for key in ('title', 'detail'):
            for old, new in terms.items(): row[key] = row[key].replace(old, new)
            remaining = row[key]
            for name in ('Honeypot.is', 'Honeypot', 'GoPlus', 'RugCheck', 'BNB', 'SOL', 'ETH'):
                remaining = remaining.replace(name, '')
            remaining = re.sub(r'0x[a-fA-F0-9]+|[1-9A-HJ-NP-Za-km-z]{32,44}', '', remaining)
            if re.search(r'[a-zA-Z]{2,}', remaining):
                row[key] = '第三方风险提示（类型待核实）' if key == 'title' else '检测来源返回了尚未收录中文说明的信息，请打开原始报告核查；本项风险等级保持不变。'
    return checks
