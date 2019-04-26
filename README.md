## Search backend for Wagtail CMS using Whoosh engine.

[![Build Status](https://travis-ci.org/wagtail/wagtail-whoosh.svg?branch=master)](https://travis-ci.org/wagtail/wagtail-whoosh)

## How to use

* `0.1.x` work with `wagtail>=2.0,<2.2`
* `0.2.x` work with `wagtail>=2.2`

`pip install wagtail-whoosh`

After installing this package, add `wagtail_whoosh` to INSTALLED_APPS. And then config `WAGTAILSEARCH_BACKENDS`

```python
WAGTAILSEARCH_BACKENDS = {
    'default': {
        'BACKEND': 'wagtail_whoosh.backend',
        'PATH': str(ROOT_DIR('search_index')),
        'ANALYZER': 'path.to.my.analyzer',  # Optional
    },
}
```

Set `./manage.py update_index` as cron job

## Features

### Score support

```
results = Page1.objects.search(query).annotate_score("_score").results()
result += Page2.objects.search(query).annotate_score("_score").results()
return sorted(results, key=lambda r: r._score)
```

### Language and custom Analyzer support

By default `wagtail-whoosh` will use the Django setting `LANGUAGE_CODE` to
 automatically setup page text analysis according to your language. If this
 isn't desirable, or if Whoosh doesn't support your language out-of-the-box, 
 or for whatever reason you might have, it is possible to specify a custom
 analyzer by adding an `ANALYZER` to the seach backend config. This value
 should be either a dotted string to an analyzer instance or an analyzer
 Python object. See [Whoosh documentation](https://whoosh.readthedocs.io/en/latest/analysis.html)
 for more about analyzers.

## NOT-Supported features

1. `boosting` is not supported.
2. `facet` is not supported.
3. `autocomplete` is not supported.

## Sponsor

[Tomas Walch](https://github.com/tjwalch)
