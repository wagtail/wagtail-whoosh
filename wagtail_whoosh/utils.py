from functools import lru_cache

from django.apps import apps

from wagtail.search.index import Indexed

try:
    # Only use the GPLv2 licensed unidecode if it's installed.
    from unidecode import unidecode
except ImportError:
    def unidecode(value):
        return value


@lru_cache()
def get_indexed_parents(model):
    models = [model]
    if model._meta.parents:
        models += [m[0] for m in model._meta.parents.items() if issubclass(m[0], Indexed)]
    return models


@lru_cache()
def get_descendant_models(model):
    """
    Returns all descendants of a model
    """
    descendant_models = {other_model for other_model in apps.get_models()
                         if issubclass(other_model, model)}
    return descendant_models


def get_boost(value):
    if value:
        # TODO might be a value between 0.0->1.0, docs unclear
        return float(value)
    return 1.0
