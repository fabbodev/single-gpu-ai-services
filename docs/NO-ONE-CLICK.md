# No one-click installer

This repository intentionally does not provide a single script that hides installation and configuration.

The goal is operational clarity: an administrator should be able to see which Docker network is created, which model directory each engine uses, which containers exist, which component controls Docker, and which HTTP endpoint is exposed.

If automation is added later, it should remain optional and should mirror the documented manual steps rather than replace them.
