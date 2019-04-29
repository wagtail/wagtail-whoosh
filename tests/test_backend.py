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

    def test_autocomplete(self):
        pass

    def test_facet(self):
        pass

    def test_facet_tags(self):
        pass

    def test_facet_with_nonexistent_field(self):
        pass

    def test_boost(self):
        pass

    def _setup_swe(self):
        self.swedish_book = models.Book.objects.create(
            title='Senaste nyheterna',
            publication_date=timezone.now(),
            number_of_pages=99,
        )

    @override_settings(WAGTAILSEARCH_BACKENDS=sv_search_setttings_language)
    def test_language(self):
        self._setup_swe()
        results = self.backend.search("nyhet", models.Book)
        self.assertUnsortedListEqual([r.title for r in results], [
            self.swedish_book.title,
        ])

    @override_settings(WAGTAILSEARCH_BACKENDS=sv_search_setttings_analyzer)
    def test_analyzer(self):
        self._setup_swe()
        results = self.backend.search("nyhet", models.Book)
        self.assertUnsortedListEqual([r.title for r in results], [
            self.swedish_book.title,
        ])
