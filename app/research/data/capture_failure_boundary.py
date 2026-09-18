"""Fail-closed, non-durable diagnostics for a failed capture storage owner.

A memory report is not an END receipt. Never clear the budget latch, retry a
write, or authorize a new live session on the strength of this report.
"""
from .durable_capture_log import JournalError, decoded, encoded
from .restartable_feed_capture import RestartableFeedCapture


def failure_report(scope, *, phase, error, budget, context=None):
    errors = []
    if context:
        epoch = context.get('epoch', {})
        if epoch.get('reason'):
            errors.append(str(epoch['reason'])[:1000])
        errors.extend(str(x)[:1000] for x in context.get('pipeline', {}).get('errors', [])[:8])
    current = error
    for _ in range(4):
        if current is None:
            break
        message = type(current).__name__+':'+str(current)[:1000]
        if message not in errors:
            errors.append(message)
        current = current.__cause__ or current.__context__
    # result_persisted refers to this memory diagnostic, not a possibly
    # renamed epoch result/END whose acknowledgement was lost.
    return dict(outcome='FATAL_FAILURE', stop_reason='FATAL_FAILURE', phase=phase,
                original_window=dict(scope), errors=errors,
                result_persisted=False, durable_result_acknowledged=False,
                completion_receipt_acknowledged=False, physical_result_files_may_exist=True,
                storage=budget.snapshot(), audits=[], live_resume_supported=False,
                full_day_ready=False, profitability_evaluation_ready=False,
                quality=dict(status='QUALITY_INPUTS_REJECTED', reasons=['CAPTURE_FAILED_UNPERSISTED']))


class GuardedRestartableFeedCapture(RestartableFeedCapture):
    """Versioned diagnostic boundary; inherited receipt/recovery format unchanged."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._unpersisted_context = None
        self._terminal_report = None

    def _end(self, index, outcome, result):
        self._unpersisted_context = result
        if self.budget.failed:
            raise JournalError('RESULT_NOT_WRITTEN_AFTER_STORAGE_FAILURE')
        super()._end(index, outcome, result)
        self._unpersisted_context = None

    async def run(self, transport):
        if self.running:
            raise JournalError('supervisor already running')
        if self._terminal_report is not None:
            return decoded(encoded(self._terminal_report))
        try:
            return await super().run(transport)
        except Exception as exc:
            if not self.budget.failed:
                raise
            self._terminal_report = failure_report(self.scope(), phase='FAILED_STORAGE_OWNER',
                error=exc, budget=self.budget, context=self._unpersisted_context)
            return decoded(encoded(self._terminal_report))
