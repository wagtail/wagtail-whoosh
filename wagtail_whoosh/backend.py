import os
import shutil
from warnings import warn

from django.core.exceptions import ImproperlyConfigured
from django.db import DEFAULT_DB_ALIAS, models
from django.db.models import Case, Q, When
from django.utils.encoding import force_text
from django.utils.module_loading import import_string

from wagtail.search.backends.base import (BaseSearchBackend,
                                          BaseSearchQueryCompiler,
                                          BaseSearchResults)
from wagtail.search.index import (AutocompleteField, FilterField,
                                  RelatedFields, SearchField)
from wagtail.search.query import And, Boost, MatchAll, Not, Or, PlainText
from wagtail.search.utils import AND, OR

from whoosh import lang
from whoosh.analysis import analyzers
from whoosh.fields import ID as WHOOSH_ID
from whoosh.fields import NGRAMWORDS, TEXT, Schema
from whoosh.filedb.filestore import FileStorage
from whoosh.index import EmptyIndexError
from whoosh.qparser import FuzzyTermPlugin, MultifieldParser, QueryParser
from whoosh.writing import AsyncWriter

from .utils import get_boost, get_descendant_models, unidecode

PK = "pk"
AUTOCOMPLETE_SUFFIX = '_ngrams'
FILTER_SUFFIX = '_filter'


def _get_field_mapping(field):
    if isinstance(field, FilterField):
        return field.field_name + FILTER_SUFFIX
    elif isinstance(field, AutocompleteField):
        return field.field_name + AUTOCOMPLETE_SUFFIX
    return field.field_name


class WhooshModelIndex:
    def __init__(self, backend, model, db_alias=None):
        self.backend = backend
        self.model = model
        # TODO: support db_alias
        if db_alias is None:
            db_alias = DEFAULT_DB_ALIAS
        self.db_alias = db_alias
        self.name = model._meta.label
        self.model_index = self._open_model_index()

    def _open_model_index(self):
        storage = self.backend.storage
        model = self.model
        label = model._meta.label
        # if index doesn't exist, create
        if not storage.index_exists(indexname=label):
            schema = self.backend.build_schema(self.model)
            storage.create_index(schema, indexname=label)
        # return the opened index to work with
        return storage.open_index(indexname=label)

    def _close_model_index(self):
        self.backend.storage.close()

    def add_model(self, model):
        # Adding done on initialisation
        self._close_model_index()

    def refresh(self):
        self.model_index.refresh()

    def prepare_value(self, value):
        if not value:
            return ''
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return ', '.join(self.prepare_value(item) for item in value)
        if isinstance(value, dict):
            return ', '.join(self.prepare_value(item)
                             for item in value.values())
        if callable(value):
            return force_text(value())
        return force_text(value)

    def _get_document_fields(self, model, item):
        for field in model.get_search_fields():
            if isinstance(field, (SearchField, FilterField, AutocompleteField)):
                yield _get_field_mapping(field), self.prepare_value(field.get_value(item))
            if isinstance(field, RelatedFields):
                value = field.get_value(item)
                if isinstance(value, (models.Manager, models.QuerySet)):
                    qs = value.all()
                    for sub_field in field.fields:
                        sub_values = qs.values_list(sub_field.field_name, flat=True)
                        yield '{0}__{1}'.format(field.field_name, _get_field_mapping(sub_field)), \
                            self.prepare_value(list(sub_values))
                if isinstance(value, models.Model):
                    for sub_field in field.fields:
                        yield '{0}__{1}'.format(field.field_name, _get_field_mapping(sub_field)),\
                            self.prepare_value(sub_field.get_value(value))

    def _create_document(self, model, item):
        doc_fields = dict(self._get_document_fields(model, item))
        document = {
            PK: force_text(item.pk)
        }
        document.update(doc_fields)
        return document

    def add_item(self, item):
        model = self.model
        doc = self._create_document(model, item)
        index = self.model_index
        writer = AsyncWriter(index)
        writer.update_document(**doc)
        writer.commit()
        self._close_model_index()

    def add_items(self, item_model, items):
        model = self.model
        index = self.model_index
        writer = AsyncWriter(index)
        for item in items:
            doc = self._create_document(model, item)
            writer.update_document(**doc)
        writer.commit()
        self._close_model_index()

    def delete_item(self, obj):
        index = self.model_index
        writer = index.writer()
        writer.delete_by_term(PK, str(obj.pk))
        writer.commit()
        # TODO: do this in other method
        index.optimize()
        self._close_model_index()

    def __str__(self):
        return self.name


class WhooshSearchQueryCompiler(BaseSearchQueryCompiler):
    def __init__(self, *args, **kwargs):
        # TODO: Always pass the backend in query classes instead.
        self.backend = kwargs.pop('backend')
        super().__init__(*args, **kwargs)
        self.operator = kwargs.get('operator', self.DEFAULT_OPERATOR)
        self.field_names = list(self._get_fields_names())
        self.schema = self.backend.build_schema(self.queryset.model)

    def _get_fields_names(self):
        if self.fields:
            for f in self.fields:
                yield f
            return
        model = self.queryset.model
        for field in model.get_search_fields():
            if isinstance(field, AutocompleteField):
                continue
            if isinstance(field, RelatedFields):
                for sub_field in field.fields:
                    yield '{0}__{1}'.format(field.field_name, _get_field_mapping(sub_field))
            else:
                yield _get_field_mapping(field)

    def prepare_word(self, word):
        return unidecode(word)

    def _build_query_string(self, query=None):
        """
        Converts Wagtail query operators to their Whoosh equivalents
        """
        if query is None:
            query = self.query

        if isinstance(query, MatchAll):
            return '*'
        if isinstance(query, PlainText):
            query_params = []
            for word in query.query_string.split():
                query_params.append(self.prepare_word(word))
            operator = " %s " % query.operator.upper()
            return operator.join(query_params)
        if isinstance(query, Boost):
            # https://whoosh.readthedocs.io/en/latest/querylang.html#boosting-query-elements
            return '({0})^{1}'.format(
                self._build_query_string(query.subquery), query.boost)
        if isinstance(query, Not):
            return ' NOT ({})'.format(
                self._build_query_string(query.subquery)
            )
        if isinstance(query, And):
            return ' AND '.join([
                self._build_query_string(subquery)
                for subquery in query.subqueries
            ])
        if isinstance(query, Or):
            return ' OR '.join([
                self._build_query_string(subquery)
                for subquery in query.subqueries
            ])

        raise NotImplementedError(
            '`%s` is not supported by the whoosh search backend.'
            % self.query.__class__.__name__)

    def get_whoosh_query(self):
        parser = MultifieldParser(self.field_names, self.schema)
        return parser.parse(self._build_query_string())

    def _process_lookup(self, field, lookup, value):
        # TODO whooshify
        return Q(**{field.get_attname(self.queryset.model) +
                    '__' + lookup: value})

    def _connect_filters(self, filters, connector, negated):
        # TODO whooshify
        if connector == 'AND':
            q = Q(*filters)
        elif connector == 'OR':
            q = OR([Q(fil) for fil in filters])
        else:
            return

        if negated:
            q = ~q

        return q

    #####################################################################################
    # this part is copied from wagtail/search/backends/db.py to make it work with filter
    #####################################################################################

    def build_single_term_filter(self, term):
        term_query = models.Q()
        for field_name in self.fields_names:
            term_query |= models.Q(**{field_name + '__icontains': term})
        return term_query

    OPERATORS = {
        'and': AND,
        'or': OR,
    }

    def check_boost(self, query, boost=1.0):
        if query.boost * boost != 1.0:
            warn('Database search backend does not support term boosting.')

    def build_database_filter(self, query=None, boost=1.0):
        if query is None:
            query = self.query

        if isinstance(query, PlainText):
            self.check_boost(query, boost=boost)

            operator = self.OPERATORS[query.operator]

            return operator([
                self.build_single_term_filter(term)
                for term in query.query_string.split()
            ])

        if isinstance(query, Boost):
            boost *= query.boost
            return self.build_database_filter(query.subquery, boost=boost)

        if isinstance(self.query, MatchAll):
            return models.Q()

        if isinstance(query, Not):
            return ~self.build_database_filter(query.subquery, boost=boost)
        if isinstance(query, And):
            return AND(self.build_database_filter(subquery, boost=boost)
                       for subquery in query.subqueries)
        if isinstance(query, Or):
            return OR(self.build_database_filter(subquery, boost=boost)
                      for subquery in query.subqueries)
        raise NotImplementedError(
            '`%s` is not supported by the database search backend.'
            % query.__class__.__name__)


class WhooshAutocompleteQueryCompiler(WhooshSearchQueryCompiler):
    def _get_fields_names(self):
        model = self.queryset.model
        for field in model.get_autocomplete_search_fields():
            yield _get_field_mapping(field)


class WhooshSearchResults(BaseSearchResults):
    supports_facet = False

    def _new_query_compiler(self, model):
        qc = self.query_compiler
        if isinstance(qc, WhooshAutocompleteQueryCompiler):
            return WhooshAutocompleteQueryCompiler(
                model.objects.none(),
                qc.query,
                fields=qc.fields,
                operator=qc.operator,
                backend=self.backend
            )
        return WhooshSearchQueryCompiler(
            model.objects.none(),
            qc.query,
            fields=qc.fields,
            operator=qc.operator,
            backend=self.backend
        )

    def _do_search(self):
        # Probably better way to get the model
        qc = self.query_compiler
        model = qc.queryset.model

        results = []
        score_map = {}

        descendants = get_descendant_models(model)
        for descendant in descendants:
            query_compiler = self._new_query_compiler(descendant)
            query = query_compiler.get_whoosh_query()
            index = self.backend.storage.open_index(indexname=descendant._meta.label)
            with index.searcher() as searcher:
                descendant_results = searcher.search(query, limit=None)
                for result in descendant_results:
                    results.append(result)
                    pk = result[PK]
                    # Add to the score map, or update if higher value
                    if pk not in score_map or score_map[pk] < result.score:
                        score_map[pk] = result.score

        self.backend.storage.close()

        django_ids = [r[0] for r in sorted(
            score_map.items(), key=lambda pk_score: pk_score[1], reverse=True)]
        if not django_ids:
            return []

        if qc.order_by_relevance:
            # Retrieve the results from the db, but preserve the order by score
            preserved_order = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(django_ids)])
            results = qc.queryset.filter(pk__in=django_ids).order_by(preserved_order)
        else:
            results = qc.queryset.filter(pk__in=django_ids)
        results = results.distinct()[self.start:self.stop]

        # Add score annotations if required
        if self._score_field:
            for obj in results:
                setattr(obj, self._score_field, score_map.get(str(obj.pk)))
        return results

    def _do_count(self):
        return len(self._do_search())

    def facet(self, field_name):
        # TODO
        super().facet(field_name)


class WhooshSearchRebuilder:
    def __init__(self, model_index):
        self.model_index = model_index

    def start(self):
        """
        TODO: https://whoosh.readthedocs.io/en/latest/indexing.html#id1
        use writing.CLEAR instead of shutil.rmtree
        """
        if not self.model_index.backend.recreate_path_already:
            # Per the Whoosh mailing list, if wiping out everything from the index,
            # it's much more efficient to simply delete the index files.
            shutil.rmtree(self.model_index.backend.path)
            os.makedirs(self.model_index.backend.path)

            # we change flag so index directory would be only deleted one time when run update_index
            self.model_index.backend.recreate_path_already = True

        self.model_index.model_index = self.model_index._open_model_index()
        return self.model_index

    def finish(self):
        self.model_index.refresh()


class WhooshSearchBackend(BaseSearchBackend):
    query_compiler_class = WhooshSearchQueryCompiler
    autocomplete_query_compiler_class = WhooshAutocompleteQueryCompiler
    results_class = WhooshSearchResults
    rebuilder_class = WhooshSearchRebuilder

    def __init__(self, params):
        super().__init__(params)
        self.params = params
        self._config_params(params)

        self.use_file_storage = True
        self.path = params.get("PATH")
        # Flag for rebuilder, we only want the index folder emptied by the
        # first WhooshSearchRebuilder ran
        self.recreate_path_already = False

        self.check_storage()

    def _config_params(self, params):
        self.language = None
        language = params.get('LANGUAGE')
        if language:
            # check if LANGUAGE is valid
            if language in lang.languages:
                self.language = language
            else:
                raise ImproperlyConfigured(
                    'Wagtail Whoosh Backend: Language %s could not be loaded' %
                    language,
                )

        self.analyzer = None
        analyzer = params.get('ANALYZER')
        if analyzer:
            if isinstance(analyzer, str):
                try:
                    self.analyzer = import_string(analyzer)
                except ImportError:
                    raise ImproperlyConfigured(
                        'Wagtail Whoosh Backend: Analyzer %s could not be loaded' %
                        analyzer,
                    )
            elif isinstance(analyzer, analyzers.Analyzer):
                self.analyzer = analyzer
            else:
                raise ImproperlyConfigured(
                    'Wagtail Whoosh Backend analyzer: Expected string or subclass of '
                    '"whoosh.analysis.analyzers.Analyzer", found %s' %
                    type(analyzer),
                )

    def check_storage(self):
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

    def get_index_for_model(self, model, db_alias=None):
        return WhooshModelIndex(self, model, db_alias)

    def get_index_for_object(self, obj):
        return self.get_index_for_model(obj._meta.model, obj._state.db)

    def add_type(self, model):
        self.get_index_for_model(model).add_model(model)

    def add(self, obj):
        self.get_index_for_object(obj).add_item(obj)

    def add_bulk(self, model, obj_list):
        self.get_index_for_model(model).add_items(model, obj_list)

    def delete(self, obj):
        self.get_index_for_object(obj).delete_item(obj)

    # TODO: Always pass the backend in query classes.
    def query_compiler_class(self, *args, **kwargs):
        kwargs['backend'] = self
        return WhooshSearchQueryCompiler(*args, **kwargs)

    def autocomplete_query_compiler_class(self, *args, **kwargs):
        kwargs['backend'] = self
        return WhooshAutocompleteQueryCompiler(*args, **kwargs)

    ################################################################################
    #  Custom methods about schema
    ################################################################################

    def build_schema(self, model):
        search_fields = dict(self._prepare_search_fields(model))
        schema_fields = {
            PK: WHOOSH_ID(stored=True, unique=True),
        }
        schema_fields.update(search_fields)
        return Schema(**schema_fields)

    def _to_whoosh_field(self, field, field_name=None):
        # If the field is AutocompleteField or has partial_match field, treat it as auto complete field
        if isinstance(field, AutocompleteField) or \
                (hasattr(field, 'partial_match') and field.partial_match):
            # TODO: make NGRAMWORDS configurable
            whoosh_field = NGRAMWORDS(stored=False, minsize=2, maxsize=8, queryor=True)
        else:
            # TODO other types of fields https://whoosh.readthedocs.io/en/latest/api/fields.htm
            whoosh_field = TEXT(
                stored=False,
                field_boost=get_boost(field),
                lang=self.language,
                analyzer=self.analyzer,
            )

        if not field_name:
            field_name = _get_field_mapping(field)
        return field_name, whoosh_field

    def _prepare_search_fields(self, model):
        for field in model.get_search_fields():
            if isinstance(field, RelatedFields):
                for subfield in field.fields:
                    # Redefine field_name to avoid clashes
                    field_name = '{0}__{1}'.format(field.field_name, _get_field_mapping(subfield))
                    yield self._to_whoosh_field(subfield, field_name=field_name)
            else:
                yield self._to_whoosh_field(field)


SearchBackend = WhooshSearchBackend
