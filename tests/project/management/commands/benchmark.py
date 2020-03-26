from argparse import ArgumentTypeError, FileType
from contextlib import contextmanager
from io import StringIO
from random import seed, randint, choices, choice
from time import time

from django.conf import settings
from django.core.management import BaseCommand, call_command
from django.db import connection
from django.db.models.signals import post_save, post_delete
from wagtail.contrib.postgres_search.models import IndexEntry
from wagtail.search.backends import get_search_backend
from wagtail.search.backends.db import DatabaseSearchBackend
from wagtail.search.signal_handlers import (
    post_save_signal_handler, post_delete_signal_handler)

from ...models import Article


def format_time(s):
    for unit in ('s', 'ms', 'μs'):
        if s > 1:
            return '%.2f %s' % (s, unit)
        s *= 1000
    return '%.2f ns' % s


def strictly_positive_int(value):
    type_error = ArgumentTypeError('%s must be a strictly positive integer.'
                                   % value)
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise type_error
    if value <= 0:
        raise type_error
    return value


def time_it(func, title='', backend_name=''):
    n = 3
    start = time()
    while True:
        for i in range(n):
            func()
        elapsed_time = time() - start
        if elapsed_time > 1:
            break
        n *= 10
    print('%-30s %-15s %9s %15s'
          % (title, backend_name,
             format_time(elapsed_time / n), '%s runs' % n))


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-d', '--dictionary', type=FileType('r'),
                            default='/usr/share/dict/words',
                            help='Path to a dictionary file '
                                 'containing a word per line.')
        parser.add_argument('-s', '--start',
                            type=strictly_positive_int, default=1)
        parser.add_argument('-m', '--step-magnitude',
                            type=strictly_positive_int, default=5)
        parser.add_argument('--seed', default='random seed')
        parser.add_argument('-l', '--limit', type=strictly_positive_int,
                            default=1000000)

    def create_article_bulk(self, dictionary, bulk_size):
        Article.objects.bulk_create([Article(
                title=' '.join(choices(dictionary, k=randint(3, 10))),
                body=' '.join(choices(dictionary, k=randint(50, 300))))
            for i in range(bulk_size)])

    @property
    def backends(self):
        for backend_name in settings.WAGTAILSEARCH_BACKENDS:
            yield backend_name, get_search_backend(backend=backend_name)

    def update_index(self, backend_name):
        call_command('update_index', backend_name=backend_name,
                     stdout=StringIO())

    def unsorted_autocomplete(self, backend):
        list(backend.autocomplete(self.partial_word, Article,
                                  order_by_relevance=False)[:10])

    def sorted_autocomplete(self, backend):
        list(backend.autocomplete(self.partial_word, Article,
                                  order_by_relevance=True)[:10])

    def unsorted_search(self, backend):
        list(backend.search(self.word, Article, order_by_relevance=False)[:10])

    def sorted_search(self, backend):
        list(backend.search(self.word, Article, order_by_relevance=True)[:10])

    def step(self, dictionary, bulk_size):
        print('Adding %s articles…' % bulk_size, end='\r')
        self.create_article_bulk(dictionary, bulk_size)
        print('Testing with %s articles:' % Article.objects.count())
        for backend_name, backend in self.backends:
            time_it(lambda: self.update_index(backend_name),
                    title='Update index', backend_name=backend_name)
        print('Optimizing the database…', end='\r')
        with connection.cursor() as cursor:
            for model in (Article, IndexEntry):
                table = model._meta.db_table
                cursor.execute('VACUUM ANALYSE "%s";' % table)
                cursor.execute('REINDEX TABLE "%s";' % table)
        for backend_name, backend in self.backends:
            if not isinstance(backend, DatabaseSearchBackend):
                time_it(lambda: self.unsorted_autocomplete(backend),
                        title='Unsorted autocomplete',
                        backend_name=backend_name)
                time_it(lambda: self.sorted_autocomplete(backend),
                        title='Sorted autocomplete', backend_name=backend_name)
            time_it(lambda: self.unsorted_search(backend),
                    title='Unsorted search', backend_name=backend_name)
            time_it(lambda: self.sorted_search(backend),
                    title='Sorted search', backend_name=backend_name)
        print()

    def clear(self):
        Article.objects.all().delete()
        for _, backend in self.backends:
            backend.reset_index()

    @contextmanager
    def set_up(self):
        post_delete.disconnect(post_delete_signal_handler, sender=Article)
        post_save.disconnect(post_save_signal_handler, sender=Article)
        self.clear()
        try:
            yield
        finally:
            # self.clear()
            post_save.connect(post_save_signal_handler, sender=Article)
            post_delete.connect(post_delete_signal_handler, sender=Article)

    def handle(self, *args, **options):
        dictionary = list(options['dictionary'])
        while True:
            self.word = choice(dictionary)
            if len(self.word) >= 6:
                break
        self.partial_word = self.word[:3]
        start = options['start']
        step_magnitude = options['step_magnitude']
        limit = options['limit']
        seed(options['seed'])
        with self.set_up():
            n = start
            while n <= limit:
                self.step(dictionary, n - Article.objects.count())
                n *= step_magnitude
