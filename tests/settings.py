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
