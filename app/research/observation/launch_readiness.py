"""Fresh, read-only readiness classification; never starts or schedules a run."""
from app.research.observation.signal_window import admission


def classify(plan, now_ms, expected_schedule, current_schedule, source_errors=(),
             public_directory_exists=False, schedule_error=None):
    reasons=[]
    if schedule_error:
        reasons.append('CURRENT_SCHEDULE_UNREADABLE')
    elif current_schedule is None:
        reasons.append('CURRENT_SCHEDULE_MISSING')
    else:
        for key in ('id','kind','target_thread_id','rrule','prompt'):
            if current_schedule.get(key)!=expected_schedule.get(key):
                reasons.append('SCHEDULE_BINDING_CHANGED:'+key)
        if current_schedule.get('status')!='ACTIVE':reasons.append('CURRENT_SCHEDULE_NOT_ACTIVE')
    if source_errors:reasons.append('PREPARATION_OR_SOURCE_CHANGED')
    choice=admission(plan,now_ms)
    if choice=='MISSED_START_WINDOW':reasons.append(choice)
    if public_directory_exists:reasons.append('PUBLIC_ATTEMPT_ALREADY_RESERVED')
    return dict(status='BLOCKED' if reasons else 'FRESH_CONFIGURATION_CHECK_ONLY',reasons=reasons,
        checked_at_ms=now_ms,admission=choice,source_errors=list(source_errors),
        public_directory_exists=public_directory_exists,schedule_error=schedule_error,
        scheduler_wake_verified=False,executor_started_by_check=False,network_requests=0,
        actual_orders=0,automatic_retry=False,target_changed=False,
        scope='Point-in-time configuration check. It does not prove scheduler dispatch, future file persistence, ARM or market observation.')
