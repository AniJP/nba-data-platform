-- Play-by-play is only landed together with its box score; orphans indicate a loading bug.
select distinct a.game_id
from {{ ref('stg_nba__pbp_actions') }} a
left join {{ ref('stg_nba__games') }} g using (game_id)
where g.game_id is null
