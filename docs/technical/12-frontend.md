# 12 — Frontend (`jd-erp-web`)

React 19 + TypeScript + Vite 8, Tailwind 4, TanStack Query 5, Zustand 5,
react-hook-form + zod, axios, react-router-dom 7.

---

## 12.1 Directory layout

```
src/
  main.tsx                 boot: QueryClientProvider + RouterProvider
  App.tsx
  router.tsx               ALL routes, hash router
  index.css                Tailwind entry

  api/
    client.ts              axios instance + JWT interceptors
    endpoints/*.ts         one module per backend app — types + call functions

  auth/
    store.ts               zustand + persist  (localStorage key: jd-erp-auth)
    permissions.ts         useCan / useCanModule / useHasPermPrefix
    ProtectedRoute.tsx     redirects to /login or /portal/login
    PublicOnlyRoute.tsx    keeps logged-in users off the login pages

  components/
    layout/                AppLayout, Sidebar, Topbar  (staff)
                           PortalLayout, PortalSidebar, PortalTopbar (portal)
                           icons.tsx
    ui/                    Button, Card, TextField, Textarea, SelectField,
                           StatusPill, StarRating
    audit/FieldInput.tsx   dynamic audit-form field renderer

  hooks/                   useDebouncedValue, usePortalMe
  lib/                     env.ts, errors.ts, queryClient.ts, examLink.ts
  pages/                   ~190 page components, grouped by feature
```

The `@` alias maps to `src/` (`vite.config.ts` + `tsconfig.app.json`).

## 12.2 Routing

`createHashRouter` — URLs are `https://host/#/leads`. Hash routing is used so
the bundle can be served from any static host without server rewrite rules.
**Any deep link you share must include the `#`.**

Three route tiers:

| Tier | Wrapper | Routes |
|---|---|---|
| Fully public | none | `/apply/:token` (application form), `/exam/:token` (entrance exam) |
| Public-only | `PublicOnlyRoute` | `/login`, `/portal/login`, `/forgot-password`, `/reset-password/:uid/:token` |
| Authenticated | `ProtectedRoute` → `AppLayout` or `PortalLayout` | Everything else. `/portal/*` uses the portal layout |

`ProtectedRoute` waits for the persisted store to rehydrate, then redirects to
`/portal/login` if the path starts with `/portal`, else `/login`.

## 12.3 Auth and the API client

### The store (`auth/store.ts`)

Zustand with `persist`. Persists **only** `{access, refresh, user}` under
`jd-erp-auth` in `localStorage`. Exposes `loginWith`, `logoutAndClear`,
`setTokens`, `setUser`, `clear`, and a `sessionExpired` flag the login page
reads to show a "your session expired" banner.

At module load it wires itself into the API client via `installAuthHandlers`,
using closures so the interceptors always read fresh state.

### The client (`api/client.ts`)

- **Request interceptor** attaches `Authorization: Bearer <access>`.
- **Response interceptor** on a 401:
  - never refreshes a 401 that came *from* `/api/auth/refresh/` — that clears
    the session instead;
  - marks the request `_retry` so a request is only retried once;
  - shares **one in-flight refresh** (`refreshPromise`) across concurrent
    401s, so a page that fans out to five endpoints refreshes once;
  - on success, replays the original request with the new token;
  - on failure, calls `onAuthFailure` → clears the store and sets
    `sessionExpired` (only if there were tokens to lose).

With a 15-minute access token and a 45-minute refresh token, this is invisible
to users until 45 minutes of inactivity.

### Endpoint modules

One file per backend app under `api/endpoints/`, each exporting TypeScript
types plus thin call functions. **They are hand-maintained — there is no
generated client.** When you change a serializer, update the matching
`endpoints/*.ts` type by hand.

Remember that some list endpoints return a bare array and others return
`{count, next, previous, results}` ([chapter 2](02-platform-foundations.md)
§2.4). Check the backend view before typing a response.

### Error handling (`lib/errors.ts`)

`extractApiError(err)` flattens any DRF error shape (string `detail`, array
`detail`, `non_field_errors`, field-level string or array) into one
user-facing string. `extractFieldErrors(err)` returns a flat
`{field: message}` dict for form binding. Use these rather than reading
`err.response.data` directly.

### Query defaults (`lib/queryClient.ts`)

`retry: false`, `refetchOnWindowFocus: false`, `staleTime: 30_000`. Retries are
off deliberately — a 403 or a validation error should surface immediately, not
after three attempts.

## 12.4 Permission gating

Three hooks in `auth/permissions.ts`, all satisfied automatically for
superusers, all returning `false` for a user with no `permissions`/`modules`
array (an older persisted session — they must log out and back in):

| Hook | Semantics |
|---|---|
| `useCan(perm \| perm[])` | Exact key match. `true` if the user holds **any** of them |
| `useCanModule(module \| module[])` | Membership in the `modules` array |
| `useHasPermPrefix(prefix \| prefix[])` | `key === prefix` or `key.startsWith(prefix + '.')` — "does the user have *any* access to this area" |

### Sidebar

`components/layout/Sidebar.tsx` declares the whole navigation as a `NAV`
array. Each top-level item may declare `modules` (unlocks the group); each
child may declare:

- `perms: string[]` — **prefix** matching, same rule as `useHasPermPrefix`. So
  `"audit.faculty_daily"` matches `audit.faculty_daily.view_all`. Omitted means
  not permission-gated (self-service pages like "My Leaves").
- `requiresStudent: true` — only shown to `is_student` users (and superusers).
  This is how the "My X" pages are hidden from staff.
- `children` — a nested collapsible sub-group.

Top-level groups: Dashboard, Leads, Admission, LMS, Slot, Academics, HR,
Leaves, Tasks, Forms to fill, Audit, Master (settings), plus Settings.

> **The sidebar is presentation only.** Hiding a link does not protect the
> endpoint — the API enforces its own permission on every request. Conversely,
> granting a permission without adding the sidebar entry leaves the feature
> reachable only by typing the URL. Both sides must be updated together.

## 12.5 Two apps, one bundle

| | Staff | Portal |
|---|---|---|
| Layout | `AppLayout` + `Sidebar` + `Topbar` | `PortalLayout` + `PortalSidebar` + `PortalTopbar` |
| Login | `/#/login` | `/#/portal/login` |
| Routes | `/#/...` | `/#/portal/...` |
| Auth | Same `/api/auth/login/` endpoint for both | |
| Gating | Permission keys | `is_student` / `is_parent` from `/me` |

After login the app routes on the `is_student` / `is_parent` flags in the
`/api/auth/me/` payload.

## 12.6 Page inventory (by area)

| Area | Pages |
|---|---|
| Dashboard | `DashboardPage`, `MyDailyReportPage`, `MyAdminDailyReportPage`, `SettingsPage` |
| Leads | list / create / detail / edit, `LeadReportsPage`, `CounsellorPoolsPage`, entrance-exam list/create/detail/attempt, and lead-detail panels (`SendActionsBox`, `ApplicationFeeBox`, `ApplicationFormControls`, `PromoteToStudentBox`, `ReassignBox`, `StatusChangeBox`, `FollowupsSection`, `CommunicationsSection`, `HistorySection`, `LeadExamsSection`, `BulkMessageModal`) |
| Admission | students list/detail/edit with cards (education, fees, documents, remarks, parent account, portal access, attendance, enrolments), enrolments CRUD, `FeesCollectPage`, `FeeReportsPage`, `ConcessionReportsPage`, `BatchPromotionPage` |
| LMS | assignments, courseware, lessons, marks, tests (+ `MyAssignmentsPage`, `MyTestsPage`) |
| Slot | `ScheduleCreatePage`, `PublishTimetablePage`, `CalendarPage`, `SchedulePage`, `EditSlotModal`, `MyTimetablePage` |
| Academics | attendance (take / roster / report with five tabs / mine), `BatchReportPage`, `ClosingReportPage`, `ZeroHourFormPage`, certificates, alumni, transcripts, student leaves, student documents, appointments |
| HR | employees list/create/detail + `EmployeeForm`, departments, designations, `RelievingPage` |
| Leaves | apply, my leaves, comp-off, team approvals, balances, allocations, report, types |
| Tasks | `TasksPage`, `TasksReportPage` |
| Audit | dashboards, form builder / fill / list, submissions, my forms, my submissions, faculty & admin daily grids, course-end, batch-mentor, 0-hour, feedback, self-appraisal, compliance flags |
| Master | one page per reference list, all on `_MasterShell` |
| Portal | dashboard, attendance, timetable, assignments, courseware, tests (+ attempt, result), leaves, documents, apply-documents, lessons, appointments, feedback, profile, change password, `PortalWeekCalendar` |
| Public | `ApplicationFormPage`, `EntranceExamPage` |

## 12.7 Building and deploying

```bash
npm run build      # tsc -b && vite build  →  dist/
npm run preview    # serve dist/ locally
npm run lint
```

`dist/` is a static bundle. Because it uses a hash router, **no server rewrite
rules are required** — any static host works. Set `VITE_API_URL` at build time
(Vite inlines `import.meta.env.*` into the bundle); changing it requires a
rebuild, not just an env change on the host.

## 12.8 Conventions to follow when extending

1. **New backend endpoint** → add the types and call function to the matching
   `api/endpoints/*.ts`. Do not call `apiClient` from a page component.
2. **New page** → create it under `pages/<area>/`, register it in
   `router.tsx`, and add the sidebar entry with the right `perms` prefix.
3. **Forms** → react-hook-form + zod via `@hookform/resolvers`, and bind server
   errors with `extractFieldErrors`.
4. **Server state** → TanStack Query. Do not put fetched data in Zustand; the
   store is for auth only.
5. **UI** → reuse `components/ui/`. Tailwind 4 utility classes, no CSS modules.
6. **Permission changes require a re-login** — say so in the UI when relevant.
