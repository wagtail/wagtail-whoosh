## Search backend for Wagtail CMS using Whoosh engine.

`pip install git+https://github.com/tjwalch/wagtail-whoosh`

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
