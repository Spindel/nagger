{% if changes %}
## {{ project | title }}

{% for change in changes %}
* [{{  change.text }}]({{ change.web_url }})  {{ change.labels | labels2md }} 
{% endfor %}

{% endif %}
