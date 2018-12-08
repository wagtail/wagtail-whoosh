# coding: utf-8
from __future__ import unicode_literals

from django.test import TestCase
from wagtail.search.tests.test_backends import BackendTests


class TestWhooshSearchBackend(BackendTests, TestCase):
    backend_path = 'wagtail_whoosh.backend'
