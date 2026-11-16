-- The first event is computed over all history before the cutoff.
-- Qualifying activity, engagement and both polls use the observation window.
WITH event_flags AS (
    SELECT person_id, timestamp, event, properties,
           coalesce(properties.$pathname, '') AS path,
           timestamp >= toDateTime('{start}', 'UTC')
               AND properties.$host IN ('clusterinfo.org', 'www.clusterinfo.org')
               AND coalesce(properties.$geoip_country_name, '') NOT IN ('China', 'Singapore')
               AS in_window,
           in_window AND match(path, '^/[a-z]{2}(/|$)')
               AND replaceRegexpOne(path, '/$', '') NOT IN (
                   '/en/guides/dmt-for-cluster-headaches/extraction',
                   '/de/leitfaden/dmt-fuer-clusterkopfschmerzen/extraktion',
                   '/es/guias/dmt-cefalea-en-racimos/extraccion',
                   '/fr/guides/dmt-algie-vasculaire-de-la-face/extraction',
                   '/pt/guias/dmt-para-cefaleia-em-salvas/extracao',
                   '/it/guide/dmt-per-cefalea-a-grappolo/estrazione',
                   '/pl/poradniki/dmt-dla-klasterowego-bolu-glowy/ekstrakcja',
                   '/fi/oppaat/dmt-sarjoittaiseen-paansarkyyn/uutto'
               ) AS eligible_path
    FROM events
    WHERE timestamp < toDateTime('{end}', 'UTC')
), visitors AS (
    SELECT person_id, min(timestamp) AS first_seen,
           if(first_seen >= toDateTime('{start}', 'UTC'),
              formatDateTime(first_seen, '%Y-%m', 'UTC'), 'returning') AS arrival_month,
           toInt(countIf(in_window AND event = 'guide_page_body_scrolled_to_bottom') > 0)
             + toInt(uniqExactIf(path, eligible_path) >= 2)
             + toInt(countIf(in_window AND event = 'page_visit_duration'
                             AND toFloat(properties.duration_seconds) >= 60) > 0) AS score,
           countIf(in_window AND event = 'intent_poll_answered' AND properties.answer = 'yes') > 0 AS help_yes,
           countIf(in_window AND event = 'intent_poll_answered' AND properties.answer = 'no') > 0 AS help_no,
           countIf(in_window AND event = 'guide_poll_answered' AND properties.value = 'yes') > 0 AS guide_yes,
           countIf(in_window AND event = 'guide_poll_answered' AND properties.value = 'no') > 0 AS guide_no
    FROM event_flags
    GROUP BY person_id
    HAVING countIf(eligible_path) > 0
)
