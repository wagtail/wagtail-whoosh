import os
import shutil

from django.db import DEFAULT_DB_ALIAS, models
from django.db.models import Case, Q, When
from django.utils.encoding import force_text

from wagtail.search.backends.base import (BaseSearchBackend,
                                          BaseSearchQueryCompiler,
                                          BaseSearchResults)
from wagtail.search.index import (AutocompleteField, FilterField,
                                  RelatedFields, SearchField)
from wagtail.search.query import And, Boost, MatchAll, Not, Or, PlainText
from wagtail.search.utils import OR

from whoosh import qparser
from whoosh.fields import ID as WHOOSH_ID
from whoosh.fields import NGRAMWORDS, TEXT, Schema
from whoosh.filedb.filestore import FileStorage
from whoosh.qparser import FuzzyTermPlugin, MultifieldParser
from whoosh.writing import AsyncWriter

from .utils import (get_boost, get_descendant_models, get_indexed_parents,
                    unidecode)

PK = "pk"
AUTOCOMPLETE_SUFFIX = '_ngrams'
FILTER_SUFFIX = '_filter'


def _get_field_mapping(field):
    if isinstance(field, FilterField):
        return field.field_name + FILTER_SUFFIX
    elif isinstance(field, AutocompleteField):
        return field.field_name + AUTOCOMPLETE_SUFFIX
    return field.field_name


class ModelSchema:
    def __init__(self, model):
        self.model = model

    def build_schema(self):
        search_fields = dict(self._define_search_fields())
        schema_fields = {
            PK: WHOOSH_ID(stored=True, unique=True),
        }
        schema_fields.update(search_fields)
        return Schema(**schema_fields)

    def _define_search_fields(self):
        def _to_whoosh_field(field, field_name=None):
            if isinstance(field, AutocompleteField) or \
                    (hasattr(field, 'partial_match') and field.partial_match):
                whoosh_field = NGRAMWORDS(stored=True, minsize=2, maxsize=8, queryor=True)
            else:
                # TODO other types of fields https://whoosh.readthedocs.io/en/latest/api/fields.htm
                whoosh_field = TEXT(phrase=True, stored=True)

            if not field_name:
                field_name = _get_field_mapping(field)
            return field_name, whoosh_field

        for field in self.model.get_search_fields():
            if isinstance(field, RelatedFields):
                for subfield in field.fields:
                    # Redefine field_name to avoid clashes
                    field_name = '{0}__{1}'.format(field.field_name, _get_field_mapping(subfield))
                    yield _to_whoosh_field(subfield, field_name=field_name)
            else:
                yield _to_whoosh_field(field)


class WhooshIndex:
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
        # Adding done on initialisation
        self._close_indicies()

    def refresh(self):
        for index in self.indicies.values():
            index.refresh()

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
        for model in self.models:
            doc = self._create_document(model, item)
            index = self.indicies[model._meta.label]
            writer = AsyncWriter(index)
            writer.update_document(**doc)
            writer.commit()
        self._close_indicies()

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
        for model in self.models:
            index = self.indicies[model._meta.label]
            writer = index.writer()
            writer.delete_by_term(PK, str(obj.pk))
            writer.commit()
            index.optimize()
        self._close_indicies()

    def __str__(self):
        return self.name


class WhooshSearchQueryCompiler(BaseSearchQueryCompiler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.operator = kwargs.get('operator', None)
        self.field_names = list(self._get_fields_names())
        self.schema = ModelSchema(self.queryset.model).build_schema()

    def _get_fields_names(self):
        if self.fields:
            for f in self.fields:
                yield f
            return
        model = self.queryset.model
        for field in model.get_search_fields():
            if isinstance(field, RelatedFields):
                for sub_field in field.fields:
                    yield '{0}__{1}'.format(field.field_name, _get_field_mapping(sub_field))
            else:
                yield _get_field_mapping(field)

    def _build_query_string(self, query=None):
        """
            Converts Wagtail query operators to their Whoosh equivalents
        """
        if query is None:
            query = self.query

        if isinstance(query, MatchAll):
            return '*'
        if isinstance(query, PlainText):
            return unidecode(query.query_string)
        if isinstance(query, Boost):
            # https://whoosh.readthedocs.io/en/latest/querylang.html#boosting-query-elements
            return '({0})^{1}'.format(
                self._build_query_string(query.subquery), query.boost)
        if isinstance(query, Not):
            return ' NOT {}'.format(
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

    def _get_group(self):
        if self.operator and self.operator == 'and':
            return qparser.AndGroup
        return qparser.OrGroup

    def _get_plugins(self):
        # Overridable
        return [FuzzyTermPlugin()]

    def get_whoosh_query(self):
        group = self._get_group()
        parser = MultifieldParser(self.field_names, self.schema, group=group)
        [parser.add_plugin(pin) for pin in self._get_plugins()]
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


class WhooshAutocompleteQueryCompiler(WhooshSearchQueryCompiler):
    def _get_fields_names(self):
        model = self.queryset.model
        for field in model.get_autocomplete_search_fields():
            yield _get_field_mapping(field)


class WhooshSearchResults(BaseSearchResults):
    supports_facet = False

    def _new_query_compiler(self, model):
        if isinstance(self.query_compiler, WhooshAutocompleteQueryCompiler):
            return WhooshAutocompleteQueryCompiler(
                model.objects.none(),
                self.query_compiler.query,
                fields=self.query_compiler.fields,
                operator=self.query_compiler.operator)
        return WhooshSearchQueryCompiler(
            model.objects.none(),
            self.query_compiler.query,
            fields=self.query_compiler.fields,
            operator=self.query_compiler.operator)

    def _do_search(self):
        # Probably better way to get the model
        qc = self.query_compiler
        model = qc.queryset.model
        query = qc.get_whoosh_query()
        index = self.backend.storage.open_index(indexname=model._meta.label)
        with index.searcher() as searcher:
            results = searcher.search(query, limit=None)
            score_map = dict([(r[PK], r.score) for r in results])

        descendants = get_descendant_models(model)
        for descendant in descendants:
            query_compiler = self._new_query_compiler(descendant)
            query = query_compiler.get_whoosh_query()
            index = self.backend.storage.open_index(indexname=descendant._meta.label)
            with index.searcher() as searcher:
                results = searcher.search(query, limit=None)
                for result in results:
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
        # FIXME https://whoosh.readthedocs.io/en/latest/api/collectors.html#whoosh.collectors.Collector.count
        return len(self._do_search())

    def facet(self, field_name):
        # TODO
        super().facet(field_name)


class WhooshSearchRebuilder:
    def __init__(self, index):
        self.index = index

    def start(self):
        if self.index.backend.destroy_index:
            # Per the Whoosh mailing list, if wiping out everything from the index,
            # it's much more efficient to simply delete the index files.
            shutil.rmtree(self.index.backend.path)
            os.makedirs(self.index.backend.path)
        # recreate + open indicies
        self.index.indicies = dict(self.index._open_indicies())
        return self.index

    def finish(self):
        self.index.backend.destroy_index = False
        self.index.refresh()


class WhooshSearchBackend(BaseSearchBackend):
    query_compiler_class = WhooshSearchQueryCompiler
    autocomplete_query_compiler_class = WhooshAutocompleteQueryCompiler
    results_class = WhooshSearchResults
    rebuilder_class = WhooshSearchRebuilder

    def __init__(self, params):
        super().__init__(params)
        self.params = params

        self.use_file_storage = True
        self.path = params.get("PATH")
        # Flag for rebuilder, we only want the index folder emptied by the
        # first WhooshSearchRebuilder ran
        self.destroy_index = True

        self.check()

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

    def get_index_for_model(self, model, db_alias=None):
        return WhooshIndex(self, model, db_alias)

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


SearchBackend = WhooshSearchBackend
