"""Verify frozen-model new-period results and publish a local report section."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import verify_recycling_portfolio as verifier
from scripts.build_recycling_portfolio_report import LABELS
OUT=ROOT/'reports/validation/additional_btc_2023_2024_20260917'
APP=ROOT/'reports/validation/user_btcusdt_20260917/report-app'

def main():
 data=json.loads((OUT/'results.json').read_text());plan=data['protocol']
 assert hashlib.sha256((ROOT/'data/historical/btcusdt_2023_2024_oct_additional/manifest.json').read_bytes()).hexdigest()==plan['additional_manifest_sha256']
 assert hashlib.sha256((ROOT/'scripts/run_additional_btc_validation.py').read_bytes()).hexdigest()==plan['runner_sha256']
 old=json.loads((ROOT/plan['source_protocol']).read_text())
 assert plan['cases']==old['cases'] and plan['selected']==old['selected'] and plan['rules']==old['rules']
 verifier.OUT=OUT;verifier.main()
 checks=json.loads((OUT/'verification.json').read_text())
 checks.update(unchanged_cases_and_weights='PASS',additional_manifest_hash='PASS',runner_hash='PASS',caveats=plan['interpretation']+' Real BTCUSDC fill probability is not verified.')
 (OUT/'verification.json').write_text(json.dumps(checks,indent=2))
 rows=[]
 for k,label in LABELS.items():
  a,b=data['results']['2023'][k],data['results']['2024_Jan_Oct'][k]
  rows.append(dict(strategy=label,case=k,return2023=a['return_pct'],return2024=b['return_pct'],dd2023=a['max_drawdown_bound_pct'],dd2024=b['max_drawdown_bound_pct']))
 mixed=data['results']['2023']['allocated_hybrid'];mixed24=data['results']['2024_Jan_Oct']['allocated_hybrid']
 stress=data['results']['2023']['allocated_hybrid_stress'];stress24=data['results']['2024_Jan_Oct']['allocated_hybrid_stress']
 summary=f'''## 추가 표본 검증: 2023~2024년

새로 받은 23개 ZIP, 1,009,440개 1분봉의 파일별 검증이 통과했습니다. 2024년 11월은 미제공입니다. 2023년 1월~2024년 10월의 연속 22개월만 백테스트에 사용하고, 2024년 12월은 별도 보관했습니다. 이전 20개월과 합치면 제공 표본은 43개월이며, 아직 44개월 연속 자료는 아닙니다.

기존 모델·비중·비용·주문 규칙을 바꾸지 않고 10개 조건을 두 기간에 실행했습니다. 2023년은 동일한 34일 준비 구간을 제외한 2월 4일~12월 31일, 2024년은 1월 1일~10월 31일입니다. 기간마다 자본을 10,000으로 초기화하므로 두 수익률을 연결한 결과가 아닙니다.

혼합 진입 조합 수익률은 2023년 {mixed['return_pct']:+.2f}%, 2024년 1~10월 {mixed24['return_pct']:+.2f}%입니다. 비용·체결 스트레스에서는 각각 {stress['return_pct']:+.2f}%, {stress24['return_pct']:+.2f}%입니다.

2025~2026년 자료로 정한 모델을 더 이른 시기에 적용한 추가 기간 검증입니다. 이번 실험에 새로 제공된 표본이지만 시간 순서상 미래 전진 검증은 아닙니다. 결과를 보고 후보나 비중을 재선정하지 않았습니다. BTCUSDT 자료는 BTCUSDC 무기한의 실제 호가·체결·펀딩을 대체하지 못합니다.'''
 text='# 추가 BTC 표본과 고정 모델 검증 — 2026-09-17\n\n'+summary+'\n\n'
 text+='| 모델 | 2023 수익률 | 2023 낙폭 추정 | 2024 1~10월 수익률 | 2024 낙폭 추정 |\n|---|---:|---:|---:|---:|\n'
 for r in rows:text+=f"| {r['strategy']} | {r['return2023']:+.2f}% | {r['dd2023']:.2f}% | {r['return2024']:+.2f}% | {r['dd2024']:.2f}% |\n"
 text+='''
## 데이터 검증과 해석 범위

- 2023-01~2024-10: 22개 파일, 964,800분. 완전 연속, 중복·누락·잘못된 OHLC·음수 거래량·시각 단위 오류 없음.
- 2024-12: 1개 파일, 44,640분. 파일 자체는 완전하지만 11월 누락으로 앞 구간과 연결하지 않았다. 독립된 12월은 기존 34일 준비 구간보다 짧아 이번 동일 조건 백테스트에서 제외했다.
- ZIP 해시, 12열 구조, 분봉 시작·종료 시각, 월별 예상 행 수, 유한 수치, 고가·저가 제약, 총거래량·매수체결량 관계를 검증했다. 제공 파일이 실제 거래소 원본인지 독립 대조한 것은 아니다.
- 기존 전략 소스 해시와 10개 실험 조건·비중·비용 설정이 동일함을 확인했다. 20개 실행의 잔액·평균단가·수량·수수료·펀딩·월별 복리·사이클 손익을 별도 원장으로 재계산했다.
- 낙폭은 분봉 내 불리한 전략별 평가 합계 기반 추정이며 정확한 틱 낙폭이 아니다. 이전 모델과 지표·비중을 다시 맞추지 않았다. 각 기간의 손익은 독립 초기화 결과이다.

추가로 필요한 파일: `/Users/yumin/Downloads/BTCUSDT-1m-2024-11.zip`. 이를 받으면 2023~2026년 자료의 월 단위 연결을 검사할 수 있다. 결측 구간을 임의의 봉으로 보간하지 않았다.

재현: `scripts/validate_additional_btc_archives.py`, `scripts/run_additional_btc_validation.py`, `scripts/report_additional_btc_validation.py`. 결과·고정 프로토콜·행별 원장·검증·CSV: `reports/validation/additional_btc_2023_2024_20260917/`. 데이터 품질 기록: `data/historical/btcusdt_2023_2024_oct_additional/manifest.json`, `data/historical/btcusdt_2024_dec_additional/manifest.json`.
'''
 (ROOT/'docs/ADDITIONAL_BTC_VALIDATION_2026_09_17.md').write_text(text)
 dp=APP/'src/data.json';d=json.loads(dp.read_text());d['buildStatus']='updating'
 d['queries']['additional_comparison']=dict(rows=rows,source=dict(label='추가 제공 2023~2024 BTCUSDT · 고정 모델 비교',
  files=['reports/validation/additional_btc_2023_2024_20260917/results.json','reports/validation/additional_btc_2023_2024_20260917/protocol.json','reports/validation/additional_btc_2023_2024_20260917/verification.json','data/historical/btcusdt_2023_2024_oct_additional/manifest.json'],
  filters=['2023-02-04~2023-12-31 UTC','2024-01-01~2024-10-31 UTC','2024년 11월 미제공, 12월 단독 자료 제외'],
  evidenceFlow=[dict(title='자료와 해석',detail=text),dict(title='고정 규칙',detail=json.dumps(plan['rules'],ensure_ascii=False,indent=2))],
  metricDefinitions=[dict(label='수익률',definition='각 독립 구간의 청산 후 자산/10,000−1, 백분율. 시장가 비용 포함.'),dict(label='낙폭 추정',definition='이전 분봉 종가 고점 대비 전략별 불리한 분봉 평가 합계. 틱 기준 최대낙폭과 다름.')]),
  methods=[dict(language='python',code='scripts/run_additional_btc_validation.py; unchanged cases from recycling_portfolio_20260917/protocol.json; independent ledger verification in scripts/report_additional_btc_validation.py')])
 dp.write_text(json.dumps(d,ensure_ascii=False,indent=2))
 p=APP/'src/content/report/ReportContent.jsx';s=p.read_text();start='  {/* ADDITIONAL_VALIDATION_START */}';end='  {/* ADDITIONAL_VALIDATION_END */}'
 if start in s:s=s[:s.index(start)]+s[s.index(end)+len(end):]
 jsx=start+'\n'+f'  <ReportSection id="additional-summary" queryId="additional_comparison" sourceRows={{snapshot.queries.additional_comparison.rows}} title="追加 표본 검증" showHeading={{false}}><RichNarrative id="additional-summary:body" value={{{json.dumps(summary,ensure_ascii=False)}}}/></ReportSection>\n'
 jsx+="  {table('additional-results','추가 표본 · 고정 모델 수익률과 낙폭',snapshot.queries.additional_comparison.rows,[{field:'strategy',label:'모델'},{field:'return2023',label:'2023 수익 (%)',renderCell:num},{field:'dd2023',label:'2023 낙폭 (%)',renderCell:num},{field:'return2024',label:'2024 수익 (%)',renderCell:num},{field:'dd2024',label:'2024 낙폭 (%)',renderCell:num}],'additional_comparison',true)}\n"+end+'\n'
 jsx=jsx.replace('追加 표본','추가 표본');s=s.replace('  {/* RECYCLING_RESEARCH_START */}',jsx+'\n  {/* RECYCLING_RESEARCH_START */}');p.write_text(s)
 d['buildStatus']='complete';dp.write_text(json.dumps(d,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
