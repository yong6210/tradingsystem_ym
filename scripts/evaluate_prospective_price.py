"""Offline snapshot of Q004 evidence; never fetches, publishes or scores a day."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.diagnostics.prospective_evaluation import evaluate


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
    report=evaluate(ROOT,ROOT/'reports/validation/q004_prospective_price_forecast_20260919',datetime.now(timezone.utc))
    if args.output:
        with args.output.open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k!='states'},ensure_ascii=False,indent=2,allow_nan=False))
