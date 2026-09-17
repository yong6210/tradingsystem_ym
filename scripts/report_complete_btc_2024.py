"""Publish full-2024 validation without replacing earlier experiment evidence."""
from pathlib import Path
import hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import verify_recycling_portfolio as verifier
from scripts.build_recycling_portfolio_report import LABELS
OUT=ROOT/'reports/validation/complete_btc_2024_20260917'
APP=ROOT/'reports/validation/user_btcusdt_20260917/report-app'
def main():
 data=json.loads((OUT/'results.json').read_text());plan=data['protocol']
 manifest_path=ROOT/'data/historical/btcusdt_2023_2026_complete/manifest.json'
 m=json.loads(manifest_path.read_text());assert m['status']=='PASS' and m['file_count']==44 and m['row_count']==1928160
 assert hashlib.sha256(manifest_path.read_bytes()).hexdigest()==plan['additional_manifest_sha256']
 assert hashlib.sha256((ROOT/'scripts/run_complete_btc_2024_validation.py').read_bytes()).hexdigest()==plan['runner_sha256']
 source=json.loads((ROOT/plan['source_protocol']).read_text())
 assert plan['cases']==source['cases'] and plan['rules']==source['rules'] and plan['selected']==source['selected']
 verifier.OUT=OUT;verifier.main()
 checks=json.loads((OUT/'verification.json').read_text());checks.update(full_44_month_manifest='PASS',runner_hash='PASS',unchanged_cases='PASS',caveats=plan['interpretation'])
 (OUT/'verification.json').write_text(json.dumps(checks,indent=2))
 old=json.loads((ROOT/'reports/validation/additional_btc_2023_2024_20260917/results.json').read_text())
 rows=[]
 for k,label in LABELS.items():
  a=old['results']['2023'][k];b=data['results']['2024_full'][k]
  rows.append(dict(case=k,strategy=label,return2023=a['return_pct'],dd2023=a['max_drawdown_bound_pct'],return2024=b['return_pct'],dd2024=b['max_drawdown_bound_pct']))
 base=data['results']['2024_full']['allocated_hybrid'];stress=data['results']['2024_full']['allocated_hybrid_stress']
 summary=f'''## 추가 표본 검증: 누락 월 복구와 2024년 전체

2024년 11월 파일까지 검증을 통과했습니다. 2023년 1월~2026년 8월의 44개월, 1,928,160개 1분봉이 누락·중복 없이 연결됩니다. 이전 11월 미제공 안내는 해소됐습니다.

기존 모델·비중·비용·주문 규칙을 그대로 유지하고 2024년 1~12월의 10개 조건을 다시 실행했습니다. 혼합 진입 조합은 {base['return_pct']:+.2f}%, 분봉 낙폭 추정 {base['max_drawdown_bound_pct']:.2f}%였습니다. 비용·체결 스트레스에서는 {stress['return_pct']:+.2f}%, 낙폭 {stress['max_drawdown_bound_pct']:.2f}%입니다. 이전 1~10월의 −0.99%와 별개의 전체 연도 실행이며, 두 결과를 합산하면 안 됩니다.

아래 표의 2023년은 이전에 검증한 2월 4일~12월 31일 결과를 보존했고, 2024년 열만 1월 1일~12월 31일 결과로 갱신했습니다. 기간마다 자본 10,000을 새로 시작합니다. 44개월 전체를 하나의 계좌로 새로 백테스트한 결과는 아닙니다.

2025~2026년 자료로 정한 모델의 과거 추가 기간 검증으로, 미래 전진 검증은 아닙니다. 결과를 보고 비중이나 매개변수를 바꾸지 않았습니다. BTCUSDT 분봉은 실제 BTCUSDC 호가·체결·펀딩 자료가 아니며 거래소 원본 진위를 독립 대조하지 않았습니다.'''
 text='# 누락 월 복구와 2024년 전체 검증 — 2026-09-17\n\n'+summary+'\n\n'
 text+='| 모델 | 2023 수익률 | 2024 전체 수익률 | 2024 낙폭 추정 |\n|---|---:|---:|---:|\n'
 for r in rows:text+=f"| {r['strategy']} | {r['return2023']:+.2f}% | {r['return2024']:+.2f}% | {r['dd2024']:.2f}% |\n"
 text+='''
2024년의 지표는 2023년부터 연속 준비했고 2025년 이후 자료는 지표 계산 전에 제외했다. 신규 10개 실행은 이벤트별 수량·평균단가·잔액·수수료·펀딩·진입 총노출·월 복리·사이클 손익을 독립 검산했다. 2023년 수치는 이전 검증 결과이며 이번에 중복 실행하지 않았다.

고정 조건: 총 초기자본 10,000, 조합 전략별 1/3 예산, 신규 총노출 상한 1배, 전략별 0.5% 계획 손절 예산. 메이커 수수료 0 가정, 시장가 5bp·슬리피지 2bp·기본 펀딩 0. 스트레스는 7bp·5bp·8시간당 절대노출 1bp 펀딩·3bp 지정가 관통·분봉당 주문량 50% 체결 상한. 자세한 동결 조건은 protocol.json에 보존했다. 갭 손실·호가·유지증거금·주문 상계 등 실거래와의 차이가 남아 있다.

원본 ZIP은 수정하지 않았다. 전체 검증 기록: `data/historical/btcusdt_2023_2026_complete/manifest.json`. 신규 결과·프로토콜·검산·CSV: `reports/validation/complete_btc_2024_20260917/`. 재현: `scripts/validate_complete_btc_archives.py`, `scripts/run_complete_btc_2024_validation.py`, `scripts/report_complete_btc_2024.py`. 이전 2024년 1~10월 결과는 `reports/validation/additional_btc_2023_2024_20260917/`에 그대로 보존했다.
'''
 (ROOT/'docs/COMPLETE_BTC_2024_VALIDATION_2026_09_17.md').write_text(text)
 p=APP/'src/data.json';d=json.loads(p.read_text());d['buildStatus']='updating'
 q=d['queries']['additional_comparison'];q['rows']=rows
 q['source']=dict(label='44개월 연결 검증 · 2023 보존 / 2024 전체 재실행',
 files=['data/historical/btcusdt_2023_2026_complete/manifest.json','reports/validation/complete_btc_2024_20260917/results.json','reports/validation/complete_btc_2024_20260917/protocol.json','reports/validation/complete_btc_2024_20260917/verification.json','reports/validation/additional_btc_2023_2024_20260917/results.json'],
 filters=['2023-02-04~2023-12-31 UTC: 기존 결과','2024-01-01~2024-12-31 UTC: 신규 10회 실행'],
 evidenceFlow=[dict(title='기간·방법·검증',detail=text)],metricDefinitions=[dict(label='수익률',definition='각 독립 기간의 최종 시장가 청산 후 자산/10,000−1, 백분율. 기간별 합산 금지.'),dict(label='낙폭 추정',definition='이전 종가 고점 대비 전략별 분봉 내 불리한 평가 합계; 정확한 틱 낙폭 아님.')])
 q['methods']=[dict(language='python',code='2023 rows from additional_btc_2023_2024_20260917/results.json; 2024_full rows from complete_btc_2024_20260917/results.json; scripts/report_complete_btc_2024.py')]
 p.write_text(json.dumps(d,ensure_ascii=False,indent=2))
 jsx=APP/'src/content/report/ReportContent.jsx';body=jsx.read_text()
 start=body.index('  {/* ADDITIONAL_VALIDATION_START */}');end=body.index('  {/* ADDITIONAL_VALIDATION_END */}')
 chunk=body[start:end]
 chunk=re.sub(r'(<RichNarrative id="additional-summary:body" value=\{).*?(\}/>)',lambda match:match.group(1)+json.dumps(summary,ensure_ascii=False)+match.group(2),chunk,flags=re.S)
 body=body[:start]+chunk+body[end:];jsx.write_text(body)
 d['buildStatus']='complete';p.write_text(json.dumps(d,ensure_ascii=False,indent=2))
 print(json.dumps({'full2024_return':base['return_pct'],'full2024_stress':stress['return_pct']}))
if __name__=='__main__':main()
