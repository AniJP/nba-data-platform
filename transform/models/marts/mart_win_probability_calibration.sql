-- How well calibrated are win-probability models? Compares ESPN's published probabilities with
-- the naive baseline used by the live streaming pipeline (nba_pipeline.live), against how each
-- game actually ended. A well-calibrated model's 70% predictions come true about 70% of the time.
with plays as (
    select
        a.game_id,
        a.seconds_remaining_in_game,
        a.score_home - a.score_away                       as home_margin,
        w.espn_home_win_prob,
        (g.home_score > g.away_score)::int                as home_won
    from {{ ref('stg_nba__pbp_actions') }} a
    join {{ ref('stg_nba__win_probability') }} w using (game_id, action_id)
    join {{ ref('stg_nba__games') }} g using (game_id)
    where a.seconds_remaining_in_game > 0
),

scored as (
    select game_id, home_won, 'espn' as model, espn_home_win_prob as p from plays
    union all
    select
        game_id, home_won, 'naive_baseline' as model,
        -- same formula as nba_pipeline.live.naive_home_win_probability
        1 / (1 + exp(-(home_margin + 2.0 * (seconds_remaining_in_game / 60) / 48)
                     / (0.9 * sqrt(seconds_remaining_in_game / 60 + 1)))) as p
    from plays
)

select
    model,
    least(floor(p * 10) / 10, 0.9)                                        as prob_bucket,
    count(*)                                                             as plays,
    count(distinct game_id)                                              as games,
    round(avg(p), 3)                                                     as avg_predicted,
    round(avg(home_won), 3)                                              as actual_home_win_rate,
    -- Brier score over all of the model's predictions (lower is better)
    round(sum(sum(power(p - home_won, 2))) over (partition by model)
          / sum(count(*)) over (partition by model), 4)                  as model_brier_score
from scored
group by model, least(floor(p * 10) / 10, 0.9)
