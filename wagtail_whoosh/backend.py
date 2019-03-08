import os
import re
import shutil
from collections import OrderedDict

from django.db import DEFAULT_DB_ALIAS, models
from django.db.models import Case, Manager, Q, When
from django.utils import six
from django.utils.encoding import force_text

from wagtail.search.backends.base import (
    BaseSearchBackend, BaseSearchQueryCompiler, BaseSearchResults)
from wagtail.search.index import AutocompleteField, FilterField, RelatedFields, SearchField
from wagtail.search.query import And, Boost, MatchAll, Not, Or, PlainText

from whoosh import query as wquery
from whoosh.fields import ID as WHOOSH_ID
from whoosh.fields import TEXT, Schema
from whoosh.filedb.filestore import FileStorage
from whoosh.qparser import FuzzyTermPlugin, MultifieldParser, QueryParser
from whoosh.writing import AsyncWriter

from .utils import get_boost, get_indexed_parents

ID = "id"
DJANGO_CT = "django_content_type"
DJANGO_ID = "django_id"
DOCUMENT_FIELD = "text"
IDENTIFIER_REGEX = re.compile("^[\w\d_]+\.[\w\d_]+\.[\w\d-]+$")


def get_facet_field_name(fieldname):
    if fieldname in [ID, DJANGO_ID, DJANGO_CT]:
        return fieldname

    return "%s_exact" % fieldname


def get_identifier(obj_or_string):
    """
    Get an unique identifier for the object or a string representing the
    object.
    If not overridden, uses <app_label>.<object_name>.<pk>.
    """
    if isinstance(obj_or_string, six.string_types):
        if not IDENTIFIER_REGEX.match(obj_or_string):
            raise AttributeError(
                "Provided string '%s' is not a valid identifier." % obj_or_string
            )

        return obj_or_string

    return "%s.%s" % (get_model_ct(obj_or_string), obj_or_string._get_pk_val())


def get_model_ct_tuple(model):
    # Deferred models should be identified as if they were the underlying model.
    model_name = (
        model._meta.concrete_model._meta.model_name
        if hasattr(model, "_deferred") and model._deferred
        else model._meta.model_name
    )
    return (model._meta.app_label, model_name)


def get_model_ct(model):
    return "%s.%s" % get_model_ct_tuple(model)


class ModelSchema:
    def __init__(self, model):
        self.model = model

    def build_schema(self):
        schema_fields = {
            'id': WHOOSH_ID(stored=True, unique=True),
            DJANGO_CT: WHOOSH_ID(stored=True),
            DJANGO_ID: WHOOSH_ID(stored=True, unique=True),
            **dict(self.define_search_fields()),
        }
        return Schema(**schema_fields)

    def define_search_fields(self):
        for field in self.model.get_search_fields():
            if isinstance(field, SearchField):
                yield field.field_name, TEXT(
                    phrase=field.partial_match, stored=True, field_boost=get_boost(field.boost))
            if isinstance(field, RelatedFields):
                # TODO
                pass
            if isinstance(field, FilterField):
                # TODO
                pass
            if isinstance(field, AutocompleteField):
                # TODO
                pass


class WhooshIndex:
    # All methods here atm aren't reusable i.e. WhooshIndex(params).method() opens, operates then closes
    def __init__(self, backend, model, db_alias=None):
        self.backend = backend
        self.models = get_indexed_parents(model)
        if db_alias is None:
            db_alias = DEFAULT_DB_ALIAS
        self.db_alias = db_alias
        self.name = model._meta.label
        self.indicies = dict(self._open_indicies())

    def _open_indicies(self):
        storage = self.backend.storage
        for model in self.models:
            label = model._meta.label
            # if index doesn't exist, create
            if not storage.index_exists(indexname=label):
                schema = ModelSchema(model).build_schema()
                storage.create_index(schema, indexname=label)
            # return the opened index to work with
            yield label, storage.open_index(indexname=label)

    def _close_indicies(self):
        self.backend.storage.close()

    def add_model(self, model):
        # Close the indicies openeded when initialiased
        self._close_indicies()

    def refresh(self):
        for index in self.indicies():
            index.refresh()
        self._close_indicies()

    def prepare_value(self, value):
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return ', '.join(self.prepare_value(item) for item in value)
        if isinstance(value, dict):
            return ', '.join(self.prepare_value(item)
                             for item in value.values())
        return force_text(value)

    def _get_document_fields(self, model, item):
        for field in model.get_search_fields():
            if isinstance(field, SearchField):
                yield field.field_name, self.prepare_value(field.get_value(item))
            if isinstance(field, RelatedFields):
                # TODO
                pass
            if isinstance(field, FilterField):
                # TODO
                pass
            if isinstance(field, AutocompleteField):
                # TODO
                pass

    def _create_document(self, model, item):
        return {
            ID: get_identifier(item),
            DJANGO_CT: get_model_ct(model),
            DJANGO_ID: force_text(item.pk),
            **dict(self._get_document_fields(model, item))
        }

    def add_item(self, item):
        for model in self.models:
            doc = self._create_document(model, item)
            index = self.indicies[model._meta.label]
            writer = AsyncWriter(index)
            writer.update_document(**doc)
            writer.commit()
        self._close_indicies()

    # def prepare_field(self, obj, field):
    #     if isinstance(field, SearchField):
    #         yield (unidecode(self.prepare_value(field.get_value(obj))),
    #                get_weight(field.boost))
    #     elif isinstance(field, RelatedFields):
    #         sub_obj = field.get_value(obj)
    #         if sub_obj is None:
    #             return
    #         if isinstance(sub_obj, Manager):
    #             sub_objs = sub_obj.all()
    #         else:
    #             if callable(sub_obj):
    #                 sub_obj = sub_obj()
    #             sub_objs = [sub_obj]
    #         for sub_obj in sub_objs:
    #             for sub_field in field.fields:
    #                 for value in self.prepare_field(sub_obj, sub_field):
    #                     yield value

    def add_items(self, model, items):
        for add_model in self.models:
            index = self.indicies[add_model._meta.label]
            writer = AsyncWriter(index)
            for item in items:
                doc = self._create_document(add_model, item)
                writer.update_document(**doc)
            writer.commit()
        self._close_indicies()

    def delete_item(self, obj):
        # TODO
        whoosh_id = get_identifier(obj)

        try:
            index = self.backend.index.refresh()
            writer = index.writer()
            writer.delete_by_query(q=self.backend.parser.parse('%s:"%s"' % (ID, whoosh_id)))
            writer.commit()
        except Exception as e:
            raise e

    def __str__(self):
        return self.name


class WhooshSearchQueryCompiler(BaseSearchQueryCompiler):
    DEFAULT_OPERATOR = 'or'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields_names = list(self._get_fields_names())
        self.schema = ModelSchema(self.queryset.model).build_schema()

    def _get_fields_names(self):
        model = self.queryset.model
        return [field.field_name for field in model.get_searchable_search_fields()]

    def get_whoosh_query(self):
        parser = MultifieldParser(self.fields_names, self.schema)
        return parser.parse(force_text(self.query.query_string))

    def search(self, backend, start, stop):
        # TODO: Handle MatchAll nested inside other search query classes.
        # if isinstance(self.query, MatchAll):
        #     return self.queryset[start:stop]

        config = backend.get_config()
        queryset = self.queryset

        models = get_descendant_models(queryset.model)
        search_kwargs = {
            'filter': wquery.Or([wquery.Term(DJANGO_CT, get_model_ct(m)) for m in models]),
            'limit': None
        }

        searcher = backend.index.searcher()
        results = searcher.search(
            backend.parser.parse(self.build_whoosh_query(config=config)),
            **search_kwargs
        )
        django_id_ls = [r['django_id'] for r in results]
        searcher.close()

        if not django_id_ls:
            return queryset.none()

        queryset = queryset.filter(pk__in=django_id_ls)
        queryset = queryset.order_by('-pk')

        # support search on specific fields
        if self.fields:
            q = self.build_database_filter()
            queryset = queryset.filter(q)

        return queryset.distinct()[start:stop]

    def _process_lookup(self, field, lookup, value):
        # FIXME whooshify
        return Q(**{field.get_attname(self.queryset.model) +
                    '__' + lookup: value})

    def _connect_filters(self, filters, connector, negated):
        pass
        # if connector == 'AND':
        #     q = Q(*filters)
        # elif connector == 'OR':
        #     q = OR([Q(fil) for fil in filters])
        # else:
        #     return
        #
        # if negated:
        #     q = ~q
        #
        # return q

    def build_single_term_filter(self, term):
        term_query = models.Q()
        for field_name in self.fields_names:
            term_query |= models.Q(**{field_name + '__icontains': term})
        return term_query

    def _build_whoosh_query2(self, query, field):
        if isinstance(query, MatchAll):
            pass

        raise NotImplementedError(
            '`%s` is not supported by the whoosh search backend.'
            % self.query.__class__.__name__)


class WhooshSearchResults(BaseSearchResults):
    def _do_search(self):
        # Probably better way to get the model
        model = self.query_compiler.queryset.model
        query = self.query_compiler.get_whoosh_query()

        index = self.backend.storage.open_index(indexname=model._meta.label)
        with index.searcher() as searcher:
            results = searcher.search(query, limit=None)
            score_map = OrderedDict([(r['django_id'], r.score) for r in results])
        self.backend.storage.close()

        django_ids = score_map.keys()
        if not django_ids:
            return []
        # Retrieve the results from the db, but preserve the order by score
        preserved_order = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(django_ids)])
        results = model.objects.filter(pk__in=django_ids).order_by(preserved_order)
        results = results.distinct()[self.start:self.stop]

        # Add score annotations if required
        if self._score_field:
            for obj in results:
                setattr(obj, self._score_field, score_map.get(str(obj.pk)))
        return results

    def _do_count(self):
        # TODO
        return 1
        # return self.query_compiler.search(
        #     self.backend, None, None).count()


class WhooshSearchRebuilder:
    def __init__(self, index):
        self.index = index

    def start(self):
        self.index.backend.refresh_index()
        return self.index

    def finish(self):
        self.index.backend.refresh_index()


class WhooshSearchBackend(BaseSearchBackend):
    query_compiler_class = WhooshSearchQueryCompiler
    results_class = WhooshSearchResults
    rebuilder_class = WhooshSearchRebuilder

    def __init__(self, params):
        super().__init__(params)
        self.params = params

        self.setup_complete = False
        self.use_file_storage = True
        self.post_limit = params.get("POST_LIMIT", 128 * 1024 * 1024)
        self.path = params.get("PATH")

        self.check()
        self.refresh_index(optimize=False)

    def check(self):
        # Make sure the index is there.
        if self.use_file_storage and not os.path.exists(self.path):
            os.makedirs(self.path)

        if self.use_file_storage and not os.access(self.path, os.W_OK):
            raise IOError(
                "The path to your Whoosh index '%s' is not writable for the current user/group."
                % self.path
            )

        if self.use_file_storage:
            self.storage = FileStorage(self.path)

        # self.schema = self.build_schema()
        # self.content_field_name = "text"

        # self.parser = QueryParser(self.content_field_name, schema=self.schema)
        # self.parser.add_plugins([FuzzyTermPlugin])

    def get_config(self):
        return self.params.get('SEARCH_CONFIG')

    def get_index_for_model(self, model, db_alias=None):
        return WhooshIndex(self, model, db_alias)

    def get_index_for_object(self, obj):
        return self.get_index_for_model(obj._meta.model, obj._state.db)

    def reset_index(self):
        # Per the Whoosh mailing list, if wiping out everything from the index,
        # it's much more efficient to simply delete the index files.
        if self.use_file_storage and os.path.exists(self.path):
            shutil.rmtree(self.path)
        elif not self.use_file_storage:
            self.storage.clean()

        # Recreate everything.
        self.setup()

    def add_type(self, model):
        self.get_index_for_model(model).add_model(model)

    def refresh_index(self, optimize=True):
        pass
        # if not self.setup_complete:
        #     self.setup()
        # else:
        #     self.index = self.index.refresh()
        # if optimize:
        #     # optimize is a locking operation, shouldn't be called unless recreating the index
        #     self.index.optimize()

    def add(self, obj):
        self.get_index_for_object(obj).add_item(obj)

    def add_bulk(self, model, obj_list):
        self.get_index_for_model(model).add_items(model, obj_list)

    def delete(self, obj):
        self.get_index_for_object(obj).delete_item(obj)


SearchBackend = WhooshSearchBackend
