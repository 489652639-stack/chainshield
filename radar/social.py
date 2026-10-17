"""Public person-message intake. A saved GMGN watchlist is not a data feed."""
import hashlib
import math
import re
from urllib.parse import urlsplit

# Exact accounts verified in the user's GMGN list. No lookalike aeyakovenko123.
WATCHLIST = [
    ('X', 'elonmusk', '马斯克'), ('X', 'cz_binance', 'CZ'),
    ('X', 'vitalikbuterin', 'Vitalik'), ('X', 'heyibinance', '何一'),
    ('X', 'justinsuntron', '孙宇晨'), ('X', 'brian_armstrong', 'Brian Armstrong'),
    ('X', 'rajgokal', 'Raj Gokal'), ('X', 'cryptohayes', 'Arthur Hayes'),
    ('X', 'balajis', 'Balaji'), ('X', 'realdonaldtrump', '特朗普 · X'),
    ('TRUTH_SOCIAL', 'realdonaldtrump', '特朗普 · Truth Social'),
    ('X', 'erictrump', 'Eric Trump'), ('X', 'donaldjtrumpjr', 'Donald Trump Jr.'),
    ('X', 'davidsacks', 'David Sacks'), ('X', 'binance', '币安'),
    ('X', 'binancezh', '币安中文'), ('X', 'coinbase', 'Coinbase'),
    ('X', 'coinbaseassets', 'Coinbase 资产公告'), ('X', 'solana', 'Solana'),
    ('X', 'jupiterexchange', 'Jupiter'),
]
ACTORS = {(platform, handle): name for platform, handle, name in WATCHLIST}


def validate_batch(items, now):
    """Validate entire batch before any writes; do not fetch supplied URLs."""
    if not isinstance(items, list) or not 1 <= len(items) <= 10:
        raise ValueError('每批需要1至10条人物消息')
    clean = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('人物消息格式错误')
        platform = item.get('platform')
        handle = item.get('handle', '')
        if not isinstance(handle, str):
            raise ValueError('人物账号格式错误')
        handle = handle.lstrip('@').casefold()
        if not isinstance(platform, str) or (platform, handle) not in ACTORS:
            raise ValueError('账号未在已核对的20个监控订阅中')
        text = item.get('text')
        published = item.get('published')
        kind = item.get('kind', 'post')
        url = item.get('url', '')
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError('消息正文需要1至4000字')
        if type(published) not in (int, float) or not math.isfinite(published):
            raise ValueError('必须提供真实发布时间，不能使用采集时间代替')
        if not now - 1800 <= published <= now + 60:
            raise ValueError('消息超过30分钟窗口或发布时间异常')
        if kind not in ('post', 'reply', 'quote', 'repost', 'profile'):
            raise ValueError('消息类型无效')
        if not isinstance(url, str) or len(url) > 512:
            raise ValueError('原文地址无效')
        parsed = urlsplit(url)
        host = 'x.com' if platform == 'X' else 'truthsocial.com'
        pattern = (r'/([^/]+)/status/(\d+)' if platform == 'X'
                   else r'/@([^/]+)/posts/(\d+)')
        match = re.fullmatch(pattern, parsed.path)
        if (parsed.scheme != 'https' or parsed.netloc.casefold() != host
                or not match or match[1].casefold() != handle
                or parsed.query or parsed.fragment):
            raise ValueError('需要对应本人账号的HTTPS帖子原文链接')
        event_id = hashlib.sha256((platform + ':' + match[2]).encode()).hexdigest()
        clean.append(dict(id=event_id, platform=platform, handle=handle,
                          name=ACTORS[(platform, handle)], text=text.strip(),
                          published=published, url=url, kind=kind))
    return clean
