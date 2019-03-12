import os
import shutil

from django.db import DEFAULT_DB_ALIAS, models
from django.db.models import Case, Manager, Q, When
from django.utils.encoding import force_text

from wagtail.search.backends.base import (
    BaseSearchBackend, BaseSearchQueryCompiler, BaseSearchResults)
from wagtail.search.index import AutocompleteField, FilterField, RelatedFields, SearchField
from wagtail.search.query import And, Not, Or, PlainText

from whoosh import qparser
from whoosh.fields import ID as WHOOSH_ID
from whoosh.fields import NGRAMWORDS, TEXT, Schema
from whoosh.filedb.filestore import FileStorage
from whoosh.qparser import FuzzyTermPlugin, MultifieldParser, QueryParser
from whoosh.writing import AsyncWriter

from .utils import get_boost, get_descendant_models, get_indexed_parents, unidecode

PK = "pk"
DOCUMENT_FIELD = "text"


class ModelSchema:
    def __init__(self, model):
        self.model = model

    def build_schema(self):
        schema_fields = {
            PK: WHOOSH_ID(stored=True, unique=True),
            **dict(self._define_search_fields()),
        }
        return Schema(**schema_fields)

    def _define_search_fields(self):
        def _to_whoosh_field(field, field_name=None):
            if isinstance(field, AutocompleteField) or field.partial_match:
                whoosh_field = NGRAMWORDS(stored=True)
            else:
                # TODO other types of fields https://whoosh.readthedocs.io/en/latest/api/fields.html
                whoosh_field = TEXT(
                    phrase=not field.partial_match, stored=True, field_boost=get_boost(field.boost))

            if not field_name:
                field_name = field.field_name
            return field_name, whoosh_field

        for field in self.model.get_search_fields():
            if isinstance(field, FilterField):
                # TODO
                continue
            if isinstance(field, RelatedFields):
                for subfield in field.fields:
                    if isinstance(subfield, FilterField):
                        # TODO
                        continue
                    # Redefine field_name to avoid clashes
                    field_name = '{0}__{1}'.format(field.field_name, subfield.field_name)
                    yield _to_whoosh_field(subfield, field_name=field_name)
            else:
                yield _to_whoosh_field(field)


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
        # Adding done on initialisation
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
        if callable(value):
            return force_text(value())
        return force_text(value)

    def _get_document_fields(self, model, item):
        for field in model.get_search_fields():
            if isinstance(field, (SearchField, AutocompleteField)):
                if field.field_name == 'yo':
                    print(field.get_value(item))
                    print(type(field.get_value(item)))
                yield field.field_name, self.prepare_value(field.get_value(item))
            if isinstance(field, RelatedFields):
                value = field.get_value(item)
                if isinstance(value, (models.Manager, models.QuerySet)):
                    qs = value.all()
                    for sub_field in field.fields:
                        sub_values = qs.values_list(sub_field.field_name, flat=True)
                        yield '{0}__{1}'.format(field.field_name, sub_field.field_name), \
                            self.prepare_value(list(sub_values))

            if isinstance(field, FilterField):
                # TODO
                pass

    def _create_document(self, model, item):
        return {
            PK: force_text(item.pk),
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
        whoosh_id = ''

        try:
            index = self.backend.index.refresh()
            writer = index.writer()
            writer.delete_by_query(q=self.backend.parser.parse('%s:"%s"' % ('', '')))
            writer.commit()
        except Exception as e:
            raise e

    def __str__(self):
        return self.name


class WhooshSearchQueryCompiler(BaseSearchQueryCompiler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.field_names = list(self._get_fields_names())
        self.schema = ModelSchema(self.queryset.model).build_schema()

    def _get_fields_names(self):
        model = self.queryset.model
        for field in model.get_search_fields():
            if isinstance(field, RelatedFields):
                for sub_field in field.fields:
                    yield '{0}__{1}'.format(field.field_name, sub_field.field_name)
            else:
                yield field.field_name

    def _build_query_string(self, query=None):
        """
            Converts Wagtail query operators to their Whoosh equivalents
        """
        if not query:
            query = self.query

        if isinstance(query, str):
            return query
        if isinstance(query, PlainText):
            return force_text(query.query_string)
        if isinstance(query, Not):
            return 'NOT {}'.format(self._build_query_string(query.subquery))
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
        # Overridable
        return qparser.AndGroup

    def get_whoosh_query(self):
        group = self._get_group()
        parser = MultifieldParser(self.field_names, self.schema, group=group)
        parser.add_plugin(FuzzyTermPlugin())
        return parser.parse(self._build_query_string())

    def _process_lookup(self, field, lookup, value):
        # TODO whooshify
        return Q(**{field.get_attname(self.queryset.model) +
                    '__' + lookup: value})

    def _connect_filters(self, filters, connector, negated):
        # TODO
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
        pass

    def build_single_term_filter(self, term):
        term_query = models.Q()
        for field_name in self.fields_names:
            term_query |= models.Q(**{field_name + '__icontains': term})
        return term_query


class WhooshSearchResults(BaseSearchResults):
    def _do_search(self):
        # Probably better way to get the model
        model = self.query_compiler.queryset.model
        query = self.query_compiler.get_whoosh_query()
        index = self.backend.storage.open_index(indexname=model._meta.label)
        with index.searcher() as searcher:
            results = searcher.search(query, limit=None)
            score_map = dict([(r[PK], r.score) for r in results])

        descendants = get_descendant_models(model)
        for descendant in descendants:
            query_compiler = WhooshSearchQueryCompiler(
                descendant.objects.none(), self.query_compiler.query)
            query = query_compiler.get_whoosh_query()
            index = self.backend.storage.open_index(indexname=descendant._meta.label)
            with index.searcher() as searcher:
                results = searcher.search(query, limit=None)
                score_map.update(dict([(r[PK], r.score) for r in results]))

        self.backend.storage.close()

        django_ids = [r[0] for r in sorted(
            score_map.items(), key=lambda pk_score: pk_score[1], reverse=True)]
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

    def add_type(self, model):
        self.get_index_for_model(model).add_model(model)

    def refresh_index(self, optimize=True):
        # TODO
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
