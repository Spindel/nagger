{% if changes %}
## {{ project }}

{% for change in changes %}
* {{ change.kind.name }}: {{ change.text }}
{% endfor %}

{% endif %}
