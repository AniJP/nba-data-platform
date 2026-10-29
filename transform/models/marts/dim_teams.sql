-- Current attributes for every team seen in the data (latest game wins, so relocations/renames update).
with ranked as (
    select
        t.team_id, t.team_tricode, t.team_city, t.team_name, g.game_time_utc,
        row_number() over (partition by t.team_id order by g.game_time_utc desc) as rn
    from {{ ref('stg_nba__team_games') }} t
    join {{ ref('stg_nba__games') }} g using (game_id)
)

select
    team_id,
    team_tricode,
    team_city,
    team_name,
    team_city || ' ' || team_name as team_full_name
from ranked
where rn = 1
