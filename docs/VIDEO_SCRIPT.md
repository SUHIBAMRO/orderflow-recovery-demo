# OrderFlow Recovery — English demo script

**Duration:** approximately 45 seconds

OrderFlow Recovery is a working exception-handling prototype for multi-step insurance orders.

The Scenario Lab injects controlled failures into persisted workflows. Every external insurer, payment, JPJ and notification response is synthetic, while the workflow state, retry logic, operator actions and audit events execute in the backend.

In this example, payment and policy issuance succeed, but the roadtax gateway reports an owner-data mismatch. Because this is a deterministic rejection, the system disables blind retries and requests a safe operator action.

After the synthetic owner data is corrected and the evidence note is recorded, the same workflow resumes from the blocked roadtax step. The policy is not issued twice, and the complete event trail remains available.

The public sandbox is available in English and Dutch. Additional scenarios demonstrate bounded retries, missing documents, blacklist refund approval and idempotent recovery after a lost acknowledgement.
