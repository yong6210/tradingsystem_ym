from decimal import Decimal as D
import io
from zipfile import ZipFile
import unittest

from app.research.diagnostics.pair_feasibility import parse_hour_archive,funding_profile,contract,size_pair


def spec(step='.001',minimum='100'):
    return dict(step=D(step),min_qty=D(step),max_qty=D('1000'),min_notional=D(minimum))


def archive(rows):
    text='open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n'
    text+='\n'.join(','.join(map(str,r)) for r in rows)+'\n';buf=io.BytesIO()
    with ZipFile(buf,'w') as z:z.writestr('test.csv',text)
    return buf.getvalue()


class PairFeasibilityTests(unittest.TestCase):
    def row(self):return [1725148800000,100,110,90,105,10,1725152399999,1000,2,5,500,0]
    def test_missing_hours_remain_visible(self):
        f,p=parse_hour_archive(archive([self.row()]),'2024-09')
        self.assertEqual(len(f),1);self.assertEqual(len(p['missing_hours']),719)
    def test_duplicate_hours_rejected(self):
        with self.assertRaises(ValueError):parse_hour_archive(archive([self.row(),self.row()]),'2024-09')
    def test_wrong_clock_unit_rejected(self):
        r=self.row();r[0]*=1000;r[6]=r[0]+3600000000-1
        with self.assertRaises(ValueError):parse_hour_archive(archive([r]),'2024-09')
    def test_impossible_ohlc_or_taker_volume_rejected(self):
        for column,value in ((2,95),(9,20)):
            r=self.row();r[column]=value
            with self.assertRaises(ValueError):parse_hour_archive(archive([r]),'2024-09')
    def test_hedge_rounded_to_btc_nominal_not_separate_200_budgets(self):
        r=size_pair('60000','3000',spec(),spec('.001','20'))
        self.assertEqual(D(r['btc_qty']),D('.003'));self.assertEqual(D(r['eth_qty']),D('.060'))
        self.assertEqual(D(r['mismatch_fraction']),0);self.assertTrue(r['eligible'])
    def test_too_small_btc_order_is_not_rounded_up(self):
        r=size_pair('250000','3000',spec(),spec('.001','20'))
        self.assertEqual(D(r['btc_qty']),0);self.assertFalse(r['eligible'])
    def test_large_eth_step_mismatch_blocks(self):
        r=size_pair('60000','3100',spec(),spec('.01','20'))
        self.assertFalse(r['eligible']);self.assertIn('notional_mismatch',r['reasons'])
    def test_long_funding_interval_is_warning_not_imputed(self):
        r=[dict(symbol='ETHUSDC',fundingTime=t,fundingRate='.0001',markPrice='3000') for t in (0,12*3600000)]
        p=funding_profile(r,0,16*3600000)
        self.assertEqual(p['events'],2);self.assertEqual(p['schedule_or_gap_warnings'][0]['kind'],'interval')
    def test_funding_duplicate_or_missing_mark_rejected(self):
        r=dict(symbol='ETHUSDC',fundingTime=0,fundingRate='.0001',markPrice='3000')
        with self.assertRaises(ValueError):funding_profile([r,r],0,3600000)
        with self.assertRaises(KeyError):funding_profile([dict(symbol='ETHUSDC',fundingTime=0,fundingRate='.0001')],0,3600000)
    def test_limit_market_common_step_uses_lcm(self):
        s=dict(symbol='ETHUSDC',contractType='PERPETUAL',quoteAsset='USDC',marginAsset='USDC',status='TRADING',filters=[
            dict(filterType='LOT_SIZE',stepSize='.002',minQty='.002',maxQty='100'),
            dict(filterType='MARKET_LOT_SIZE',stepSize='.003',minQty='.003',maxQty='50'),dict(filterType='MIN_NOTIONAL',notional='20')])
        self.assertEqual(contract(s)['step'],D('.006'))


if __name__=='__main__':unittest.main()
