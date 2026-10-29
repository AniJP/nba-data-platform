-- Every game has exactly two team rows and exactly one winner.
select game_id, count(*) as team_rows, count(*) filter (where won) as winners
from {{ ref('fct_team_games') }}
group by game_id
having count(*) <> 2 or count(*) filter (where won) <> 1
