# The Agent Obstacle Course, Census Report

Every number below is derived from `data/census.csv`. Methodology in `METHODOLOGY.md`.

## Sample

- Sites in sample: 5000
- Unique sites after cross domain deduplication: 4732
- Scanned: 3390, declared exclusion: 148, unreachable: 1194

## Obstacle prevalence

| Obstacle | Overall | top 100 | 101 to 1000 | 1001 to 5000 |
|---|---|---|---|---|
| O1 bot wall | 14.8% (503/3390) | 6.0% (4/67) | 15.9% (94/593) | 14.8% (405/2730) |
| O2 JavaScript dependency | 10.9% (334/3062) | 24.6% (16/65) | 10.6% (56/529) | 10.6% (262/2468) |
| O3 identity discrimination | 5.4% (168/3084) | 14.1% (9/64) | 7.1% (38/539) | 4.9% (121/2481) |
| O4 login wall | 1.0% (32/3129) | 3.1% (2/65) | 0.7% (4/547) | 1.0% (26/2517) |

Sites a non browser agent can read with no scored obstacle: 72.4% (2453/3390).

## Score distribution

| Score band | Sites |
|---|---|
| 0 to 19 | 9 |
| 20 to 39 | 56 |
| 40 to 59 | 473 |
| 60 to 79 | 320 |
| 80 to 100 | 2532 |

Median score 100, mean 86.8, minimum 0, maximum 100.

## Declared exclusion versus broken

- Declared exclusion via robots.txt: 148 sites (3.1% of the unique sample). These chose to exclude agents and are not scored as broken.
- Bot walled (broken for agents without a declared policy path): 503 scanned sites (14.8%).
- Sites with named AI agent robots.txt directives: 692.
- Sites publishing llms.txt: 429.

## O3, identity discrimination findings

Of 3084 sites where both raw fetches completed, 168 (5.4%) served substantially different responses to the declared agent identity than to a stock browser identity (different status class, or raw text ratio under 0.5). This is the gap between a site being technically readable and being readable for an honestly identified agent.

First affected domains (full list in census.csv): google.com, mail.ru, hicloudcam.com, whatsapp.com, yahoo.com, spotify.com, vk.com, forms.gle, intuit.com, w3.org, webex.com, sourceforge.net, canva.com, amazon.co.uk, autodesk.com, checkpoint.com, cdc.gov, bilibili.com, temu.com, yahoo.co.jp, intel.com, duckduckgo.com, sberbank.ru, google.com.hk, rakuten.co.jp, dailymail.co.uk, ieee.org, avito.ru, amazon.fr, noaa.gov, lemonde.fr, zillow.com, amazon.es, stripchat.com, rt.ru, dailymail.com, bandcamp.com, homedepot.com, amazon.it, linode.com, airbnb.com, meta.com, state.gov, lowes.com, abovedomains.com, zhihu.com, apa.org, mercadolibre.com.mx, hltv.org, vinted.fr.

## Vantage point and limitations

The scan ran once from US cloud datacenter IPs, which bot protection treats far more harshly than residential traffic, so O1 rates are an upper bound for datacenter agents. Homepages only, single snapshot, signature lists make obstacle counts lower bounds, consent gates are recorded but unscored because US egress undercounts them.
