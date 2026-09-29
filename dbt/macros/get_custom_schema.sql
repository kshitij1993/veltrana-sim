{#
    dbt's default generate_schema_name composes <target_schema>_<custom_schema>
    (e.g. "silver_gold") whenever a model sets a custom +schema. This project
    wants exactly the custom schema name when one is set (silver.* by default
    via the profile's target schema, gold.* for anything under models/gold/
    with +schema: gold) - so override it to ignore the target-schema prefix.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
