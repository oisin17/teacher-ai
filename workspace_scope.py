"""Explicit server-owned scope. Membership is rechecked for every transaction."""
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

CLASS_TABLES = ('teacher_profile', 'planning_setup', 'current_learning_position',
                'actual_progress', 'lesson_progress', 'day_plans', 'monthly_plans',
                'monthly_learning_items', 'monthly_item_updates', 'period_reviews',
                'carryover_items', 'lesson_resources')


@dataclass(frozen=True)
class WorkspaceScope:
    user_id: str
    workspace_id: str

    def __post_init__(self):
        from persistence import StorageError
        try:
            object.__setattr__(self, 'user_id', str(UUID(self.user_id)))
            object.__setattr__(self, 'workspace_id', str(UUID(self.workspace_id)))
        except (ValueError, TypeError, AttributeError):
            raise StorageError('An explicit valid workspace and user are required.') from None

    @property
    def lock_key(self):
        return int.from_bytes(sha256(('teacher-ai-workspace:' + self.workspace_id).encode()).digest()[:8], 'big', signed=True)

    @property
    def namespace(self):
        return 'workspace:' + self.workspace_id + ':user:' + self.user_id


def authorize_transaction(connection, scope):
    from persistence import WorkspaceAccessError
    # Reject superusers, table owners and inherited membership in owning roles.
    connection.execute('SET LOCAL search_path = pg_catalog, public, pg_temp')
    role = connection.execute("""SELECT r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb,
        EXISTS (SELECT 1 FROM pg_class c WHERE c.relname = ANY(%s)
          AND c.relnamespace = 'public'::regnamespace
          AND pg_has_role(current_user, c.relowner, 'MEMBER')),
        (SELECT count(*) FROM pg_class c WHERE c.relname=ANY(%s)
          AND c.relnamespace='public'::regnamespace AND c.relrowsecurity AND c.relforcerowsecurity) <> %s
        FROM pg_roles r WHERE r.rolname = current_user""", (list(CLASS_TABLES),list(CLASS_TABLES),len(CLASS_TABLES))).fetchone()
    if not role or any(role):
        raise WorkspaceAccessError('A restricted non-owner database runtime role is required.')
    connection.execute("SELECT set_config('teacher_ai.user_id', %s, true), set_config('teacher_ai.workspace_id', %s, true)", (scope.user_id, scope.workspace_id))
    if connection.execute('SELECT teacher_ai_authorized_workspace(%s::uuid)', (scope.workspace_id,)).fetchone() != (True,):
        raise WorkspaceAccessError('Workspace access is not authorized.')


def bind_session_scope(state, scope):
    """Clear all old widget/draft/download data before a scope can change."""
    if state.get('_authorized_scope') != scope.namespace:
        state.clear()
        state['_authorized_scope'] = scope.namespace
    return scope.namespace


class ScopedSessionState:
    """Dynamic facade: never retains another Streamlit session's scope."""
    def __init__(self, streamlit):
        self.st = streamlit

    def widget_key(self, key):
        prefix = self.st.session_state['_authorized_scope'] + ':'
        return key if isinstance(key, str) and key.startswith(prefix) else prefix + str(key)

    def __getitem__(self, key): return self.st.session_state[self.widget_key(key)]
    def __setitem__(self, key, value): self.st.session_state[self.widget_key(key)] = value
    def __delitem__(self, key): del self.st.session_state[self.widget_key(key)]
    def __contains__(self, key): return self.widget_key(key) in self.st.session_state
    def get(self, key, default=None): return self.st.session_state.get(self.widget_key(key), default)
    def pop(self, key, default=None): return self.st.session_state.pop(self.widget_key(key), default)
    def setdefault(self, key, value=None):
        if key not in self: self[key] = value
        return self[key]
    def keys(self):
        prefix = self.st.session_state['_authorized_scope'] + ':'
        return [k[len(prefix):] for k in self.st.session_state if k.startswith(prefix)]
    def __iter__(self): return iter(self.keys())


def scoped_state(streamlit):
    return ScopedSessionState(streamlit)
