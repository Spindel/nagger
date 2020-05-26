## [{{ milestone.title }}]({{ milestone.web_url }})

{{ milestone.description }}

{% for issue in issues recursive %}
{% set width = loop.depth0 * 2 %}
{{ "*" | indent(width=width, first=True) }} {{ issue | present_issue }}
{% if issue.related %}
{{ loop(issue.related) }}
{% endif %}
{% endfor %}
