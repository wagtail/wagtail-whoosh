# coding: utf-8
from __future__ import unicode_literals

import copy

from django.conf import settings
from django.test import TestCase, override_settings

from wagtail.search.index import AutocompleteField
from wagtail.search.tests.test_backends import BackendTests
from wagtail.tests.search import models

from whoosh.analysis import LanguageAnalyzer
from whoosh.analysis.ngrams import NgramFilter

sv_search_setttings_language = copy.deepcopy(settings.WAGTAILSEARCH_BACKENDS)
sv_search_setttings_language['default']['LANGUAGE'] = 'sv'

analyzer_swedish = LanguageAnalyzer('sv')
sv_search_setttings_analyzer = copy.deepcopy(settings.WAGTAILSEARCH_BACKENDS)
sv_search_setttings_analyzer['default']['ANALYZER'] = analyzer_swedish

indexing_resources = copy.deepcopy(settings.WAGTAILSEARCH_BACKENDS)
indexing_resources['default']['MEMORY'] = 2048
indexing_resources['default']['PROCS'] = 2

ngram_length = copy.deepcopy(settings.WAGTAILSEARCH_BACKENDS)
ngram_length['default']['NGRAM_LENGTH'] = (3, 9)


class TestWhooshSearchBackend(BackendTests, TestCase):
    backend_path = 'wagtail_whoosh.backend'

    def test_facet(self):
        pass

    def test_facet_tags(self):
        pass

    def test_facet_with_nonexistent_field(self):
        pass

    def test_incomplete_plain_text(self):
        """
        Treat partial_match the same as AutocompleteField
        """
        pass

    def _setup_swe(self):
        self.swedish_author = models.Author.objects.create(
            name='Senaste nyheterna',
        )

    @override_settings(WAGTAILSEARCH_BACKENDS=sv_search_setttings_language)
    def test_language(self):
        # to rerun update_index because we have override_settings here
        self.setUp()
        self._setup_swe()
        results = self.backend.search("nyhet", models.Author)
        self.assertUnsortedListEqual([r.name for r in results], [
            self.swedish_author.name,
        ])

    @override_settings(WAGTAILSEARCH_BACKENDS=sv_search_setttings_analyzer)
    def test_analyzer(self):
        # to rerun update_index because we have override_settings here
        self.setUp()
        self._setup_swe()
        results = self.backend.search("nyhet", models.Author)
        self.assertUnsortedListEqual([r.name for r in results], [
            self.swedish_author.name,
        ])

    @override_settings(WAGTAILSEARCH_BACKENDS=indexing_resources)
    def test_resource_settings(self):
        # Test that the writer kwargs are changed via settings
        self.setUp()
        index = self.backend.get_index_for_model(models.Author)
        writer_args = index._writer_args()

        self.assertEquals({
            'limitmb': 2048,
            'procs': 2,
        }, writer_args)

    @override_settings(WAGTAILSEARCH_BACKENDS=ngram_length)
    def test_ngram_length_settings(self):
        self.setUp()
        test_field = AutocompleteField('Test')
        whoosh_field = self.backend._to_whoosh_field(test_field)[1]
        # Find the NgramFilter from the Composite Analyzer
        filter = next(analyzer for analyzer in whoosh_field.analyzer if isinstance(analyzer, NgramFilter))

        self.assertEquals(3, filter.min)
        self.assertEquals(9, filter.max)
