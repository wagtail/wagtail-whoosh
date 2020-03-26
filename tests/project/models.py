from django.db.models import Model, CharField
from wagtail.core.fields import RichTextField
from wagtail.search.index import SearchField, Indexed


class Article(Indexed, Model):
    title = CharField(max_length=200)
    body = RichTextField()

    search_fields = [
        SearchField('title', partial_match=True, boost=2),
        SearchField('body'),
    ]
