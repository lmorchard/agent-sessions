Good catch, and a pointed one — that is this issue's own defect in miniature, reintroduced by the fix for it: an assertion the driver is not in a position to make, written onto the ledger.

Fixed in 52e3155. The reason now reads **"no readable events"** rather than "empty stream", which is true both for a zero-byte stream and for a truncated or garbled one. The function comment says so explicitly, so the next reader doesn't have to rediscover that a false return means "no *readable* events" rather than "the file is empty".

The **classification** is deliberately left alone: a garbled non-empty stream still lands `driver-fault`. That preserves current behaviour for a case nobody has evidence about, and reclassifying it would go beyond both the frozen acceptance criteria and what has actually been observed. It's recorded as a known limit in the PR body and the session notes.

Re-verified after the change by an independent verifier (fresh context, the frozen manifest and the repo only): 48 park-test assertions and 113 driver-test assertions pass, and the tamper diff against the freeze commit is still empty. No assertion in either suite reads the `driver-fault` branch's reason text — verified by grep and by running the suites, not assumed — so the reword could not have been used to weaken a check.
