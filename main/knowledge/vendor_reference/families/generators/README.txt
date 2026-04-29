Generator Family Pack v2.0.0

This pack is intended to be dropped into GridSenpAI as the Generator vendor-reference family.

Rules:
- Every model file includes the full schema.
- Only source-backed fixed vendor/model fields are populated.
- Fields that depend on project controls, configuration, or operating mode remain null by design.
- The program should use populated fixed fields as vendor-reference candidates.
- The program should ask the applicant for project-specific fields when needed.
- Null fixed fields are not errors; they indicate that the current vetted source set did not support a trustworthy value.

This pack contains 25 generator records across:
- Cummins
- Caterpillar
- Rolls-Royce / mtu
- Rehlko
- Generac
