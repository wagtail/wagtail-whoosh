SECRET_KEY = 'this is required'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'db.sqlite3',
    }
}

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'wagtail_search_benchmark',
#     }
# }

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

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

    'wagtail.tests.search',

    'tests.project',

    # you can not make it work with sqlite, we only use it when do benchmark test
    # 'wagtail.contrib.postgres_search',

    'wagtail_whoosh',
]

WAGTAILSEARCH_BACKENDS = {
    'default': {
        'BACKEND': 'wagtail_whoosh.backend',
        'PATH': 'test_search_index'
    },
    # 'db': {
    #     'BACKEND': 'wagtail.search.backends.db',
    # },
    # 'postgres': {
    #     'BACKEND': 'wagtail.contrib.postgres_search.backend',
    # },
}
