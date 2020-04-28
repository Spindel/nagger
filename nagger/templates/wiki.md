## Release notes {{ milestone_name }}

{% for project in projects %}
## {{ project.name }}

{% for change in project.changes %}
* [{{  change.text }}]({{ change.web_url }})  {{ change.labels | labels2md }} 
{% if loop.last %}
{# Whitespace at the end to make list formatting work #}

{% endif %}
{% else %}
No changes

{% endfor %}
{% endfor %}
