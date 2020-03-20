"""
This settings is for benchmark testing

When you do this test, you need a Postgres db instance
you might need to change the DATABASES
"""

DEBUG = False

SECRET_KEY = 'this is required'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'wagtail_search_benchmark',
    }
}

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.sites',
    'django.contrib.sessions',
    'django.contrib.messages',

    'wagtail.contrib.forms',
    'wagtail.contrib.redirects',
    'wagtail.embeds',
    'wagtail.sites',
    'wagtail.users',
    'wagtail.snippets',
    'wagtail.documents',
    'wagtail.images',
    'wagtail.search',
    'wagtail.admin',
    'wagtail.core',

    'modelcluster',
    'taggit',

    # All test code in this Django app
    'tests.project',

    'wagtail.contrib.postgres_search',
    'wagtail_whoosh',
]

WAGTAILSEARCH_BACKENDS = {
    'default': {
        'BACKEND': 'wagtail_whoosh.backend',
        'PATH': 'test_search_index',
        'PROCS': 2,
        'MEMORY': 1024,
    },
    # 'db': {
    #     'BACKEND': 'wagtail.search.backends.db',
    # },
    # 'postgres': {
    #     'BACKEND': 'wagtail.contrib.postgres_search.backend',
    # },
}
