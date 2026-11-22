import json

from django import template

register = template.Library()


@register.filter
def tojson(value):
    return json.dumps(value, ensure_ascii=False)


@register.filter
def seconds(ms):
    try:
        return f"{int(ms) / 1000:.1f}s"
    except (TypeError, ValueError):
        return ""
