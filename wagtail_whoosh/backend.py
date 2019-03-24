import os
import re
import shutil
from collections import OrderedDict
from warnings import warn

from django.db import DEFAULT_DB_ALIAS, models
from django.db.models import Case, Manager, Q, When
from django.utils import six
from django.utils.encoding import force_text

from wagtail.search import index
from wagtail.search.backends.base import (BaseSearchBackend,
                                          BaseSearchQueryCompiler,
                                          BaseSearchResults)
from wagtail.search.index import RelatedFields, SearchField
from wagtail.search.query import (And, MatchAll, Not, Or, SearchQueryShortcut,
                                  Term)
from wagtail.search.utils import AND, OR

from whoosh import query as wquery
from whoosh.fields import ID as WHOOSH_ID
from whoosh.fields import TEXT, Schema
from whoosh.filedb.filestore import FileStorage
from whoosh.qparser import FuzzyTermPlugin, QueryParser
from whoosh.writing import AsyncWriter

from .utils import get_descendant_models, get_weight, unidecode

ID = "id"
DJANGO_CT = "django_ct"
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


class Index:
    def __init__(self, backend, model, db_alias=None):
        self.backend = backend
        self.model = model
        if db_alias is None:
            db_alias = DEFAULT_DB_ALIAS
        self.db_alias = db_alias
        self.name = model._meta.label
        self.search_fields = self.model.get_search_fields()

    def add_model(self, model):
        pass

    def refresh(self):
        pass

    def prepare_value(self, value):
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return ', '.join(self.prepare_value(item) for item in value)
        if isinstance(value, dict):
            return ', '.join(self.prepare_value(item)
                             for item in value.values())
        return force_text(value)

    def prepare_field(self, obj, field):
        if isinstance(field, SearchField):
            yield (unidecode(self.prepare_value(field.get_value(obj))),
                   get_weight(field.boost))
        elif isinstance(field, RelatedFields):
            sub_obj = field.get_value(obj)
            if sub_obj is None:
                return
            if isinstance(sub_obj, Manager):
                sub_objs = sub_obj.all()
            else:
                if callable(sub_obj):
                    sub_obj = sub_obj()
                sub_objs = [sub_obj]
            for sub_obj in sub_objs:
                for sub_field in field.fields:
                    for value in self.prepare_field(sub_obj, sub_field):
                        yield value

    def prepare_body(self, obj):
        body_ls = [
            value for field in self.search_fields
            for value, boost in self.prepare_field(obj, field)
        ]
        return " ".join(body_ls)

    def add_item(self, obj):
        self.add_items(self.model, [obj])

    def _delete_parent_model_data(self, model, objs):
        parent_models = model._meta.get_parent_list()

        for parent_model in parent_models:
            model_ct = get_model_ct(parent_model)
            query_string = " OR ".join([
                "%s.%s" % (model_ct, obj.pk)
                for obj in objs
            ])

            try:
                index = self.backend.index.refresh()
                writer = index.writer()
                writer.delete_by_query(q=self.backend.parser.parse('%s:"%s"' % (ID, query_string)))
                writer.commit()
            except Exception as e:
                raise e

    def add_items(self, model, objs):
        for obj in objs:
            obj._body_ = self.prepare_body(obj)

        self._delete_parent_model_data(model, objs)

        index = self.backend.index.refresh()
        writer = AsyncWriter(index)

        for obj in objs:
            doc = {
                ID: get_identifier(obj),
                DJANGO_CT: get_model_ct(obj),
                DJANGO_ID: force_text(obj.pk),
                'text': force_text(obj._body_),
            }

            try:
                writer.update_document(**doc)
            except Exception as e:
                raise e

        if len(objs) > 0:
            writer.commit()

    def delete_item(self, obj):
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
    DEFAULT_OPERATOR = 'and'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields_names = list(self.get_fields_names())

    def get_fields_names(self):
        model = self.queryset.model
        fields_names = self.fields or [field.field_name for field in
                                       model.get_searchable_search_fields()]
        # Check if the field exists (this will filter out indexed callables)
        for field_name in fields_names:
            try:
                model._meta.get_field(field_name)
            except models.fields.FieldDoesNotExist:
                continue
            else:
                yield field_name

    def build_whoosh_query(self, query=None, config=None):
        if query is None:
            query = self.query

        if isinstance(query, SearchQueryShortcut):
            return self.build_whoosh_query(query.get_equivalent(), config)
        if isinstance(query, Term):
            return unidecode(query.term)
        if isinstance(query, Not):
            return ' NOT {}'.format(
                self.build_whoosh_query(query.subquery, config)
            )
        if isinstance(query, And):
            return ' AND '.join([
                self.build_whoosh_query(subquery, config)
                for subquery in query.subqueries
            ])
        if isinstance(query, Or):
            return ' OR '.join([
                self.build_whoosh_query(subquery, config)
                for subquery in query.subqueries
            ])

        raise NotImplementedError(
            '`%s` is not supported by the whoosh search backend.'
            % self.query.__class__.__name__)

    def search(self, backend, start, stop, score_field=None):
        # TODO: Handle MatchAll nested inside other search query classes.
        if isinstance(self.query, MatchAll):
            return self.queryset[start:stop]

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
        # Results are returned by order of relevance, OrderedDict used to keep track
        score_map = OrderedDict([(r['django_id'], r.score) for r in results])
        searcher.close()

        django_id_ls = score_map.keys()
        if not django_id_ls:
            return queryset.none()

        # Retrieve the results from the db, but preserve the order by score
        preserved_order = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(django_id_ls)])
        queryset = queryset.filter(pk__in=django_id_ls).order_by(preserved_order)

        # support search on specific fields
        if self.fields:
            q = self.build_database_filter()
            queryset = queryset.filter(q)

        queryset = queryset.distinct()[start:stop]

        # Add score annotations if required
        if score_field:
            for obj in queryset:
                setattr(obj, score_field, score_map.get(str(obj.pk)))

        return queryset

    def _process_lookup(self, field, lookup, value):
        return Q(**{field.get_attname(self.queryset.model) +
                    '__' + lookup: value})

    def _connect_filters(self, filters, connector, negated):
        if connector == 'AND':
            q = Q(*filters)
        elif connector == 'OR':
            q = OR([Q(fil) for fil in filters])
        else:
            return

        if negated:
            q = ~q

        return q

    def build_single_term_filter(self, term):
        term_query = models.Q()
        for field_name in self.fields_names:
            term_query |= models.Q(**{field_name + '__icontains': term})
        return term_query

    def build_database_filter(self, query=None):
        if query is None:
            query = self.query

        if isinstance(self.query, MatchAll):
            return models.Q()

        if isinstance(query, SearchQueryShortcut):
            return self.build_database_filter(query.get_equivalent())
        if isinstance(query, Term):
            if query.boost != 1:
                warn('Database search backend does not support term boosting.')
            return self.build_single_term_filter(query.term)
        if isinstance(query, Not):
            return ~self.build_database_filter(query.subquery)
        if isinstance(query, And):
            return AND(self.build_database_filter(subquery)
                       for subquery in query.subqueries)
        if isinstance(query, Or):
            return OR(self.build_database_filter(subquery)
                      for subquery in query.subqueries)
        raise NotImplementedError(
            '`%s` is not supported by the database search backend.'
            % self.query.__class__.__name__)


class WhooshSearchResults(BaseSearchResults):
    def _do_search(self):
        return list(self.query_compiler.search(
            self.backend, self.start, self.stop, score_field=self._score_field))

    def _do_count(self):
        return self.query_compiler.search(
            self.backend, None, None, score_field=self._score_field).count()


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

        self.setup()
        self.refresh_index(optimize=False)

    def setup(self):
        """
        Defers loading until needed.
        """
        new_index = False

        # Make sure the index is there.
        if self.use_file_storage and not os.path.exists(self.path):
            os.makedirs(self.path)
            new_index = True

        if self.use_file_storage and not os.access(self.path, os.W_OK):
            raise IOError(
                "The path to your Whoosh index '%s' is not writable for the current user/group."
                % self.path
            )

        if self.use_file_storage:
            self.storage = FileStorage(self.path)

        self.schema = self.build_schema()
        self.content_field_name = "text"

        self.parser = QueryParser(self.content_field_name, schema=self.schema)
        self.parser.add_plugins([FuzzyTermPlugin])

        if new_index is True:
            self.index = self.storage.create_index(self.schema)
        else:
            try:
                self.index = self.storage.open_index(schema=self.schema)
            except index.EmptyIndexError:
                self.index = self.storage.create_index(self.schema)

        self.setup_complete = True

    def build_schema(self):
        schema_fields = {
            'id': WHOOSH_ID(stored=True, unique=True),
            'django_ct': WHOOSH_ID(stored=True),
            'django_id': WHOOSH_ID(stored=True),
            'text': TEXT(stored=True),
        }

        return Schema(**schema_fields)

    def get_config(self):
        return self.params.get('SEARCH_CONFIG')

    def get_index_for_model(self, model, db_alias=None):
        return Index(self, model, db_alias)

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
        pass  # Not needed.

    def refresh_index(self, optimize=True):
        if not self.setup_complete:
            self.setup()
        else:
            self.index = self.index.refresh()
        if optimize:
            # optimize is a locking operation, shouldn't be called unless recreating the index
            self.index.optimize()

    def add(self, obj):
        self.get_index_for_object(obj).add_item(obj)

    def add_bulk(self, model, obj_list):
        if obj_list:
            self.get_index_for_object(obj_list[0]).add_items(model, obj_list)

    def delete(self, obj):
        self.get_index_for_object(obj).delete_item(obj)


SearchBackend = WhooshSearchBackend
