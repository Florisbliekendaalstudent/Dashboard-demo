"""Lightweight local fallback for optional SHAP imports.

The dashboard does not require the external ``shap`` package to run. Some
older saved model code imports it during module load or unpickling, though.
This stub prevents that optional dependency from disabling the ML tab.
"""

import numpy as np

IS_SHAP_STUB = True


class Explanation:
    def __init__(self, values=None, base_values=None, data=None, feature_names=None):
        self.values = values
        self.base_values = base_values
        self.data = data
        self.feature_names = feature_names


class TreeExplainer:
    def __init__(self, model=None, *args, **kwargs):
        self.model = model

    def shap_values(self, data, *args, **kwargs):
        try:
            rows, cols = data.shape
        except Exception:
            rows, cols = 1, 1
        return np.zeros((rows, cols))

    def __call__(self, data, *args, **kwargs):
        return Explanation(values=self.shap_values(data), data=data)


Explainer = TreeExplainer


def summary_plot(*args, **kwargs):
    return None


def force_plot(*args, **kwargs):
    return None
