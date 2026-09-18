import unittest
from app.research.observation.launch_readiness import classify
from app.research.observation.signal_window import window


class LaunchReadinessTests(unittest.TestCase):
    def setUp(self):
        self.plan=window(14400000)
        self.schedule=dict(id='fixed',kind='heartbeat',target_thread_id='task',rrule='fixed-rule',prompt='fixed-prompt',status='ACTIVE')

    def check(self,**kwargs):
        args=dict(plan=self.plan,now_ms=self.plan['launch_ms']-60000,
                  expected_schedule=self.schedule,current_schedule=dict(self.schedule))
        args.update(kwargs);return classify(**args)

    def test_historical_active_does_not_replace_missing_current(self):
        r=self.check(current_schedule=None)
        self.assertEqual(r['reasons'],['CURRENT_SCHEDULE_MISSING'])
        self.assertFalse(r['scheduler_wake_verified'])

    def test_snapshot_success_is_not_dispatch(self):
        r=self.check();self.assertEqual(r['status'],'FRESH_CONFIGURATION_CHECK_ONLY')
        self.assertFalse(r['executor_started_by_check']);self.assertEqual(r['network_requests'],0)

    def test_each_binding_mismatch_blocks(self):
        for key in ['id','kind','target_thread_id','rrule','prompt']:
            with self.subTest(key=key):
                s=dict(self.schedule);s[key]='changed'
                self.assertIn('SCHEDULE_BINDING_CHANGED:'+key,self.check(current_schedule=s)['reasons'])

    def test_inactive_blocks(self):
        s=dict(self.schedule,status='PAUSED')
        self.assertIn('CURRENT_SCHEDULE_NOT_ACTIVE',self.check(current_schedule=s)['reasons'])

    def test_unreadable_is_not_missing(self):
        r=self.check(current_schedule=None,schedule_error='TOMLDecodeError')
        self.assertEqual(r['reasons'],['CURRENT_SCHEDULE_UNREADABLE'])

    def test_last_start_boundary_and_expiry(self):
        t=self.plan['latest_start_ms']
        self.assertEqual(self.check(now_ms=t)['admission'],'START')
        self.assertIn('MISSED_START_WINDOW',self.check(now_ms=t+1)['reasons'])

    def test_empty_public_directory_prevents_retry(self):
        self.assertIn('PUBLIC_ATTEMPT_ALREADY_RESERVED',self.check(public_directory_exists=True)['reasons'])

    def test_source_change_blocks(self):
        self.assertIn('PREPARATION_OR_SOURCE_CHANGED',self.check(source_errors=['fixed.py'])['reasons'])

    def test_report_all_blockers_without_retiming(self):
        r=self.check(now_ms=self.plan['latest_start_ms']+1,current_schedule=None,source_errors=['seed'])
        self.assertEqual(len(r['reasons']),3)
        self.assertFalse(r['automatic_retry']);self.assertFalse(r['target_changed'])

    def test_too_early_is_explicit_and_no_execution(self):
        r=self.check(now_ms=self.plan['launch_ms']-120001)
        self.assertEqual(r['admission'],'TOO_EARLY');self.assertFalse(r['executor_started_by_check'])
