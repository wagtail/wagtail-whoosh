## Search backend for Wagtail CMS using Whoosh engine.

[![Build Status](https://travis-ci.org/AccordBox/wagtail-whoosh.svg?branch=master)](https://travis-ci.org/AccordBox/wagtail-whoosh)

## How to use

`pip install wagtail-whoosh`

After installing this package, add `wagtail_whoosh` to INSTALLED_APPS. And then config `WAGTAILSEARCH_BACKENDS`

```python
import os

ROOT_DIR = os.path.abspath(os.path.dirname(__name__))

WAGTAILSEARCH_BACKENDS = {
    'default': {
        'BACKEND': 'wagtail_whoosh.backend',
        'PATH': os.path.join(ROOT_DIR, 'search_index')
    },
}
```

Set `./manage.py update_index` as cron job, or setup hooks that index or delete items on publish / delete.

e.g.

```python
from wagtail.core import hooks
from wagtail.search.backends import get_search_backend

@hooks.register('after_create_page')
def index_page(request, page):
    backend = get_search_backend()
    backend.add(page)


@hooks.register('after_delete_page')
def deindex_page(request, page):
    backend = get_search_backend()
    backend.delete(page)

@hooks.register('after_edit_page')
def index_page(request, page):
    backend = get_search_backend()
    backend.delete(page)
    backend.add(page)
```



## Sponsor

[Tomas Walch](https://github.com/tjwalch)
