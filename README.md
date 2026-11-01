# Lambda cold-start benchmark

Track D.

## Design decisions
- Function is deliberately tiny so the measured latency is mostly startup cost. Limit: this understates real cold starts (large dependencies, big packages). Heavier function comparison is planned for week two.
