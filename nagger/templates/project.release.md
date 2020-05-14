Release: {{ tag_name }}
Milestone: {{ milestone.web_url }}

{% if changes %}
	{% for kind in Kind %}
		{% for change in changes | selectattr("kind", "equalto", kind.value) %}
			{% if loop.first %}

## {{ kind | present_kind | title }}:

			{% endif %}
			{% if change.slug %}
* [{{ change.text}}]({{change.slug}})
			{% else %}
* {{ line.text }}
			{% endif %}
			{% if loop.last %}
			{# Last line, add a whitespace #}

			{% endif %}
		{% endfor %}
	{% endfor %}
{% else %}
No major changes
{% endif %}
