"""A permissive stand-in for streamlit and plotly so page scripts can be EXECUTED in tests (the real packages are not needed)."""
import sys
import types
from unittest.mock import MagicMock


class StopPage(Exception):
    pass


class SessionState(dict):
    def __getattr__(self, k):
        return self.get(k)
    def __setattr__(self, k, v):
        self[k] = v


CONFIG = {"press": set(), "checked": set(), "pick_n": 0, "text": {}}


class Container:
    """Every widget method returns a sensible default; calls are recorded for assertions."""
    def __init__(self, log):
        self.log = log
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def _rec(self, name, *a, **k): self.log.append((name, a, k))
    def columns(self, spec, **k):
        self._rec("columns", spec); n = spec if isinstance(spec, int) else len(spec); return [Container(self.log) for _ in range(n)]
    def tabs(self, labels, **k):
        self._rec("tabs", labels); return [Container(self.log) for _ in labels]
    def expander(self, *a, **k): self._rec("expander", *a); return Container(self.log)
    def container(self, *a, **k): return Container(self.log)
    def radio(self, label, options, index=0, **k): self._rec("radio", label); return options[index]
    def selectbox(self, label, options, index=0, **k):
        self._rec("selectbox", label); return list(options)[index] if len(list(options)) else None
    def multiselect(self, label, options, default=None, **k):
        self._rec("multiselect", label)
        if default is not None: return list(default)
        return list(options)[:CONFIG["pick_n"]]
    def text_input(self, label, value="", **k): self._rec("text_input", label); return CONFIG["text"].get(label, value)
    def text_area(self, label, value="", **k): return CONFIG["text"].get(label, value)
    def slider(self, label, min_value=None, max_value=None, value=None, **k): return value
    def checkbox(self, label, value=False, **k): return label in CONFIG["checked"] or value
    def button(self, label, **k): self._rec("button", label); return label in CONFIG["press"]
    def stop(self): raise StopPage()
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        def f(*a, **k):
            self._rec(name, *a, **k); return MagicMock()
        return f


def install():
    log = []
    root = Container(log)
    st = types.ModuleType("streamlit")
    st.session_state = SessionState()
    st.sidebar = Container(log)
    st.cache_resource = lambda f=None, **k: (f if callable(f) else (lambda g: g))
    st.cache_data = st.cache_resource
    def attr(name):
        return getattr(root, name)
    st.__getattr__ = attr   # module-level __getattr__ (PEP 562)
    sys.modules["streamlit"] = st
    for name in ("plotly", "plotly.graph_objects", "plotly.subplots"):
        sys.modules[name] = MagicMock()
    return st, log


def reset():
    CONFIG.update({"press": set(), "checked": set(), "pick_n": 0, "text": {}})
