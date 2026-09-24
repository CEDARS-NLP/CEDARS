# SSO Setup

CEDARS supports a hybrid authentication model. Local username/password login remains available for non-SSO users, while configured SSO email domains are reserved for MSK SSO sign-in.

## Current Implementation Status

The current implementation adds the SSO foundation:

- V2-compatible auth libraries for new backend auth work: `python-jose[cryptography]` and `passlib[bcrypt]`.
- Legacy Werkzeug password verification remains supported for existing local users.
- New local password hashes use bcrypt through passlib.
- The `Users` table can store nullable SSO identity metadata.
- Local login and registration are blocked for configured SSO-only email domains.
- The frontend can discover whether SSO is enabled and show a Sign in with SSO button.

The live OIDC authorization callback and MSK token exchange are the next implementation step. Those routes should follow the MSK reference workflow when the gated reference files are available locally.

## Environment Variables

Set these variables for an SSO deployment:

| Variable | Purpose |
| --- | --- |
| `SSO_ENABLED` | Set to `true` to show the SSO option in the frontend. |
| `SSO_PROVIDER_NAME` | Display name for the login button, for example `MSK SSO`. |
| `SSO_ISSUER` | OIDC issuer URL. |
| `SSO_AUTHORIZATION_ENDPOINT` | OIDC authorization endpoint. |
| `SSO_TOKEN_ENDPOINT` | OIDC token endpoint. |
| `SSO_USERINFO_ENDPOINT` | Optional OIDC userinfo endpoint. |
| `SSO_JWKS_URI` | JWKS endpoint used to validate ID tokens. |
| `SSO_CLIENT_ID` | OIDC client ID registered with the provider. |
| `SSO_CLIENT_SECRET` | OIDC client secret. Store securely. |
| `SSO_REDIRECT_URI` | Redirect URI registered with the provider, usually `/api/v1/auth/sso/callback`. |
| `SSO_SCOPES` | Space-separated OIDC scopes. Default is `openid email profile`. |
| `SSO_ALLOWED_EMAIL_DOMAINS` | Comma-separated domains that must use SSO, for example `mskcc.org`. |
| `SSO_REQUIRED_CLAIMS` | Comma-separated required claims. Default is `sub,email`. |
| `SSO_GROUPS_CLAIM` | Claim name that contains ezGroups or group values. Default is `groups`. |
| `SSO_LOGOUT_ENDPOINT` | Optional provider logout endpoint for IdP logout. |
| `SSO_POST_LOGOUT_REDIRECT_URI` | Optional post-logout return URL. |

## Domain Enforcement

Any username that looks like an email address under `SSO_ALLOWED_EMAIL_DOMAINS` is rejected by local registration and local password login. Those users must use the SSO button.

Non-SSO-domain local users keep the current username/password flow.

## Claims and Groups

SSO claims are configurable because provider behavior can vary by deployment. The planned OIDC callback should validate at least `sub` and `email`, and should require `email_verified` when MSK SSO emits that claim. ezGroups can be parsed from `SSO_GROUPS_CLAIM`, but this implementation does not yet synchronize groups to CEDARS global admin or project roles.

## Database Notes

The global `Users` table includes nullable SSO metadata columns:

- `auth_provider`
- `sso_subject`
- `sso_email`
- `sso_email_verified`
- `sso_groups_json`
- `last_login_time`

SSO accounts should be created with `password_hash=NULL`. Existing local accounts are not migrated automatically.

## Testing

Use the repository test environment at `CEDARS/cedars/.testenv`:

```powershell
Push-Location .\CEDARS
$env:PYTHONPATH = "$PWD;$PWD\cedars"
.\cedars\.testenv\Scripts\python.exe -m pytest cedars\tests_fastapi\test_sso_auth.py cedars\tests_fastapi\test_p1_auth_projects.py -v
Pop-Location
```

Frontend lint/build requires Node.js and npm on the machine running the check.