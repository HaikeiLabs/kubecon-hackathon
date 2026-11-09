# Frontend Plan: Conference Friction Desk

## Goal

Build a two-page demo that makes the attendee-to-organizer feedback loop obvious:

1. An attendee reports a problem affecting their conference experience.
2. The organizer sees the report grouped into an existing issue bucket—or as a new bucket if it does not match.

The interface should foreground the attendee impact and the action organizers can take, not the underlying agent implementation.

## Core experience

### Attendee report page

- A concise form for the issue description, with optional category, location/session, and contact/follow-up preference.
- Clear guidance not to include sensitive personal information.
- Submission confirmation that does not promise a fix or expose other attendees' reports.
- Loading, validation, and failure states; preserve the draft on a recoverable error.

### Organizer page

- A live or refreshable inbox of incoming reports and issue buckets.
- Each incoming report shows the original text, relevant context, and the agent's proposed match or proposed new bucket.
- Existing-bucket matches show the bucket title, number of related reports, and a short explanation of the match.
- New-bucket proposals show a suggested title/summary and why it appears distinct.
- The organizer can confirm or correct the match. Do not silently merge low-confidence or ambiguous reports.
- A detail view/panel shows reports grouped under a bucket, impact/urgency rationale, and suggested next action.

## Stretch experience

Prioritize these only after the full core flow works:

- **Organizer review controls:** edit bucket summary/category, move a report, mark resolved, or request follow-up.
- **Impact signals:** show trends over time, affected areas, accessibility-related tags, and number of related reports. Treat model-produced labels as suggestions, not facts.
- **Draft fix:** show a proposed website/schedule fix or draft PR link/status, with explicit human review required.
- **Live updates:** push new report/bucket updates to the organizer page rather than requiring refresh.
- **Observability view:** a compact demo panel for request/agent latency or a Dash0 link, if instrumentation is ready.
- **Discord intake:** accept reports via the existing bot while keeping this UI as the shared organizer view. Avoid building a second, separate triage flow.

## UI states and accessibility

- Design for keyboard navigation, visible focus, labels, adequate contrast, and screen-reader announcements for submission status.
- Use plain language and avoid requiring attendees to know a department or issue category.
- Ensure the organizer can distinguish attendee-provided content from AI-generated summaries and recommendations.
- Provide empty, loading, error, and seeded-demo states.

## Frontend/backend contract

Keep the UI independent of the model and Elasticsearch implementation. It should submit a report and render API responses for report status, bucket assignment, match confidence/reason, and organizer actions. Agree on the API schema with the backend before implementing against mock data; keep a small typed mock fixture so UI work can proceed before integration.

Suggested core objects:

- `Report`: id, text, optional location/session/category, created time, status, bucket id.
- `Bucket`: id, title, summary, category, status, report count, updated time.
- `TriageResult`: proposed bucket or new-bucket proposal, confidence, explanation, suggested action.

The API plan is the source of truth for exact fields and endpoint names.

## Acceptance criteria

- An attendee can submit a report and receive a clear confirmation.
- An organizer can see the new report and its proposed disposition.
- The UI clearly distinguishes an update to an existing bucket from creation of a new bucket.
- An organizer can confirm/correct an uncertain disposition.
- The demo works with seeded data and communicates agent failures gracefully.
- Core pages remain usable on a laptop-sized demo screen and are keyboard accessible.
