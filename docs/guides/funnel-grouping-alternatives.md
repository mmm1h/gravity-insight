# Funnel property-grouping alternative

Funnel responses must not be interpreted as property-grouped when a requested
non-time grouping is absent. The current upstream date-priority behavior is an
explicit unsupported response shape:

- whole-window grouping labels must appear at `aggregate_date.group.*`;
- daily grouping labels must appear at `date_list.[].*.[].group`;
- ISO dates at either label location do not satisfy the requested dimension.

The Runtime returns `ok=false`, `status=contract_changed`,
`error.field=group_by_list`, and an `unsupported_items` entry for every missing
grouping dimension when a non-empty numeric result has this shape. Do not use
the remaining numbers as grouped values.

Until grouped readback is re-verified, use separate filtered requests:

1. Set `calculate_each_day=false` and remove `group_by`.
2. For each known arm value, issue one request with exactly one user-property
   equality filter for that value. Do not combine arms in one filter.
3. Bind each request ID to its input arm and filter offline before dispatch.
4. Accept only the numeric vector at `aggregate_date.total` after verifying the
   returned request/filter binding. Never infer an arm from a response date.
5. For D0 registration funnels, keep the registration event as the anchor and
   use the `today` window so later visits do not redefine the cohort.

This workaround increases request count linearly with the number of arms. It
does not prove that native Funnel grouping is supported and must be retired
only after both daily modes return a verified non-date group dimension.
