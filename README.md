## Search backend for Wagtail CMS using Whoosh engine.

[![Build Status](https://travis-ci.org/wagtail/wagtail-whoosh.svg?branch=master)](https://travis-ci.org/wagtail/wagtail-whoosh)

## How to use

* `0.1.x` work with `wagtail>=2.0,<2.2`
* `0.2.x` work with `wagtail>=2.2`

`pip install wagtail-whoosh`

After installing this package, add `wagtail_whoosh` to INSTALLED_APPS. And then config `WAGTAILSEARCH_BACKENDS`

```python
import os

ROOT_DIR = os.path.abspath(os.path.dirname(__name__))

WAGTAILSEARCH_BACKENDS = {
    'default': {
        'BACKEND': 'wagtail_whoosh.backend',
        'PATH': os.path.join(ROOT_DIR, 'search_index')
        'LANGUAGE': 'fr',
    },
}
```

Set `./manage.py update_index` as cron job

## Features

### Support autocomplete

If you want to search `hello world`, you might need to use `hello` in previous versions. Now you can use `hel` and the backend would return the result.

```
# you need to define the search field in this way
index.SearchField('title', partial_match=True)

# or this way
index.AutocompleteField('title')
```

### Specifying the fields to search

```
# Search just the title field
>>> EventPage.objects.search("Event", fields=["title"])
[<EventPage: Event 1>, <EventPage: Event 2>]
```

### Score support

```
results = Page1.objects.search(query).annotate_score("_score").results()
result += Page2.objects.search(query).annotate_score("_score").results()
return sorted(results, key=lambda r: r._score)
```

### Language support

Whoosh includes pure-Python implementations of the Snowball stemmers and stop word lists for various languages adapted from NLTK.

So you can use the built-in language support by setting like `'LANGUAGE': 'fr'`, the language support list is below.

`('ar', 'da', 'nl', 'en', 'fi', 'fr', 'de', 'hu', 'it', 'no', 'pt', 'ro', 'ru', 'es', 'sv', 'tr')`

If you want more control or want to do customization, you can use `ANALYZER` instead of `LANGUAGE` here.

> An analyzer is a function or callable class (a class with a __call__ method) that takes a unicode string and returns a generator of tokens

You can set `ANALYZER` using an object reference or dotted module path.

**NOTE: If ANALYZER is set, your LANGUAGE would be ignored**

```
from whoosh.analysis import LanguageAnalyzer
analyzer_swedish = LanguageAnalyzer('sv')

WAGTAILSEARCH_BACKENDS = {
    'default': {
        'BACKEND': 'wagtail_whoosh.backend',
        'PATH': str(ROOT_DIR('search_index')),
        'ANALYZER': analyzer_swedish,
    },
}
```

## NOT-Supported features

1. `facet` is not supported.

