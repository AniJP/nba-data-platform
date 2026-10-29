-- Shots made can never exceed shots attempted.
select game_id, player_id, fgm, fga, fg3m, fg3a, ftm, fta
from {{ ref('stg_nba__player_games') }}
where fgm > fga or fg3m > fg3a or ftm > fta or fg3m > fgm
