{% if changes %}
## {{ project | title }}

{% for kind in Kind %}
{% for change in changes | selectattr("kind", "equalto", kind.value) %}
{% if loop.first %}
{{ kind | present_kind }}:
{% endif %}
* {{ change.text }}
{% endfor %}
{% if loop.last %}

{% endif %}
{% endfor %}

{% endif %}
