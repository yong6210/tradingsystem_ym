"""Bounded, unauthenticated GET transport for E021 public paper receipts."""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request


CHANNELS = {'/fapi/v1/time':'SERVER_TIME', '/fapi/v1/klines':'KLINES',
            '/fapi/v1/ticker/bookTicker':'QUOTE', '/fapi/v1/premiumIndex':'PREMIUM',
            '/fapi/v1/fundingRate':'FUNDING_HISTORY'}
LIMITS = dict(total_seconds=180,observe_seconds=45,poll_seconds=5,requests=100,
              warmup_pages=40,rows_per_page=1000,response_bytes=512*1024,total_raw_bytes=16*1024*1024)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('public redirects disabled')


def save(path, data):
    with path.open('x') as stream:
        json.dump(data,stream,indent=2,allow_nan=False)
        stream.write('\n')


class PublicRest:
    def __init__(self,output):
        self.output = output
        self.count = self.bytes = 0
        self.deadline = time.monotonic()+LIMITS['total_seconds']
        self.opener = urllib.request.build_opener(NoRedirect())
        (output/'raw').mkdir()

    def get(self,path,params=None):
        if path not in CHANNELS:
            raise ValueError('not an allowed public path')
        params = params or {}
        allowed = {'SERVER_TIME':set(),'KLINES':{'symbol','interval','startTime','limit'},
                   'QUOTE':{'symbol'},'PREMIUM':{'symbol'},
                   'FUNDING_HISTORY':{'symbol','startTime','endTime','limit'}}[CHANNELS[path]]
        if set(params)!=allowed or (allowed and params.get('symbol')!='BTCUSDC'):
            raise ValueError('unexpected public query fields or symbol')
        if self.count>=LIMITS['requests'] or self.deadline-time.monotonic()<5:
            raise ValueError('fixed request/time budget reached')
        self.count += 1
        rid = f'{self.count:04d}'
        url = 'https://fapi.binance.com'+path
        if params:url += '?'+urllib.parse.urlencode(params)
        c = dict(request_started_ns=time.monotonic_ns(),request_started_utc_ns=time.time_ns())
        raw = b'';status = None;error = None
        try:
            with self.opener.open(url,timeout=5) as response:
                status = response.status
                raw = response.read(LIMITS['response_bytes']+1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read(LIMITS['response_bytes']+1)
            exc.close()
            error = 'HTTP_'+str(status)
        except Exception as exc:
            error = type(exc).__name__+': '+str(exc)
        c.update(received_ns=time.monotonic_ns(),received_utc_ns=time.time_ns())
        if len(raw)>LIMITS['response_bytes']:error = 'RESPONSE_BYTE_LIMIT'
        self.bytes += len(raw)
        with (self.output/'raw'/f'{rid}.body').open('xb') as stream:stream.write(raw)
        receipt = dict(request_id=rid,path=path,url=url,query=params,status=status,error=error,
                       clock=c,sha256=hashlib.sha256(raw).hexdigest(),raw_file=f'raw/{rid}.body')
        save(self.output/'raw'/f'{rid}.receipt.json',receipt)
        if self.bytes>LIMITS['total_raw_bytes'] or time.monotonic()>self.deadline:
            raise ValueError('total public resource limit')
        if status in (418,429):raise ValueError('public rate limit: stop without retries')
        return receipt,raw


def ingest(rest,store,path,params=None,session='one'):
    receipt,raw = rest.get(path,params)
    channel = CHANNELS[path]
    error = receipt['error']
    try:text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = '';error = 'NON_UTF8_RESPONSE'
    if error or receipt['status']!=200:
        text = json.dumps(dict(channel=channel,error=error or 'HTTP_'+str(receipt['status'])))
        channel = 'FEED_ERROR'
    return store.commit(receipt['request_id'],channel,text,receipt['clock'],session,params)


def funding_query(state):
    return dict(symbol='BTCUSDC',startTime=state['scan_start_ms'],
                endTime=time.time_ns()//1000000-1000,limit=100)


def receive_cycle(rest,store):
    next_ms = store.state()['account']['signal']['state']['last_open_ms']+60000
    ingest(rest,store,'/fapi/v1/klines',dict(symbol='BTCUSDC',interval='1m',startTime=next_ms,limit=3))
    ingest(rest,store,'/fapi/v1/premiumIndex',dict(symbol='BTCUSDC'))
    ingest(rest,store,'/fapi/v1/fundingRate',funding_query(store.state()))
    return ingest(rest,store,'/fapi/v1/ticker/bookTicker',dict(symbol='BTCUSDC'))
