# Prompt Complexity Checklist

How to gauge whether a prompt is complex enough to meaningfully test a code agent. A good evaluation prompt should take 2-3 hours of real work, involve multiple files, and require genuine problem-solving.

---

## High Complexity Signals

These indicate a prompt that will meaningfully challenge a code agent:

- [ ] Multiple features/requirements in single prompt
- [ ] Database schema changes (new tables, migrations)
- [ ] Auth/authorization changes
- [ ] API endpoints + frontend UI
- [ ] Integration with external services
- [ ] State management complexity
- [ ] Multi-file changes required
- [ ] Testing requirements mentioned
- [ ] Error handling requirements
- [ ] Real-world business logic

## Low Complexity Signals

These suggest the prompt is too simple for a thorough evaluation:

- [ ] Single UI component
- [ ] "Add a button that..."
- [ ] Simple CRUD with no edge cases
- [ ] Styling/CSS only changes
- [ ] Documentation only
- [ ] Single file change
- [ ] No database involvement
- [ ] Trivial bug fix

---

## Scope Estimation

| Scope | Estimated Time | Verdict |
|-------|---------------|---------|
| Trivial | <30 min | Too simple for meaningful evaluation |
| Light | 30-60 min | Borderline -- needs expansion |
| Medium | 1-2h | Acceptable minimum |
| Complex | 2-3h | Ideal for evaluation |
| Epic | 3h+ | Good but may not finish |

---

## Examples

### Too Simple

```
Add a logout button to the header
```
- Single component change
- No backend
- <30 min work

### Borderline

```
Add user profile page where users can update their name and email
```
- Single feature
- Basic CRUD
- Maybe 1h work
- **Expand with:** validation, avatar upload, password change, email verification

### Good

```
We need a notification system. Users should be able to receive notifications
when someone comments on their post, likes their content, or follows them.
They need a notification bell in the header showing unread count, and a
dropdown to see recent notifications. Mark as read functionality.
Persist to database.
```
- Multiple notification types
- Real-time updates
- Database changes
- UI components
- 2-3h scope

### Ideal

```
We still don't have an admin interface for employers. right now, there's
no way for them to see who's applying, schedule interviews, accept or
reject people, or even update their company profile...

Employers need a dashboard to see what's going on, a way to add and remove
employees and see who's active. They will need to be able to change settings
for their company profile, and some basic statistics and reports. They'll
need CRUD operations...

also, when someone signs up, we have no idea if they're looking for a job
or if they're an employer posting positions...

Local Supabase is set up already...
```
- Full-stack (frontend + backend + database)
- Multiple features (dashboard, CRUD, auth flow)
- Role-based access
- Real business logic
- 2-3h+ scope

---

## Expanding a Simple Prompt

If your prompt scores too low, consider adding:

- Database schema changes
- Auth/role-based access
- Error handling requirements
- Testing requirements (TDD, E2E)
- Integration complexity
- Multiple user flows
