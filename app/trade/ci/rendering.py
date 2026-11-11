from copy import deepcopy

from app.trade.ci.imports import ci_render_data
from app.trade.common.rendering import render_approved_files


def render_ci_files(payload, branding):
    prepared = deepcopy(payload)
    prepared["document"] = ci_render_data(prepared["document"])
    return render_approved_files(prepared, branding)
