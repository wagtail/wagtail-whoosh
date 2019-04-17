# coding: utf-8
from __future__ import unicode_literals

from django.test import TestCase

from wagtail.search.query import Boost, PlainText
from wagtail.search.tests.test_backends import BackendTests
from wagtail.tests.search import models


class TestWhooshSearchBackend(BackendTests, TestCase):
    backend_path = 'wagtail_whoosh.backend'

    def test_facet(self):
        pass

    def test_facet_tags(self):
        pass

    def test_facet_with_nonexistent_field(self):
        pass

    def test_boost(self):
        # Whoosh results differ from the standard test, we only care about ordering though
        results = self.backend.search(PlainText('JavaScript Definitive') | Boost(PlainText('Learning Python'), 2.0), models.Book.objects.all())

        result_titles = [r.title for r in results]
        # Both python and JavaScript should be returned with Python at the top
        self.assertLess(result_titles.index('Learning Python'), result_titles.index("JavaScript: The Definitive Guide"))

        results = self.backend.search(PlainText('JavaScript Definitive') | Boost(PlainText('Learning Python'), 0.5), models.Book.objects.all())
        # Now they should be swapped
        result_titles = [r.title for r in results]
        self.assertGreater(result_titles.index('Learning Python'), result_titles.index("JavaScript: The Definitive Guide"))
