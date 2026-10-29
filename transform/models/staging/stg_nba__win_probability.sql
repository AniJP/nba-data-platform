-- ESPN's published home-win probability after each play.
with wp as (
    select
        cast(payload.header.id as varchar) as game_id,
        unnest(payload.winprobability)    as w
    from {{ ref('stg_nba__summary_payloads') }}
)

select
    game_id,
    cast(w.playId as varchar)                    as action_id,
    cast(w.homeWinPercentage as double)          as espn_home_win_prob
from wp
