# Ten-equation formula–code crosswalk

The manuscript Methods source is authoritative for definitions and numbering. The historical eight-equation crosswalk is deprecated because it omitted `Eq06 / eq:component-ratio` and `Eq09 / eq:signed-diagnostics`.

| Equation | Methods label | Scientific role | Candidate implementation role |
|---|---|---|---|
| Eq01 | `eq:proxy-baseline` | pre-fire event-specific proxy baseline | `event_trajectory` in the forest-aligned and alignment scripts |
| Eq02 | `eq:proxy-normalized` | baseline-normalized annual proxy | `event_trajectory` |
| Eq03 | `eq:proxy-indicator` | annual threshold indicator | `first_completion` |
| Eq04 | `eq:proxy-attainment` | two-year sustained attainment and strict cohort | `first_completion` / `build_proxy_status` |
| Eq05 | `eq:proxy-reattainment` | post-decline re-attainment | `post_decline_reattainment`-type logic in the frozen alignment implementation |
| Eq06 | `eq:component-ratio` | component ratio diagnostic | component-ratio calculation in the frozen alignment implementation |
| Eq07 | `eq:component-deficit` | component deficit diagnostic | deficit calculation in the frozen alignment implementation |
| Eq08 | `eq:lrsd-domains` | height, canopy, contextual, and balanced LRSD domains | `build_structure_endpoints` / `structure_endpoints` |
| Eq09 | `eq:signed-diagnostics` | signed height, canopy, and canopy-minus-height diagnostics | `build_structure_endpoints` and the corrected supporting sensitivity function |
| Eq10 | `eq:tail-fraction` | strict-cohort tail fraction | endpoint summaries and bootstrap summaries |

The public release must replace the role-level descriptions above with exact staged file names, function names, line ranges, and observed hashes after byte-preserving staging. `Eq10` uses the strict-cohort denominator in Methods; an endpoint/cohort mismatch must be reported and reconciled, not silently substituted.

Notation domains are `g ∈ {H, C, L, bal}`; `bal` is the equal-weight height/canopy-amount endpoint. The primary LRSD threshold is `delta = 0.20`.
