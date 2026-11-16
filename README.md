# ClusterInfo patients helped

A daily, read-only PostHog retrieval estimates two patient counts for ClusterInfo, for each UTC first-arrival month and the full observation period. It uses the [agreed full-period model](https://docs.google.com/document/d/1WB6VoIIBVKr90k6ssXVMHTFe-uj1TRCrWt20gIvWWec/edit?tab=t.0#heading=h.84yf3agr9lvc).

[**Open the latest patient estimates**](https://github.com/Yukee/clusterinfo-patients-helped/tree/reports) · [Daily workflow runs](https://github.com/Yukee/clusterinfo-patients-helped/actions/workflows/estimates.yml)

## Run

Use Python 3.10 or later on macOS or Linux. The pipeline uses the standard library. Supply the ClusterInfo EU project's read-only query credential in the environment variable `POSTHOG_READONLY_KEY`.

```sh
python3 estimate.py
```

The command prints both estimates with 95% credible intervals and writes `reports/latest.json`. It refreshes through the last completed UTC day. Arrival months can be partial at either end. Every refresh rebuilds the full report, including earlier arrival months, as visitors return, additional poll answers arrive, and the population estimates change. A failed query or calculation leaves the previous report intact.

To reproduce a historical cutoff or export the underlying first-time IDs, use an explicit output path. Each exported row contains a PostHog person ID, arrival month, engagement score and flags for the two poll answers. The scheduled run saves aggregate data only.

```sh
python3 estimate.py --as-of 2026-11-16T11:59:28Z --output reports/reference.json
python3 estimate.py --ids-csv reports/valid-ids.csv
python3 -m unittest -v
```

## GitHub Actions

GitHub schedules the hosted runner daily at 06:17 UTC. A maintainer can also start it from **Actions → Daily patient estimates → Run workflow** on main. It checks the model, refreshes the estimates, and publishes the cohort summary and JSON to the reports branch. Its commit history preserves earlier snapshots. The latest successful report remains available if a refresh fails.

The workflow reads the repository Actions secret `POSTHOG_READONLY_KEY` and uses GitHub’s job token to write to the reports branch. The public summary includes modeled estimates, monthly visitor counts and assumptions. Individual visitor exports and the per-score poll inputs stay out of the published files.

## Optional local schedule

On macOS, run the following from the checkout. The installer registers a per-user LaunchAgent, runs the job immediately, and schedules it for 07:15 local time. macOS runs a missed calendar job on wake while the user session is active. The agent uses the installed Python executable and reads the PostHog credential from the user's interactive zsh environment, as on the ClusterInfo workstation. Keep the key in that environment and keep the checkout at the installed path. Re-run the installer after moving the repo or changing the interpreter.

```sh
python3 schedule.py install
python3 schedule.py status
```

The report records its retrieval time and exclusive UTC cutoff. Check `reports/refresh.log` for the summary or `reports/refresh.err` for errors. To unregister the local job, run `python3 schedule.py remove`. All tracker code lives in this checkout. Launchd stores its registration in the user's LaunchAgents directory. On another host, an existing scheduler can call `estimate.py` with the same environment.

## What the two counts mean

Write N for valid first-time IDs, S for their estimated help-seeking share, and A for action intent conditional on seeking help. Four editable probabilities live in [assumptions.json](assumptions.json). Use `--assumptions PATH` for a separate scenario.

| Setting | Default | Meaning |
| --- | ---: | --- |
| multiple_id_correction | 0.80 | People per tracked ID |
| act_given_intent_and_help_seeking | 0.90 | Probability an intending help-seeker acts |
| helped_given_act_and_help_seeking | 0.50 | Probability an acting help-seeker benefits |
| counterfactual_share | 0.50 | Share of those benefits attributable to earlier relief through ClusterInfo |

- **Patients who find help on ClusterInfo** = N × S × A × multiple-ID correction × probability of acting. This output counts estimated actors. It includes people who try something and experience no benefit.
- **Patients who find counterfactual relief** = patients who find help × probability of benefiting after action × counterfactual share.

Counts are posterior expectations for arrival cohorts. Actual action, benefit and attribution are modeled. The four downstream factors stay fixed within a run, so the intervals quantify uncertainty from the polls under the stated assumptions. The default relief estimate is one quarter of the find-help estimate.

## Retrieval and inference

1. [cohort.sql](cohort.sql) groups all project events before the cutoff by PostHog person ID to find each ID's first recorded event. Its observation window starts at the first actionable-learning response, 2026-09-30 23:56:05 UTC. An arriving ID qualifies if it has an event in the window on a two-letter locale-prefixed, non-extraction page on clusterinfo.org or www.clusterinfo.org. Events geolocated to China or Singapore are excluded as a bot proxy. Visitors who also visit an extraction page can qualify. Update the path list when extraction translations launch.
2. A qualifying ID scores one point for reaching a guide body's bottom, one for activity on at least two distinct eligible paths and one for recording a page duration of at least 60 seconds. Score and answers are measured through the common cutoff, so an older arrival can have more follow-up time. The query evaluates valid IDs in PostHog before grouping, so default reporting involves no identifier export.
3. Within each score, update a Beta(1, 1) help-seeking prior with the unambiguous yes/no answers to `intent_poll_answered` from valid first-time IDs. For actionable learning, use `guide_poll_answered` among people who unambiguously answered yes to help-seeking. This calibration pool includes eligible returning visitors who answered both polls in the observation window. Each ID contributes once per poll. Repeated identical answers count once. Conflicting answers are excluded from that poll's update, and absent answers leave the ID in the eligible denominator.
4. Update independent Beta(1, 4), Beta(2, 3), Beta(3, 2), Beta(4, 1) action-intent priors for scores 0–3 with those pooled guide yes/no counts. An empty stratum retains its prior. These are score-specific priors with no ordering constraint. Inference assumes poll respondents represent others at the same engagement score.
5. For a cohort with score counts N_e, each draw computes H = Σ N_e s_e and J = Σ N_e s_e a_e. Report S = H / N and A = J / H and use J in both count formulas. Multiply within each draw before summarising. All months share the same period-wide probability draws but have their own observed engagement mix. This keeps sparse months estimable and the monthly count estimates additive. The full-period interval is computed from the full-period draws. Empty months have zero counts and undefined shares.
6. [estimate.py](estimate.py) publishes one JSON snapshot atomically. It includes cutoff, settings, score evidence, posterior parameters, monthly and full-period counts, intervals and the underlying anonymous aggregate inputs. The default simulation uses 100,000 draws with seed 20261116; both are CLI options. Replaying a frozen cutoff against live PostHog can reflect subsequent ingestion or identity corrections.

### Reference replay

For the cutoff 2026-11-16 11:59:28 UTC the implementation reproduced 9,360 eligible arrivals, help-seeking share 38.5% and conditional actionable learning 47.9%. The four action posteriors were Beta(1, 4), Beta(2, 4), Beta(9, 2), and Beta(33, 2). With the default downstream factors this gives approximately 1,243 patients who find help and 311 with counterfactual relief over that period.
