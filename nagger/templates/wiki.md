## Release notes [{{  milestone.title }}]({{ milestone.web_url }})

Period: {{milestone.start_date}} - {{milestone.due_date}}

{{ milestone.description }}

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
