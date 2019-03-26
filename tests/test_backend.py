# coding: utf-8
from __future__ import unicode_literals

from django.test import TestCase

from wagtail.search.query import Boost, Not, PlainText
from wagtail.search.tests.test_backends import BackendTests
from wagtail.tests.search import models


class TestWhooshSearchBackend(BackendTests, TestCase):
    backend_path = 'wagtail_whoosh.backend'

    # Facet searching not supported yet
    def test_facet(self):
        pass

    def test_facet_tags(self):
        pass

    def test_facet_with_nonexistent_field(self):
        pass

    def test_boost(self):
        # Whoosh matches python on ProgammingLanguage.get_programming_language_display, so this test is modified

        results = self.backend.search(PlainText('JavaScript Definitive') | Boost(PlainText('Learning Python'), 2.0), models.Book.objects.all())

        # Both python and JavaScript should be returned with Python at the top
        self.assertEqual([r.title for r in results][:2], [
            "Learning Python",
            "JavaScript: The Definitive Guide",
        ])

        results = self.backend.search(PlainText('JavaScript Definitive') | Boost(PlainText('Learning Python'), 0.8), models.Book.objects.all())

        # Now they should be swapped
        self.assertEqual([r.title for r in results][:2], [
            "JavaScript: The Definitive Guide",
            "Learning Python",
        ])

    def test_not(self):
        # Overridden, the default operator for Whoosh is Or, so the last test needs the operator sent through
        all_other_titles = {
            'A Clash of Kings',
            'A Game of Thrones',
            'A Storm of Swords',
            'Foundation',
            'Learning Python',
            'The Hobbit',
            'The Two Towers',
            'The Fellowship of the Ring',
            'The Return of the King',
            'The Rust Programming Language',
            'Two Scoops of Django 1.11',
        }
        results = self.backend.search(Not(PlainText('javascript')),
                                      models.Book.objects.all())
        self.assertSetEqual({r.title for r in results}, all_other_titles)

        results = self.backend.search(~PlainText('javascript'),
                                      models.Book.objects.all())
        self.assertSetEqual({r.title for r in results}, all_other_titles)

        # Tests multiple words
        results = self.backend.search(~PlainText('javascript the'),
                                      models.Book.objects.all(), operator='and')

        self.assertSetEqual({r.title for r in results}, all_other_titles)
