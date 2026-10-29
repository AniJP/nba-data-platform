-- A team's final score must equal the sum of its players' points.
select t.game_id, t.team_id, t.points, sum(p.points) as player_points
from {{ ref('stg_nba__team_games') }} t
join {{ ref('stg_nba__player_games') }} p using (game_id, team_id)
group by t.game_id, t.team_id, t.points
having t.points <> sum(p.points)
