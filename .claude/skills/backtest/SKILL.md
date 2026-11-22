---
name: backtest
description: Back-test one runtime agent (or all) against its thresholds in verification/thresholds.yaml.
argument-hint: <agent-id e.g. A7 | all>
disable-model-invocation: true
---
Run `make backtest AGENT=$ARGUMENTS` in replay mode (no live Crustdata, Claude or Gmail calls), then use the backtest-auditor sub-agent to explain failures and propose the smallest fix. Do not change thresholds or golden expectations unless the spec says they are wrong.
