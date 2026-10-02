"""Session-only numeric timings. Never record arguments, SQL, prompts or secrets."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from hashlib import sha256
from pathlib import Path
from time import perf_counter

_active = ContextVar('teacher_ai_trace', default=None)


class Trace:
    def __init__(self, action=False):
        self.started = perf_counter()
        self.action = action
        self.metrics = {}

    def record(self, name, seconds, failed=False):
        value = self.metrics.setdefault(name, dict(count=0, seconds=0.0, failures=0))
        value['count'] += 1
        value['seconds'] += seconds
        value['failures'] += int(failed)

    def snapshot(self):
        return dict(elapsed_seconds=round(perf_counter() - self.started, 4),
                    metrics={k: dict(v, seconds=round(v['seconds'], 4))
                             for k, v in sorted(self.metrics.items())})


def start_trace(trace=None):
    trace = trace or Trace()
    _active.set(trace)
    return trace


@contextmanager
def span(name):
    trace = _active.get()
    started = perf_counter()
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        if trace is not None:
            trace.record(name, perf_counter() - started, failed)


def timed(name):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            with span(name):
                return function(*args, **kwargs)
        return run
    return decorate


class TimedCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        with span('db.fetch'):
            return self.cursor.fetchone()

    def fetchall(self):
        with span('db.fetch'):
            return self.cursor.fetchall()

    def __iter__(self):
        iterator = iter(self.cursor)
        while True:
            with span('db.fetch'):
                try:
                    row = next(iterator)
                except StopIteration:
                    return
            yield row

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class TimedConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, *args, **kwargs):
        # Fixed categories only; never retain query text or bound values.
        command = sql.lstrip().split(None, 1)[0].upper()
        category = ('lock' if 'pg_advisory_xact_lock' in sql else
                    'read' if command == 'SELECT' else
                    'write' if command in ('INSERT', 'UPDATE', 'DELETE') else 'setup')
        with span('db.sql.' + category):
            return TimedCursor(self.connection.execute(sql, *args, **kwargs))

    def __getattr__(self, name):
        return getattr(self.connection, name)


class TimedAI:
    def __init__(self, client):
        self.client = client
        self.responses = self

    def create(self, **kwargs):
        # Current workflows are stateless; avoid optional provider response storage.
        kwargs.setdefault('store', False)
        name = kwargs.get('text', {}).get('format', {}).get('name')
        stage = {'lesson_resource_batch': 'resource_generation',
                 'lesson_resource_review': 'resource_review'}.get(name, 'other')
        with span('ai.' + stage):
            return self.client.responses.create(**kwargs)


def build_identity(root=None):
    """Fingerprint shipped application sources, not a guessed Git SHA.

    No .git, environment, secrets, documents or database files are inspected.
    Deterministic per source bundle, including module reload guards.
    """
    root = Path(root or Path(__file__).parent)
    digest = sha256()
    paths = sorted(root.glob('*.py')) + [root / 'requirements.txt']
    for path in paths:
        digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return 'source-' + digest.hexdigest()[:16]


def runtime_versions():
    from importlib.metadata import version, PackageNotFoundError
    result = {}
    for package in ('streamlit', 'openai', 'psycopg', 'pypdf', 'python-docx'):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = 'unavailable'
    return result
