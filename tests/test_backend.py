# coding: utf-8
from __future__ import unicode_literals

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from wagtail.search.tests.test_backends import BackendTests
from wagtail.tests.search import models


search_setttings = settings.WAGTAILSEARCH_BACKENDS
search_setttings['default']['ANALYZER'] = 'tests.analyzer.analyzer_swedish'


class TestWhooshSearchBackend(BackendTests, TestCase):
    backend_path = 'wagtail_whoosh.backend'

    def setup_swe(self):
        self.swedish_book = models.Book.objects.create(
            title='Senaste nyheterna',
            publication_date=timezone.now(),
            number_of_pages=99,
        )

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

    @override_settings(LANGUAGE_CODE='sv-se')
    def test_default_analyzer_language(self):
        self.setup_swe()
        results = self.backend.search("nyhet", models.Book)
        self.assertUnsortedListEqual([r.title for r in results], [
            self.swedish_book.title,
        ])

    @override_settings(WAGTAILSEARCH_BACKENDS=search_setttings)
    def test_analyzer(self):
        self.setup_swe()
        results = self.backend.search("nyhet", models.Book)
        self.assertUnsortedListEqual([r.title for r in results], [
            self.swedish_book.title,
        ])
