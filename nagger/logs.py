from contextlib import contextmanager
from structlog.contextvars import bind_contextvars, unbind_contextvars


@contextmanager
def log_state(*args, **kws):
    bind_contextvars(**kws)
    try:
        yield
    finally:
        unbind_contextvars(*kws)
