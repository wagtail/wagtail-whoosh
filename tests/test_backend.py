# coding: utf-8
from __future__ import unicode_literals

from django.core.management import call_command
from django.test import TestCase
from django.utils.six import StringIO
# from wagtail.tests.search.models import SearchTest
from wagtail.search.tests.test_backends import BackendTests
from wagtail.tests.search import models
from wagtail.search.query import MATCH_ALL, And, Boost, Filter, Not, Or, PlainText, Term


class TestWhooshSearchBackend(BackendTests, TestCase):
    backend_path = 'wagtail_whoosh.backend'
