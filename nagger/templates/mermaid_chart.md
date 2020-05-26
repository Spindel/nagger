```mermaid
graph LR;
classDef closed fill:#efe,stroke-width:4px;font-style:italic

{% for issue in issues recursive %}
{{ issue.id }}["{{ issue.title }} {{ issue.link }}"];
  {% if issue.closed %}
class {{ issue.id }} {{ issue.state }};
  {% endif -%}
  {% if issue.parent %}
{{ issue.parent.id }} --- {{ issue.id }};
  {% endif -%}
  {% if issue.related -%}
      {{ loop(issue.related) }}
  {% endif -%}
{% endfor -%}
```
