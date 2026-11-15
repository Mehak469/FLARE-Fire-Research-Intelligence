"""Plotly figures. Kept separate so the logic stays testable and the pages stay short."""
from __future__ import annotations
from ..core.bins import AXIS_TITLES


def coverage_figure(cov: dict, mode: str = "investigations", only_gravity: str | None = None):
    """Heatmap of evidence counts. First axis = rows, second = columns, third = one panel per label. Zero cells say GAP."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    dims, axes, cells = cov["dims"], cov["axes"], cov["cells"]
    rows_dim = dims[0]
    cols_dim = dims[1] if len(dims) > 1 else None
    facet_dim = dims[2] if len(dims) > 2 else None
    if len(dims) > 3:
        raise ValueError("charts support up to 3 axes")
    row_labels = [l for l in axes[rows_dim] if not (only_gravity and rows_dim == "gravity_class" and l != only_gravity)]
    col_labels = axes[cols_dim] if cols_dim else ["all"]
    facets = axes[facet_dim] if facet_dim else [None]
    key = "n_investigations" if mode == "investigations" else "n_runs"
    fig = make_subplots(rows=1, cols=len(facets), subplot_titles=[f"{AXIS_TITLES[facet_dim]}: {f}" if f else "" for f in facets])
    index = {tuple(c["labels"][d] for d in dims): c for c in cells}
    scale = [[0.0, "#E5E7EB"], [0.0001, "#BFDBFE"], [1.0, "#1D4ED8"]]
    for j, f in enumerate(facets, start=1):
        z, text, hover = [], [], []
        for rl in row_labels:
            zr, tr, hr = [], [], []
            for cl in col_labels:
                combo = [rl] + ([cl] if cols_dim else []) + ([f] if facet_dim else [])
                c = index[tuple(combo)]
                n = c[key]
                zr.append(n); tr.append("GAP" if n == 0 else str(n))
                names = ", ".join(c["investigations"][:8]) or "none"
                hr.append(f"{n} {mode} here<br>investigations: {names}<br>runs: {c['n_runs']} ({c['n_verified_runs']} human-verified)")
            z.append(zr); text.append(tr); hover.append(hr)
        fig.add_trace(go.Heatmap(z=z, x=col_labels, y=row_labels, text=text, texttemplate="%{text}", hovertext=hover,
                                 hoverinfo="text", colorscale=scale, zmin=0, showscale=False), row=1, col=j)
    fig.update_xaxes(title_text=AXIS_TITLES[cols_dim] if cols_dim else "")
    fig.update_yaxes(title_text=AXIS_TITLES[rows_dim])
    fig.update_layout(height=120 + 70 * max(len(row_labels), 2), margin=dict(l=10, r=10, t=40, b=10))
    return fig
