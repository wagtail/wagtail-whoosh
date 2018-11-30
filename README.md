## Search backend for Wagtail CMS using Whoosh engine.

[![Build Status](https://travis-ci.org/michael-yin/wagtail-whoosh.svg?branch=master)](https://travis-ci.org/michael-yin/wagtail-whoosh)

## How to use

`pip install wagtail-whoosh`

After installing this package, add `wagtail_whoosh` to INSTALLED_APPS. And then config `WAGTAILSEARCH_BACKENDS`

```python
WAGTAILSEARCH_BACKENDS = {
    'default': {
        'BACKEND': 'wagtail_whoosh.backend',
        'PATH': str(ROOT_DIR('search_index'))
    },
}
```

Set `./manage.py update_index` as cron job

