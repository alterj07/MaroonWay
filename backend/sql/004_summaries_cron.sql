-- Schedule the summary batch from Postgres.
--
-- The generator is a long, rate-limited job and the free hosting tiers have no
-- cron, so the database is the scheduler: pg_cron fires hourly, pg_net posts to
-- the API, and the API runs one bounded chunk in the background. The job skips
-- rows it has already written, so an hourly chunk converges on a finished
-- dataset and then costs one fast request a day.
--
-- Before applying, once, in the Supabase SQL editor:
--
--     select vault.create_secret('<the API service ADMIN_TOKEN>', 'maroonway_admin_token');
--
-- That is the token Render generated for maroonway-api (render.yaml declares it
-- with generateValue: true), not the one in a local .env -- they differ. Keeping
-- it in Vault keeps it out of cron.job, whose command text any database user can
-- read.
--
-- Re-running this file is safe: cron.schedule replaces a job of the same name.
-- Deliberately free of semicolons inside the dollar-quoted body, so
-- app/ingest/apply_sql.py can split it (its splitter does not parse dollar
-- quotes).

create extension if not exists pg_cron;
create extension if not exists pg_net;

select cron.schedule(
    'summaries-hourly',
    '0 * * * *',  -- UTC
    $$
    select net.http_post(
        url := 'https://maroonway-api.onrender.com/admin/summaries/run',
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'X-Admin-Token', (
                select decrypted_secret from vault.decrypted_secrets
                where name = 'maroonway_admin_token'
            )
        ),
        body := jsonb_build_object('limit', 25),
        -- The free instance sleeps after 15 minutes idle, and a cold start can
        -- take most of a minute. The request still arrives and wakes it; a
        -- shorter timeout would only make a working run look failed.
        timeout_milliseconds := 30000
    )
    $$
);

-- Checking on it:
--
--     select jobid, jobname, schedule, active from cron.job;
--     select * from cron.job_run_details order by start_time desc limit 10;
--     select id, status_code, content, created from net._http_response order by created desc limit 10;
--
-- The last one is the one that tells the truth: pg_net queues the request and
-- returns, so cron.job_run_details reports success even when the API answered
-- 401. A healthy run is status_code 202; 409 means the previous chunk was still
-- going, which is the overlap guard doing its job.
--
--     select cron.unschedule('summaries-hourly');
