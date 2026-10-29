-- Shot profile by distance zone, built from play-by-play field-goal attempts.
-- Distances are computed from ESPN court coordinates (feet, hoop near x=25, y=0), so treat
-- zone boundaries as approximate.
with shots as (
    select
        a.player_id,
        a.shot_result = 'Made' as made,
        case
            when a.is_three                                 then '3PT'
            when a.shot_distance_ft is null                 then 'Unknown'
            when a.shot_distance_ft < 4                     then 'Rim (0-3 ft)'
            when a.shot_distance_ft < 10                    then 'Short (4-9 ft)'
            when a.shot_distance_ft < 16                    then 'Mid (10-15 ft)'
            else                                                 'Long 2 (16+ ft)'
        end as zone,
        g.season
    from {{ ref('stg_nba__pbp_actions') }} a
    join {{ ref('stg_nba__games') }} g using (game_id)
    where a.is_field_goal and a.player_id is not null and a.player_id <> 0
)

select
    season,
    player_id,
    zone,
    count(*)                                                      as attempts,
    count(*) filter (where made)                                  as makes,
    round(avg(made::int), 3)                                      as fg_pct,
    round(count(*) / sum(count(*)) over (partition by season, player_id), 3) as share_of_attempts
from shots
group by season, player_id, zone
