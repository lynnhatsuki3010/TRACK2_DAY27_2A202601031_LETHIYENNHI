-- Singular business test: every date with at least one completed order in
-- stg_orders must show up in fct_daily_revenue. A GROUP BY/filter bug that
-- silently drops a date (e.g. a bad join condition) would otherwise pass
-- generic not_null/unique tests, since those only inspect rows that made it
-- into the mart, not rows that should have been there.
with completed_dates as (
    select distinct order_date
    from {{ ref('stg_orders') }}
    where status = 'completed'
)
select cd.order_date
from completed_dates cd
left join {{ ref('fct_daily_revenue') }} f
    on cd.order_date = f.order_date
where f.order_date is null
