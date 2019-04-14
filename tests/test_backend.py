# coding: utf-8
from __future__ import unicode_literals

from django.test import TestCase
from wagtail.search.tests.test_backends import BackendTests


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
