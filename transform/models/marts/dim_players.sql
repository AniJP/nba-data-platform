-- One row per player: latest name/team plus career-in-dataset span.
with appearances as (
    select p.*, g.game_date_et, g.game_time_utc
    from {{ ref('stg_nba__player_games') }} p
    join {{ ref('stg_nba__games') }} g using (game_id)
),

latest as (
    select *, row_number() over (partition by player_id order by game_time_utc desc) as rn
    from appearances
)

select
    l.player_id,
    l.player_name,
    l.first_name,
    l.last_name,
    l.position          as latest_position,
    l.team_id           as current_team_id,
    agg.first_game_date,
    agg.last_game_date,
    agg.games_played
from latest l
join (
    select
        player_id,
        min(game_date_et)                       as first_game_date,
        max(game_date_et)                       as last_game_date,
        count(*) filter (where played)          as games_played
    from appearances
    group by player_id
) agg using (player_id)
where l.rn = 1
