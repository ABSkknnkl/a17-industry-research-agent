"""Signals that a caller's persisted request budget has been consumed."""


class ProbeBudgetExceeded(RuntimeError):
    pass
