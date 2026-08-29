-- The customer dimension can legitimately carry more than one row with
-- is_active = true per customer_id (SCD2 backfill bug, late-arriving
-- correction, etc). A plain join against active_customers fans out each
-- matching order row once per active version, silently inflating both
-- completed_order_rows and daily_revenue with no SQL error. We dedupe to the
-- single most-recent active version per customer before joining so the join
-- can never multiply rows. See unit test
-- duplicate_active_customer_does_not_inflate_revenue in unit_tests.yml.

with completed_orders as (
    select *
    from {{ ref('stg_orders') }}
    where status = 'completed'
),
active_customers as (
    select *
    from {{ ref('stg_customers') }}
    where is_active = true
),
active_customers_deduped as (
    select *
    from (
        select
            *,
            row_number() over (
                partition by customer_id
                order by valid_from desc
            ) as rn
        from active_customers
    ) ranked
    where rn = 1
)
select
    o.order_date,
    count(*) as completed_order_rows,
    sum(o.amount_usd) as daily_revenue
from completed_orders o
left join active_customers_deduped c
    on o.customer_id = c.customer_id
group by 1
order by 1
