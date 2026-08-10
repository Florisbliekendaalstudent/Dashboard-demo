from copy import deepcopy


def tr(text: str, lang: str = "nl", **kwargs) -> str:
    if not isinstance(text, str):
        return text
    return text.format(**kwargs) if kwargs else text


def tr_dict_values(d: dict, lang: str = "nl") -> dict:
    return {k: tr(v, lang) for k, v in d.items()}


def translate_variable_specs(variabelen: list[dict], lang: str = "nl") -> list[dict]:
    return deepcopy(variabelen)


def translate_plotly_figure(fig, lang: str = "nl"):
    return fig


def translate_matplotlib_figure(fig, lang: str = "nl"):
    return fig


def translate_dataframe(df, lang: str = "nl"):
    return df
