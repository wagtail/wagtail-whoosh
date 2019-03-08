from wagtail.search.index import Indexed

try:
    # Only use the GPLv2 licensed unidecode if it's installed.
    from unidecode import unidecode
except ImportError:
    def unidecode(value):
        return value


def get_indexed_parents(model):
    models = [model]
    if model._meta.parents:
        models += [m[0] for m in model._meta.parents.items() if issubclass(m[0], Indexed)]
    return models


def get_boost(value):
    if value:
        # TODO might be a value between 0.0->1.0, docs unclear
        return float(value)
    return 1.0
