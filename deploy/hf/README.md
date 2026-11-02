---
title: Onya API
colorFrom: gray
colorTo: gray
sdk: docker
app_port: 7860
short_description: Covenant monitoring API for the Onya site.
---

# Onya API

FastAPI backend for Onya, covenant monitoring for private credit. It
serves covenant results, evidence, back-test figures, a saved sample
memo, and the live agent to the Onya site on Vercel.

Public read endpoints: `/health`, `/companies`, `/backtest`,
`/company/SNBR/periods`, `/company/SNBR/period/{period_end}`,
`/samples/memo`. The agent endpoint `POST /agent/run` needs the demo
token header and is called only by the site's server.
