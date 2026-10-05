# Auth

Last verified: cef611321063 on 2026-10-05 (source + live read-only)

Auth covers account creation, sign-in and sign-out, the two httpOnly JWT cookies, silent token refresh, `/auth/me`, and the global platform-admin role. Every role uses it. The UI is the "Welcome back" page at `/login`, the "Create account" page at `/register`, and "Sign out" at the bottom of the sidebar. Overall: **beta**. Login, `/auth/me` and the route guards work and are driven live. Refresh and logout have no tests. A page reload more than 15 minutes after login sends the user back to `/login`, even though the 7-day refresh cookie is still valid. Nothing in the product can create a platform admin. SSO is deferred.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| auth-register | `POST /auth/register` (201). The "Create account" form then logs in and lands on `/projects`. Duplicate email returns 400 "Email already registered". Password needs at least 8 characters | beta | UI+API | 084c48fc | not driven (form snapshot only) | `backend/app/auth/router.py:44-51`, `auth/service.py:68-79`, `auth/schemas.py:7`, `frontend/src/auth/AuthProvider.tsx:57-63`, `tests/test_auth_api.py::test_register_user`, `::test_register_duplicate_email`. The 8-character rule has no test |
| auth-login | `POST /auth/login` sets both cookies and returns the user. A bad password returns 401 "Invalid credentials" | stable | UI+API | 5ab4a252 | 2026-10-05 | `auth/router.py:54-74`, `auth/service.py:82-89`, `frontend/src/auth/LoginPage.tsx:22`, `test_auth_api.py::test_login_user`, `::test_login_wrong_password`. Live: wrong password shows "Invalid credentials", then the right one lands on `/projects` |
| auth-me | `GET /auth/me` returns id, email, name, role, is_active. No cookie returns 401 "Not authenticated" | stable | UI+API | 5ab4a252 | 2026-10-05 | `auth/router.py:101-104`, `backend/app/dependencies.py:12-29`, `AuthProvider.tsx:36-47`, `test_auth_api.py::test_get_current_user`, `::test_protected_route_without_token` |
| auth-cookies | `access_token`: Path `/api`, 15 min. `refresh_token`: Path `/api/v1/auth`, 7 days. Both httpOnly, SameSite=Lax. Secure only when `CEDARS_COOKIE_SECURE` is true | beta | API | 5ab4a252 | 2026-10-05 | `auth/router.py:22-41`, `backend/app/config.py:28-30`. Live cookie jar: paths as above, expiry gap 603900 s (7 days minus 15 min). No test checks path or flags |
| auth-refresh | `POST /auth/refresh` reissues both cookies. `client.ts` calls it once on any non-auth 401 and retries the request | beta | UI+API | a5b72355 | not driven | `auth/router.py:77-90`, `auth/service.py:92-108`, `frontend/src/api/client.ts:6-24`, `:37-49`. No test. Reload defect under Gotchas |
| auth-logout | `POST /auth/logout` deletes both cookies. "Sign out" in the sidebar returns to "Welcome back" | beta | UI+API | 5ab4a252 | 2026-10-05 | `auth/router.py:93-98`, `AuthProvider.tsx:65-72`, `frontend/src/components/AppSidebar.tsx:148-155`. No test. Tokens are not revoked |
| auth-route-guards | `ProtectedRoute` sends a signed-out user to `/login`. `GuestRoute` sends a signed-in user from `/login` or `/register` to `/projects` | beta | UI | 8197dee8 | 2026-10-05 | `frontend/src/App.tsx:44-78`, `:91-129`. No frontend tests. No catch-all route, so an unknown path renders blank |
| auth-platform-admin | `UserRole.PLATFORM_ADMIN` bypasses every project role check and is the only role allowed on `/admin/*` | api-only | API | a5b72355 | not driven (403 side only) | `dependencies.py:43-45`, `backend/app/admin/router.py:15-28`, `auth/models.py:13-17`, `auth/service.py:75`. No endpoint, CLI or UI sets the role |
| auth-sso | OIDC/SAML sign-in for institutional identity providers | deferred | - | - | not driven | CLAUDE.md "v2 Deferred Features" |

Why the grades:
- **auth-login and auth-me are `stable`.** Both have API tests that pass on SQLite and Postgres (382/382 locally at this commit) and were driven live. The `is_active` gap on login (Gotchas) cannot happen today, because nothing can deactivate a user.
- **auth-refresh and auth-logout** have no tests. Refresh also has the reload defect.
- **auth-platform-admin is `api-only`.** It works in tests, but only a direct DB edit can create one. CLAUDE.md forbids that, so the 200 paths cannot be driven.

## How to get to it (user POV)

1. Open the app. A signed-out user lands on "Welcome back" (`/login`).
2. New users click "Create one" and fill in "Email", "Full name" and "Password", then click "Create account". The app signs them in and opens "Projects".
3. Returning users fill in "Email" and "Password" and click "Sign in". They land on "Projects".
4. The signed-in user's name shows at the bottom of the sidebar. "Sign out" is directly below it.
5. There is no "forgot password", profile page, user list or admin page. Platform admin has no UI at all.

## Driving it with control-cedars

Preconditions: the baseline. The seed password is in state.json: `PW=$(jq -r .secrets.user_password "$($CC evidence dir)/../state.json")`. Bullets marked *mutation pass* are POSTs. List them, but run them only in the mutation pass.

- **auth-me**: each seeded role reads its own user → `$CC api GET /auth/me --as viewer` → 200, `"role": "user"`, `"is_active": true`. Same for `--as admin` and `--as annotator`.
- **auth-me** (signed out): → `$CC api GET /auth/me --as anon --expect 401` → `"detail": "Not authenticated"`.
- **auth-login** and **auth-logout** and **auth-route-guards**: wrong password, right password, guest redirect, sign out →
  ```
  PW=$(jq -r .secrets.user_password "$($CC evidence dir)/../state.json"); $CC browser run - --as anon --save auth-login-logout <<EOF
  [{"goto":"/projects"},
   {"expect_url":"/login\$"},
   {"fill":{"label":"Email"},"value":"verify-viewer@example.com"},
   {"fill":{"label":"Password"},"value":"wrong-password"},
   {"click":{"role":"button","name":"Sign in"}},
   {"expect_text":"Invalid credentials"},
   {"fill":{"label":"Password"},"value":"$PW"},
   {"click":{"role":"button","name":"Sign in"}},
   {"expect_url":"/projects\$"},
   {"expect":{"role":"heading","name":"Projects"}},
   {"expect_text":"Verify Viewer"},
   {"goto":"/login"},
   {"expect_url":"/projects\$"},
   {"click":{"role":"button","name":"Sign out"}},
   {"expect_text":"Welcome back"},
   {"expect_url":"/login\$"},
   {"screenshot":"signed-out"}]
  EOF
  ```
  → PASS, 17 steps (2026-10-05), evidence `auth-login-logout-signed-out.png`. The heredoc is unquoted so `$PW` expands, which is why `$` in `expect_url` is escaped.
- **auth-cookies**: read the paths and lifetimes from the viewer cookie jar → `NOW=$(date +%s); awk -v now=$NOW '!/^#/ && $6 ~ /_token$/ {print $6, $3, $5-now}' "$($CC evidence dir)/../cookies/viewer.txt"` → `access_token /api <=900` and `refresh_token /api/v1/auth <=604800`. The jar has no HttpOnly or SameSite column, so check those flags in `auth/router.py:27-29`.
- **auth-register** (form): → `$CC browser snapshot /register --as anon --wait-text "Create account"` → textboxes "Email", "Full name", "Password", button "Create account", link "Sign in".
- **auth-register** (*mutation pass*): short password, then success →
  ```
  $CC browser run - --as anon --save auth-register <<'EOF'
  [{"goto":"/register"},
   {"fill":{"label":"Email"},"value":"verify-reg-20261005@example.com"},
   {"fill":{"label":"Full name"},"value":"Verify Reg"},
   {"fill":{"label":"Password"},"value":"short"},
   {"click":{"role":"button","name":"Create account"}},
   {"expect_text":"String should have at least 8 characters"},
   {"fill":{"label":"Password"},"value":"long-enough-pw"},
   {"click":{"role":"button","name":"Create account"}},
   {"expect_url":"/projects$"},
   {"expect_text":"No projects yet"}]
  EOF
  ```
  → PASS when the new user lands on an empty project list. Use a fresh `@example.com` address each time, because `EmailStr` rejects `.local` and `.test`.
- **auth-register** (duplicate, *mutation pass*): → `$CC api POST /auth/register --as anon --expect 400 --body '{"email":"verify-viewer@example.com","name":"x","password":"long-enough-pw"}'` → `"detail": "Email already registered"`.
- **auth-refresh** (*mutation pass*): → `$CC api POST /auth/refresh --as viewer` → 200 `{"message":"Token refreshed"}`. Then `$CC api POST /auth/refresh --as anon --expect 401` → `"No refresh token"`.
- **auth-refresh** (reload after expiry): SKIP. `browser run` logs in fresh on every run, so it cannot hold an expired access cookie next to a live refresh cookie. Prove it by reading `client.ts:37` together with `AuthProvider.tsx:38`, or wait 15 minutes in a manual browser and reload.
- **auth-platform-admin**: the 403 side → `$CC api GET /admin/queues --as admin --expect 403` → `"Platform admin required"`. The 200 side is SKIP: `$CC db query "select email, role from users"` shows every seeded user as `USER`, and only a DB edit could change that.
- **auth-sso**: SKIP, deferred.

## Gotchas

- **A reload after 15 minutes signs the user out.** The browser drops `access_token` when its max-age runs out (`auth/router.py:31`). On reload, `AuthProvider` calls `/auth/me` (`AuthProvider.tsx:38`). `client.ts:37` never tries a refresh for paths containing `/auth/`, so the 401 sets the user to null and `ProtectedRoute` redirects to `/login` (`App.tsx:55-56`). The 7-day refresh cookie is never used on this path. Silent refresh only works for API calls made while the page stays open.
- **Any failed retry after a refresh redirects to `/login`.** After a successful refresh, `client.ts:45` returns only when the retry is 2xx. A retried 403, 404 or 422 falls through to `window.location.href = "/login"` (`:47`), so a permission error after token expiry looks like being signed out.
- **`client.ts:62` calls `res.json()` on every 2xx, including 204.** The parse throws, so the mutation's `onError` runs and `onSuccess` never does. This already affects data-source delete (`frontend/src/projects/DataPage.tsx:259-265` against `backend/app/connectors/router.py:75`) and NLP query delete (`NlpQueriesSection.tsx:55` against `nlp/router.py:103`). The delete happens, but the UI reports an error and does not refresh the list.
- **"Expired" looks like "missing" in the browser.** The cookie max-age equals the JWT lifetime, so the browser drops the cookie before the token expires. A browser sees "Not authenticated" (`dependencies.py:19`), not "Token expired" (`:23`). Only a client that holds onto the cookie sees "Token expired".
- **Logout does not revoke anything.** `auth/router.py:93-98` only deletes cookies. Refresh issues a new refresh token without revoking the old one (`auth/service.py:108`). A copied refresh token works for 7 days.
- **Logout leaves the react-query cache in place.** `AuthProvider.tsx:65-72` clears the user but not the `QueryClient` (`App.tsx:23`). A second user signing in on the same tab can briefly see cached data from the first user's projects.
- **Login ignores `is_active`.** `authenticate_user` (`auth/service.py:82-89`) never checks it. Every later request does (`dependencies.py:27-28`), so an inactive user gets cookies and then a 401 "User not found" on each call. This is latent, because nothing can set `is_active` false today.
- **Known security defects** affect `auth-register` and the WebSocket endpoints. Details are tracked privately, not in this public repo.
- **No password reset, deactivation, role change or user list exists** in the API or the UI.
- **The JWT `role` claim is never read.** `create_access_token` includes it (`auth/router.py:62`), but `get_current_user` reloads the user row on every request (`dependencies.py:26`). Role changes take effect immediately.
- **The frontend does not know the user's role.** The `User` type has no `role` field (`AuthProvider.tsx:11-15`). Nothing in the UI can change for a platform admin, and no admin page exists.
- **Secure cookies are off unless configured.** `cookie_secure` defaults to False (`config.py:30`). Terraform sets it from `enable_https` (`infra/cedars-v2/main.tf:16`, passed through `ecs.tf:45`). The parity stack runs with it off (`compose.parity.yml:25`). `_validate_settings` only logs a warning when origins are non-local (`main.py:71-82`). It refuses to start only for an unsafe `secret_key` (`main.py:61-66`).
- **Errors show up about 7 seconds late.** The default `QueryClient` retries 3 times (`App.tsx:23`), so a 403 page error appears only after the retries finish.
- **eslint error** `react-hooks/set-state-in-effect` at `AuthProvider.tsx:46`. It is one of the 8 eslint errors at this commit.
