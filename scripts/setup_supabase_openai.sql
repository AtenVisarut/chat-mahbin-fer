-- ============================================================================
-- 1. Enable Extensions
-- ============================================================================
create extension if not exists vector;

-- ============================================================================
-- 2. Products Table (OpenAI Embeddings - 1536 dimensions)
-- ============================================================================
create table if not exists products (
  id bigserial primary key,
  product_name text,
  active_ingredient text,
  target_pest text,
  applicable_crops text,
  how_to_use text,
  usage_period text,
  usage_rate text,
  embedding vector(1536) -- OpenAI embeddings are 1536 dimensions
);

-- Create index for faster search
create index if not exists idx_products_embedding on products 
using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

-- Function to search for products
create or replace function match_products (
  query_embedding vector(1536),
  match_threshold float,
  match_count int
)
returns table (
  id bigint,
  product_name text,
  active_ingredient text,
  target_pest text,
  applicable_crops text,
  how_to_use text,
  usage_period text,
  usage_rate text,
  link_product text,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    products.id,
    products.product_name,
    products.active_ingredient,
    products.target_pest,
    products.applicable_crops,
    products.how_to_use,
    products.usage_period,
    products.usage_rate,
    products.link_product,
    1 - (products.embedding <=> query_embedding) as similarity
  from products
  where 1 - (products.embedding <=> query_embedding) > match_threshold
  order by products.embedding <=> query_embedding
  limit match_count;
end;
$$;

-- ============================================================================
-- 3. Users Table (For Registration)
-- ============================================================================
create table if not exists users (
    id bigserial primary key,
    line_user_id text unique not null,
    display_name text,
    phone_number text,
    province text,
    crops_grown text[], -- Array of strings
    registration_completed boolean default false,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index if not exists idx_users_line_id on users(line_user_id);

-- ============================================================================
-- 4. Cache Table (For State Management)
-- ============================================================================
create table if not exists cache (
  key text primary key,
  value jsonb not null,
  expires_at timestamptz not null
);

-- ============================================================================
-- 5. Conversation Memory Table
-- ============================================================================
create table if not exists conversation_memory (
    id bigserial primary key,
    user_id text not null,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    created_at timestamptz default now(),
    metadata jsonb default '{}'::jsonb
);

create index if not exists idx_conversation_memory_user_id on conversation_memory(user_id);
create index if not exists idx_conversation_memory_created_at on conversation_memory(created_at desc);

-- ============================================================================
-- 6. Analytics Tables
-- ============================================================================
create table if not exists analytics_events (
    id bigserial primary key,
    user_id text not null,
    event_type text not null, -- 'image_analysis', 'question', 'product_recommendation', 'error'
    
    -- Image analysis fields
    disease_name text,
    pest_type text,
    confidence text,
    severity text,
    
    -- Question fields
    question_text text,
    intent text,
    
    -- Product recommendation fields
    product_name text,
    
    -- Error fields
    error_type text,
    error_message text,
    stack_trace text,
    
    -- Performance metrics
    response_time_ms float,
    
    -- Timestamp
    created_at timestamptz default now()
);

create index if not exists idx_analytics_events_user_id on analytics_events(user_id);
create index if not exists idx_analytics_events_event_type on analytics_events(event_type);
create index if not exists idx_analytics_events_created_at on analytics_events(created_at);

-- Analytics Alerts
create table if not exists analytics_alerts (
    id bigserial primary key,
    alert_type text not null,
    message text not null,
    severity text not null,
    resolved boolean default false,
    resolved_at timestamptz,
    created_at timestamptz default now()
);

-- ============================================================================
-- 7. Analytics Views (For Dashboard)
-- ============================================================================

-- View: Daily Statistics
create or replace view analytics_daily_stats as
select 
    date(created_at) as date,
    count(distinct user_id) as unique_users,
    count(*) filter (where event_type = 'image_analysis') as images_analyzed,
    count(*) filter (where event_type = 'question') as questions_asked,
    count(*) filter (where event_type = 'error') as errors,
    avg(response_time_ms) filter (where response_time_ms is not null) as avg_response_time_ms
from analytics_events
group by date(created_at)
order by date desc;

-- View: Top Diseases (Last 7 Days)
create or replace view analytics_top_diseases as
select 
    disease_name,
    count(*) as count
from analytics_events
where event_type = 'image_analysis'
    and disease_name is not null
    and created_at >= now() - interval '7 days'
group by disease_name
order by count desc
limit 20;

-- View: Top Products (Last 7 Days)
create or replace view analytics_top_products as
select 
    product_name,
    count(*) as count
from analytics_events
where event_type = 'product_recommendation'
    and product_name is not null
    and created_at >= now() - interval '7 days'
group by product_name
order by count desc
limit 20;

-- Function: Get Dashboard Stats
create or replace function get_dashboard_stats(days_back integer default 1)
returns json as $$
declare
    result json;
begin
    select json_build_object(
        'overview', (
            select json_build_object(
                'unique_users', count(distinct user_id),
                'images_analyzed', count(*) filter (where event_type = 'image_analysis'),
                'questions_asked', count(*) filter (where event_type = 'question'),
                'errors', count(*) filter (where event_type = 'error')
            )
            from analytics_events
            where created_at >= now() - (days_back || ' days')::interval
        ),
        'performance', (
            select json_build_object(
                'avg_response_time_ms', round(avg(response_time_ms)::numeric, 2),
                'error_rate_percent', round(
                    (count(*) filter (where event_type = 'error')::float / 
                     nullif(count(*) filter (where event_type in ('image_analysis', 'question')), 0) * 100)::numeric, 
                    2
                )
            )
            from analytics_events
            where created_at >= now() - (days_back || ' days')::interval
        )
    ) into result;
    
    return result;
end;
$$ language plpgsql;

-- ============================================================================
-- 8. Permissions
-- ============================================================================
grant all on all tables in schema public to authenticated;
grant all on all tables in schema public to anon;
grant all on all sequences in schema public to authenticated;
grant all on all sequences in schema public to anon;
grant all on all functions in schema public to authenticated;
grant all on all functions in schema public to anon;
