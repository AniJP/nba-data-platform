{# ESPN box scores store each player's stats as an array aligned with a `keys` array, e.g.
   keys  = ['minutes', 'points', 'fieldGoalsMade-fieldGoalsAttempted', ...]
   stats = ['31',      '24',     '11-18', ...]
   Look values up by key name rather than position, so a reordering upstream can't shift columns. #}

{% macro espn_stat(stats, keys, key) -%}
    {{ stats }}[list_position({{ keys }}, '{{ key }}')]
{%- endmacro %}

{% macro espn_int(stats, keys, key) -%}
    try_cast(replace({{ espn_stat(stats, keys, key) }}, '+', '') as integer)
{%- endmacro %}

{# 'made-attempted' pairs, e.g. '11-18' #}
{% macro espn_made(stats, keys, key) -%}
    try_cast(split_part({{ espn_stat(stats, keys, key) }}, '-', 1) as integer)
{%- endmacro %}

{% macro espn_attempted(stats, keys, key) -%}
    try_cast(split_part({{ espn_stat(stats, keys, key) }}, '-', 2) as integer)
{%- endmacro %}

{# ESPN game clock: '5:32' (minutes:seconds) or '44.6' (under a minute) -> seconds #}
{% macro espn_clock_seconds(col) -%}
    case
        when {{ col }} like '%:%'
            then try_cast(split_part({{ col }}, ':', 1) as double) * 60
                 + try_cast(split_part({{ col }}, ':', 2) as double)
        else try_cast({{ col }} as double)
    end
{%- endmacro %}

{# ESPN timestamps look like '2026-10-28T23:00Z'. DuckDB's JSON reader usually auto-detects them
   as TIMESTAMPTZ already; if a column arrives as text instead, normalise it before casting.
   Works for either input type. #}
{% macro espn_timestamp(col) -%}
    coalesce(
        try_cast({{ col }} as timestamptz),
        try_cast(replace(cast({{ col }} as varchar), 'Z', ':00+00:00') as timestamptz)
    )
{%- endmacro %}

{# Play wallclock: '2026-10-28T23:12:43Z' (usually auto-detected as TIMESTAMPTZ) #}
{% macro espn_timestamp_or_null(col) -%}
    coalesce(
        try_cast({{ col }} as timestamptz),
        try_cast(replace(cast({{ col }} as varchar), 'Z', '+00:00') as timestamptz)
    )
{%- endmacro %}
