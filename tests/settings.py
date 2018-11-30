SECRET_KEY = 'this is required'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'db.sqlite3',
    }
}

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',

    'modelcluster',
    'taggit',

    'wagtail.core',
    'wagtail.search',
    'wagtail.tests.search',

    'wagtail_whoosh',
]

WAGTAILSEARCH_BACKENDS = {
    'default': {
        'BACKEND': 'wagtail_whoosh.backend',
        'PATH': 'test_search_index'
    },
}


# Don't run migrations, just create tables.

class DisableMigrations(object):
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = DisableMigrations()
