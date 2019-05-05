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

    def test_incomplete_plain_text(self):
        """
        Treat partial_match the same as AutocompleteField
        """
        pass
