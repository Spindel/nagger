title: Release {{ milestone_name }}
date: {{ date }}
Category: Releases
author: {{ author }}

{{ description }}

{% for project in projects %}
{% if project.external %}
## {{ project.name }}

{% for kind in Kind %}
{% for change in project.external | selectattr("kind", "equalto", kind.value) %}
{% if loop.first %}
{{ kind | present_kind }}:

{% endif %}
* {{ change.text }}
{% if loop.last %}

{% endif %}
{% endfor %}
{% endfor %}

{% endif %}
{% endfor %}
