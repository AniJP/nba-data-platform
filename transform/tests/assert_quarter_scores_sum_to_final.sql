-- In regulation games, the four quarter scores add up to the final score.
select t.game_id, t.team_id
from {{ ref('stg_nba__team_games') }} t
join {{ ref('stg_nba__games') }} g using (game_id)
where not g.went_to_overtime
  and t.q1_points + t.q2_points + t.q3_points + t.q4_points <> t.points
