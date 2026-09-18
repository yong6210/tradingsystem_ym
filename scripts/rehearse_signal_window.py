"""Offline E022 whole-executor rehearsal. All quotes, bars and clocks are synthetic.

The production executor is called unchanged. Only its external clock and HTTP
opener are replaced; real sockets are blocked. Scheduled public evidence is read
but never written. Each case owns a separate synthetic registration and journal.
"""
import argparse
from contextlib import ExitStack,redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import socket
import sqlite3
import sys
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.observation.t0_signal import T0Signal
from scripts.run_direction_controls import save,load,digest
from scripts.run_signal_window import execute

CASES = ('normal','funding_failure_before_entry','missed_start','insufficient_end_liquidity')


class SyntheticClock:
    def __init__(self,start_ms):
        self.start_ms = start_ms
        self.elapsed_ns = 0
        self.sleeps = []

    def time_ns(self):return self.start_ms*1000000+self.elapsed_ns
    def monotonic_ns(self):return self.elapsed_ns
    def monotonic(self):return self.elapsed_ns/1000000000
    def advance_ms(self,value):self.elapsed_ns += int(value*1000000)
    def sleep(self,seconds):
        if not 0<=seconds<=10:raise ValueError('unexpected executor sleep')
        self.sleeps.append(seconds)
        self.elapsed_ns += int(seconds*1000000000)


class SyntheticResponse:
    def __init__(self,body,status=200):
        self.body = json.dumps(body).encode()
        self.status = status
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.body[:limit]


class SyntheticOpener:
    def __init__(self,clock,target,case,folder):
        self.clock,self.target,self.case,self.folder = clock,target,case,folder
        self.calls = []

    def open(self,url,timeout):
        parsed = urlparse(url)
        if parsed.scheme!='https' or parsed.netloc!='fapi.binance.com' or timeout!=5:
            raise ValueError('unexpected transport request')
        self.clock.advance_ms(50)
        now = self.clock.time_ns()//1000000
        params = {k:v[0] for k,v in parse_qs(parsed.query).items()}
        path = parsed.path
        self.calls.append(dict(path=path,params=params,received_ms=now))
        if path=='/fapi/v1/time':return SyntheticResponse(dict(serverTime=now))
        if path=='/fapi/v1/klines':
            start,limit = int(params['startTime']),int(params['limit'])
            end = min(start+limit*60000,(now//60000+1)*60000)
            bars = [[at,'60100','60200','60000','60150','1',at+59999,'60150',1,'1','60150','0']
                    for at in range(start,end,60000)]
            return SyntheticResponse(bars)
        if path=='/fapi/v1/premiumIndex':
            return SyntheticResponse(dict(symbol='BTCUSDC',time=now-10,markPrice='60150',
                nextFundingTime=self.target+14400000,lastFundingRate='0.0001'))
        if path=='/fapi/v1/fundingRate':
            if self.case=='funding_failure_before_entry' and now>=self.target+55000:
                return SyntheticResponse(dict(error='synthetic HTTP 503'),status=503)
            return SyntheticResponse([])
        if path=='/fapi/v1/ticker/bookTicker':
            qty = '1'
            if self.case=='insufficient_end_liquidity':
                # Fault injection depends only on the already committed END.
                db = sqlite3.connect(f'file:{self.folder}/public/paper.sqlite?mode=ro',uri=True)
                try:state = json.loads(db.execute('SELECT state FROM receipts ORDER BY seq DESC LIMIT 1').fetchone()[0])
                finally:db.close()
                if state['account']['phase']=='STOPPED':qty = '0.0001'
            return SyntheticResponse(dict(symbol='BTCUSDC',bidPrice='60149',askPrice='60150',
                                          bidQty=qty,askQty=qty,time=now-10))
        raise ValueError('unhandled synthetic endpoint: '+path)


def fixture_registration(folder,registered,case):
    target = registered['plan']['target_close_ms']
    signal = T0Signal()
    signal.last_open_ms = target-120000
    signal.bucket = (target-60000)//14400000
    signal.count = 239;signal.high = 60200;signal.low = 60000;signal.completed = 80
    signal.ema20 = 60000.1;signal.ema80 = 60000;signal.atr = 200
    signal.closes = list(range(60000,60021))
    save(folder/'synthetic_seed.json',dict(account=dict(signal=signal.checkpoint())))
    reg = deepcopy(registered)
    reg['classification'] = 'SYNTHETIC_FULL_EXECUTOR_REHEARSAL_NOT_PUBLIC_DATA'
    reg['synthetic_case'] = case
    reg['seed_path'] = str((folder/'synthetic_seed.json').resolve())
    reg['binding']['seed_sha256'] = digest(folder/'synthetic_seed.json')
    reg['binding']['scope'] = 'SYNTHETIC_REHEARSAL_NOT_FORWARD_OR_PERFORMANCE'
    save(folder/'registration.json',reg)
    save(folder/'prepared_verification.json',dict(status='PREPARED_NOT_PUBLICLY_EXECUTED',
        classification=reg['classification'],
        artifact_hashes={name:digest(folder/name) for name in ('registration.json','synthetic_seed.json')}))
    save(folder/'EVIDENCE_KIND.json',dict(classification=reg['classification'],
        synthetic_clock=True,synthetic_market_data=True,real_network_disabled=True,
        note='The child public directory name comes from the unchanged executor; it contains simulated receipts only.'))
    return digest(folder/'prepared_verification.json')


def run_case(folder,registered,case):
    folder.mkdir()
    prepared_sha = fixture_registration(folder,registered,case)
    target = registered['plan']['target_close_ms']
    clock = SyntheticClock(target-(20000 if case=='missed_start' else 120000))
    opener = SyntheticOpener(clock,target,case,folder)
    transcript = io.StringIO()
    with ExitStack() as stack:
        stack.enter_context(patch('time.time_ns',clock.time_ns))
        stack.enter_context(patch('time.monotonic_ns',clock.monotonic_ns))
        stack.enter_context(patch('time.monotonic',clock.monotonic))
        stack.enter_context(patch('time.sleep',clock.sleep))
        stack.enter_context(patch('urllib.request.build_opener',return_value=opener))
        network = stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('REAL NETWORK FORBIDDEN')))
        stack.enter_context(redirect_stdout(transcript))
        execute(folder,prepared_sha)
        network.assert_not_called()
    (folder/'executor.log').write_text(transcript.getvalue())
    summary = load(folder/'public/summary.json')
    outputs = {}
    if case=='missed_start':
        if summary['status']!='MISSED_START_WINDOW' or opener.calls:
            raise ValueError('late start was not refused before transport')
        audit = None
    else:
        audit = load(folder/'public/independent_audit.json')
        verified = load(folder/'public/verification.json')
        outputs = verified['replay']['outputs']
        if verified['replay']['public_raw_matches']!=len(opener.calls):raise ValueError('missing simulated receipts')
        if summary['armed_ms']>=target or summary['public_requests']>100:raise ValueError('timing/request bound')
        if summary['last_received_utc_ns']//1000000-(target-60000)>180000:raise ValueError('active time bound')
        if case=='normal':
            if (summary['entries'],summary['exits'],summary['residual_quantity'],summary['observation_end_exits'])!=(1,1,0,1):
                raise ValueError('normal synthetic lifecycle did not complete')
        elif case=='funding_failure_before_entry':
            if summary['entries']!=0 or 'FUNDING_HISTORY' not in summary['faults']:
                raise ValueError('funding failure did not block entry')
            if not outputs.get('ENTRY_CANCELLED_DATA_GUARD') or not outputs.get('PAPER_VALUATION'):
                raise ValueError('quote/risk observation did not continue')
        elif case=='insufficient_end_liquidity':
            if summary['entries']!=1 or summary['exits']!=0 or summary['residual_quantity']<=0:
                raise ValueError('unfilled exit position was lost')
            if not outputs.get('EXIT_BLOCKED_LIQUIDITY'):raise ValueError('missing exit failure event')
        for entry in audit['entries']:
            if entry['received_ms']<target+60000:raise ValueError('entry before registered schedule')
    result = dict(case=case,status='PASS_SYNTHETIC_ASSERTIONS',real_network_requests=0,
        simulated_requests=len(opener.calls),synthetic_elapsed_seconds=clock.elapsed_ns/1000000000,
        maximum_simulated_sleep_seconds=max(clock.sleeps,default=0),
        account_summary=summary,independent_audit=audit,outputs=outputs)
    save(folder/'rehearsal_result.json',result)
    return result


def main(output):
    scheduled = ROOT/'reports/validation/e022_signal_boundary_20260919'
    registered = load(scheduled/'registration.json')
    protected = dict(registered['source_hashes'])|dict(registered['prior_artifact_hashes'])
    for path in scheduled.rglob('*'):
        if path.is_file():protected[str(path.relative_to(ROOT))] = digest(path)
    for name,h in protected.items():
        if digest(ROOT/name)!=h:raise ValueError('scheduled source/evidence changed: '+name)
    script_hash = digest(Path(__file__))
    save(output/'registration.json',dict(classification='OFFLINE_FULL_EXECUTOR_REHEARSAL',
        cases=CASES,protected_hashes=protected,script_sha256=script_hash,
        synthetic_http_latency_ms=50,real_network_requests_allowed=0,automatic_retries=0))
    (output/'source_snapshot.py').write_bytes(Path(__file__).read_bytes())
    results = [run_case(output/case,registered,case) for case in CASES]
    for name,h in protected.items():
        if digest(ROOT/name)!=h:raise ValueError('scheduled source/evidence changed after rehearsal: '+name)
    if digest(Path(__file__))!=script_hash:raise ValueError('rehearsal implementation changed')
    save(output/'verification.json',dict(status='PASS_FOUR_OFFLINE_EXECUTOR_SCENARIOS',
        cases=len(results),protected_files_unchanged=len(protected),scheduled_public_run_started=(scheduled/'public').exists(),
        real_network_requests=0,simulated_requests=sum(x['simulated_requests'] for x in results),
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file()}))
    print(json.dumps([dict(case=r['case'],status=r['status'],simulated_requests=r['simulated_requests'],
                          target_result=r['account_summary'].get('target_result',r['account_summary']['status']),
                          residual_quantity=r['account_summary'].get('residual_quantity',0)) for r in results],indent=2))


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    output = parser.parse_args().output;output.mkdir(parents=True,exist_ok=False)
    try:main(output)
    except Exception as exc:
        save(output/'failure.json',dict(type=type(exc).__name__,reason=str(exc)))
        raise
