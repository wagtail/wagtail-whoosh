# coding: utf-8
from __future__ import unicode_literals

import copy

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from wagtail.search.tests.test_backends import BackendTests
from wagtail.tests.search import models

from whoosh.analysis import LanguageAnalyzer

sv_search_setttings_language = copy.deepcopy(settings.WAGTAILSEARCH_BACKENDS)
sv_search_setttings_language['default']['LANGUAGE'] = 'sv'

analyzer_swedish = LanguageAnalyzer('sv')
sv_search_setttings_analyzer = copy.deepcopy(settings.WAGTAILSEARCH_BACKENDS)
sv_search_setttings_analyzer['default']['ANALYZER'] = analyzer_swedish


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
