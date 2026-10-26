# Security

MATERIALMIND is a local research application. Its server binds to `127.0.0.1`; it has no
production authentication or multi-tenant isolation and should not be exposed to a network.
Session state is held in memory and cleared on restart. CIF inputs are size-limited and
validated but should be trusted research files. Do not load untrusted Python pickle/joblib
artifacts; the application fits the included model from data instead of loading arbitrary models.

Report reproducible security problems privately using GitHub's private vulnerability reporting
if available, or contact the repository owner through their public GitHub profile. Do not
include secrets or private research data in a public issue.
