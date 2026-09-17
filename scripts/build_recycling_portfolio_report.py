"""Add the reviewed allocation/recycling study to the existing local report."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/recycling_portfolio_20260917'
APP=ROOT/'reports/validation/user_btcusdt_20260917/report-app'
LABELS={'rotation_no_add':'순환매 · 추가 매수 없음','rotation_bounded':'순환매 · 누적 3단위 제한',
'rotation_recycling':'순환매 · 익절 후 재충전','swing_maker':'스윙 · 지정가','swing_market':'스윙 · 시장가',
'breakout_maker':'돌파 · 지정가','breakout_market':'돌파 · 시장가','allocated_maker':'자본 분리 조합 · 지정가',
'allocated_hybrid':'자본 분리 조합 · 혼합 진입','allocated_hybrid_stress':'자본 분리 조합 · 혼합 스트레스'}

def main():
 data=json.loads((OUT/'results.json').read_text()); attribution=json.loads((OUT/'attribution.json').read_text())
 rows=[]
 for k,label in LABELS.items():
  a,b=data['results']['validation'][k],data['results']['evaluation'][k]
  rows.append(dict(case=k,strategy=label,validation=a['return_pct'],evaluation=b['return_pct'],drawdown=b['max_drawdown_bound_pct'],
                   cycles=sum(len(s['cycles']) for s in b['sleeves'].values()),recycled=attribution['evaluation'][k]['recycled_cycles']))
 summary='''## 최신 검증: 재진입과 자본 분리 구현

부분 익절 후 재고를 다시 채우는 순환매와 전략별 자본 예산을 구현했습니다. 스윙·순환매·돌파에 초기 자본을 1/3씩 배정하고, 서로의 포지션 때문에 진입이 막히지 않도록 별도 장부로 계산합니다. 전체 신규 체결 총노출은 계좌의 1배 이하로 제한합니다.

2026년 1~8월 혼합 진입 조합은 **−0.22%**, 보수적 분봉 낙폭 추정은 **3.30%**였습니다. 비용·체결 스트레스에서는 **−2.18%**, 낙폭 **4.78%**입니다. 2025년 8~12월도 **−1.98%**로, 아직 수익 우위가 입증되지 않았습니다.

혼합 진입은 스윙·돌파의 최초 진입만 시장가, 순환매·재진입·목표 익절은 지정가입니다. 시장가에는 수수료·슬리피지를 적용했습니다. 실제 BTCUSDC 호가 검증이 아닌 BTCUSDT 분봉 대리 자료이며, 이미 본 데이터를 사용한 20회 사후 비교입니다. 아래 기존 70회 연구와 별도 버전이고 여러 규칙이 달라 수익률 차이를 한 가지 수정의 효과로 해석하면 안 됩니다.'''
 detail='''## 무엇이 구현됐고 무엇이 부족한가

**재고 재충전:** 최초 수량의 3배를 최대 보유량으로 유지하고, 부분 익절 후 직전 체결가에서 1 ATR 되돌림이 나오면 다시 채웁니다. 최초 ATR·손절선·12시간 시간 제한을 유지합니다. 추가 주문과 익절 주문은 별도 슬롯입니다. 추가 체결과 손절이 같은 분에 가능하면 추가 후 손절, 손절과 익절이 가능하면 손절을 먼저 처리합니다. 새 추가 체결은 이전 익절 주문을 취소하며 같은 분의 낙관적인 반등 익절을 가정하지 않습니다.

2026년 단독 순환매 330사이클 중 24개에서 누적 매수량이 최초 수량의 3배를 넘어, 부분 익절 뒤 재충전이 실제 발생했습니다. 하지만 제한형 **−4.65%**에서 재충전형 **−4.79%**로 손실이 늘었습니다. 2025년에도 **−5.27% → −5.73%**였습니다. 반복 순환을 구현하는 것과 수익성은 별개입니다.

**자본 분리:** 동일 비중을 사전에 고정했고 결과에 맞춰 비중을 조정하지 않았습니다. 다른 전략 예산을 빌리지 않으며 모든 지정가 주문의 분봉 거래량 참여 한도를 합산합니다. 고변동 구간은 신규 위험을 막되 기존 스윙을 국면 변화만으로 강제 청산하지 않습니다. 2026년 혼합 조합 손익은 스윙 **+76.30**, 순환매 **−168.15**, 돌파 **+70.03**(초기 전체 자본 10,000 기준)입니다.

**체결 비교:** 스윙·돌파 지정가 유효시간은 15분, 순환매는 3분입니다. 돌파 단독은 2026년 지정가 **−0.92%**, 시장가 **+1.57%**였지만 2025년에는 **−1.20%**, **−3.62%**였습니다. 유리한 기간만 보고 시장가를 정답으로 채택할 수 없습니다.

**남은 한계:** 전략별 가상 장부가 반대 방향을 동시에 보유할 수 있습니다. 비용 절감용 주문 상계는 적용하지 않았고 실거래 계좌의 주문·증거금·포지션 모드 연결은 구현하지 않았습니다. 실제 틱·호가 대기열·펀딩 이력이 없어 지정가 체결 확률을 입증하지 못했습니다. 낙폭은 각 장부의 불리한 분봉 가격을 합친 보수적 경로 추정이며 틱 기준 실제 낙폭이 아닙니다. 워뇨띠 매매법 재현이나 전 장세 수익 모델 완성을 주장하지 않습니다.'''
 text='# 순환매 재진입·전략 자본 분리 검증 — 2026-09-17\n\n'+summary+'\n\n'
 text+='| 모델 | 2025년 8~12월 | 2026년 1~8월 | 2026 낙폭 추정 | 2026 사이클 |\n|---|---:|---:|---:|---:|\n'
 for r in rows:text+=f"| {r['strategy']} | {r['validation']:+.2f}% | {r['evaluation']:+.2f}% | {r['drawdown']:.2f}% | {r['cycles']} |\n"
 text+='\n'+detail+'\n\n## 실행 명세와 검증\n\n'
 text+='초기 10,000, 전략별 0.5% 계획 손절 예산(배정 초기자본과 사이클 시작 잔액 중 작은 값 기준), 순환매 최초 위험 1/3. 지정가 수수료 0 가정, 시장가 5bp·슬리피지 2bp, 기본 펀딩 0. 스트레스는 시장가 7bp·슬리피지 5bp·8시간당 절대노출 1bp 펀딩·3bp 지정가 관통·분봉당 주문량 50% 체결 상한. 기본 관통은 1bp. 모든 지정가 합산 거래량 참여율 0.1%. 갭으로 계획 손실 예산을 초과할 수 있다.\n\n'
 text+='모든 기간은 UTC, 시작 시 계좌·포지션 초기화, 지표만 이전 자료로 준비한다. 후보 재선정·파라미터 검색 없이 이전 선정 모델을 사용한다. 스윙은 자체 EMA 청산, 돌파는 외부 4시간 추세 반전 청산 제거. 혼합형의 추가 진입은 지정가로 유지한다. 같은 분에는 스윙→순환매→돌파 순서로 잔여 거래량·위험을 배정한다. 추가 매수 없는 비교도 초기 위험은 같은 1/3이다. 재충전 제한형은 누적 매수 3단위, 허용형은 현재 재고 3단위로 구분한다.\n\n'
 text+='20개 실행 모두 이벤트별 잔액·평균단가·수량·수수료·펀딩을 독립 재계산했고, 월별 복리·사이클 손익·체결 시 총노출이 일치했다. 재순환·손절 순서·독립 주문·시장가 비용·공유 거래량·자본 보존·미래 가격 변경 불변성 테스트를 추가했다. 원장은 실제 거래소 체결 원장이 아니라 모의 체결 원장이다.\n\n'
 text+='재현 스크립트: `scripts/run_recycling_portfolio.py`, `scripts/verify_recycling_portfolio.py`, `scripts/build_recycling_portfolio_report.py`. 소스: `app/research/recycling_portfolio.py`. 데이터·프로토콜·원장·요약·검증: `reports/validation/recycling_portfolio_20260917/`. 기존 엔진·기존 70회·자체 감사 28회 결과는 보존했다. 실거래 실행 설정은 변경하지 않았다.\n\n'
 text+='현재 판단은 **연구 구현 완료, 수익 모델 채택 보류**다. 순환매 진입 신호는 이전 15분봉 편차 조건을 그대로 유지해 재충전 효과를 관찰했다. 지지·저항의 실제 유효성, 손실 방향 추가 진입의 조건부 기대값, 호가 체결 우위는 새로 입증하지 않았다. 그 부분은 이번 구현만으로 해결됐다고 보고하지 않는다.\n'
 (ROOT/'docs/RECYCLING_PORTFOLIO_2026_09_17.md').write_text(text)
 path=APP/'src/data.json';d=json.loads(path.read_text());d['buildStatus']='updating'
 source=dict(label='재고 재충전·동일 비중 자본 분리 · 20회 고정 실험',
   files=['reports/validation/recycling_portfolio_20260917/results.json','reports/validation/recycling_portfolio_20260917/protocol.json','reports/validation/recycling_portfolio_20260917/verification.json','app/research/recycling_portfolio.py'],
   filters=['BTCUSDT 분봉 대리 자료, BTCUSDC 실체결 검증 아님','2025-08-01~2025-12-31 및 2026-01-01~2026-08-31 UTC'],
   evidenceFlow=[dict(title='사전 규칙과 실행',detail=json.dumps(data['protocol']['rules'],ensure_ascii=False,indent=2)),dict(title='비용 가정',detail=text[text.index('초기 10,000,'):text.index('모든 기간은 UTC')]),dict(title='해석과 검증',detail=detail)],
   metricDefinitions=[dict(label='수익률',definition='각 독립 기간의 최종 시장가 종료 비용 포함 자산/10,000−1, 백분율.'),dict(label='낙폭 추정',definition='이전 분봉 종가 평가 고점 대비 각 전략의 불리한 분봉 내 평가 합계. 틱 경로와 전략 간 고저가 동시성 미확인.'),dict(label='사이클',definition='전략별 최초 체결에서 잔여 수량 전량 종료까지의 횟수 합계. 부분 체결 횟수가 아님.')])
 d['queries']['recycling_comparison']=dict(rows=rows,source=source,methods=[dict(language='python',code='scripts/run_recycling_portfolio.py → scripts/verify_recycling_portfolio.py → scripts/build_recycling_portfolio_report.py; results.validation/evaluation each case return_pct, max_drawdown_bound_pct, sum sleeve cycles')])
 path.write_text(json.dumps(d,ensure_ascii=False,indent=2))
 jsx=APP/'src/content/report/ReportContent.jsx';body=jsx.read_text()
 start='  {/* RECYCLING_RESEARCH_START */}';end='  {/* RECYCLING_RESEARCH_END */}'
 if start in body:body=body[:body.index(start)]+body[body.index(end)+len(end):]
 insert=start+'\n'+f'  <ReportSection id="recycling-summary" queryId="recycling_comparison" sourceRows={{snapshot.queries.recycling_comparison.rows}} title="最新 검증" showHeading={{false}}><RichNarrative id="recycling-summary:body" value={{{json.dumps(summary.replace("**", ""),ensure_ascii=False)}}}/></ReportSection>\n'
 insert+="  {table('recycling-results','재진입·자본 분리 · 두 기간 비교',snapshot.queries.recycling_comparison.rows,[{field:'strategy',label:'모델'},{field:'validation',label:'2025 수익률 (%)',renderCell:num},{field:'evaluation',label:'2026 수익률 (%)',renderCell:num},{field:'drawdown',label:'2026 낙폭 추정 (%)',renderCell:num},{field:'cycles',label:'2026 사이클'}],'recycling_comparison',true)}\n"
 insert+=f'  <ReportSection id="recycling-design" queryId="recycling_comparison" sourceRows={{snapshot.queries.recycling_comparison.rows}} title="재진입과 체결 명세" showHeading={{false}}><RichNarrative id="recycling-design:body" value={{{json.dumps(detail.replace("**", ""),ensure_ascii=False)}}}/></ReportSection>\n'+end+'\n'
 body=body.replace('  {/* MULTI_RESEARCH_START */}',insert+'\n  {/* MULTI_RESEARCH_START */}')
 body=body.replace('title="最新 검증"','title="최신 검증"')
 jsx.write_text(body)
 d['buildStatus']='complete';path.write_text(json.dumps(d,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
