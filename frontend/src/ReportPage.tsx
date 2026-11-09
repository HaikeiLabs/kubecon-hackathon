import { useRef, useState, type FormEvent } from "react";
import { api } from "./api";

const MIN = 8;
const MAX = 4000;

type State = { kind: "editing" } | { kind: "submitting" } | { kind: "error"; message: string } | { kind: "done" };

export default function ReportPage() {
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [touched, setTouched] = useState(false);
  const [state, setState] = useState<State>({ kind: "editing" });
  const doneRef = useRef<HTMLHeadingElement>(null);

  const tooShort = description.trim().length < MIN;
  const showInvalid = touched && tooShort;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (tooShort) return;
    setState({ kind: "submitting" });
    try {
      await api.submitReport({ description: description.trim(), location: location.trim() || null });
      setState({ kind: "done" });
      setDescription("");
      setLocation("");
      setTouched(false);
      requestAnimationFrame(() => doneRef.current?.focus());
    } catch (err) {
      // Draft stays in the fields so the attendee can retry.
      setState({ kind: "error", message: err instanceof Error ? err.message : "Something went wrong." });
    }
  }

  if (state.kind === "done") {
    return (
      <section className="narrow card" aria-live="polite">
        <h1 ref={doneRef} tabIndex={-1}>Thanks — your report was sent</h1>
        <p>The organizing team reviews every report. We can't promise a specific fix, and because reports are anonymous we won't follow up with you directly.</p>
        <button className="primary" onClick={() => setState({ kind: "editing" })}>Report another problem</button>
      </section>
    );
  }

  const submitting = state.kind === "submitting";

  return (
    <section className="narrow">
      <h1>Report a problem</h1>
      <p className="lede">Something getting in the way of your conference? Tell the organizers. You don't need to know which team handles it.</p>

      <div className="notice" role="note">
        <strong>Reports are anonymous.</strong> Please don't include names, emails, phone numbers, or health details.
      </div>

      <form onSubmit={onSubmit} noValidate className="card">
        <div className="field">
          <label htmlFor="description">What's the problem? <span className="req">(required)</span></label>
          <textarea
            id="description"
            rows={6}
            maxLength={MAX}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onBlur={() => setTouched(true)}
            aria-invalid={showInvalid}
            aria-describedby="description-hint description-error"
            placeholder="e.g. The step-free entrance to Hall B is blocked by carts"
            disabled={submitting}
          />
          <div className="hint" id="description-hint">{description.length}/{MAX}</div>
          {showInvalid && <div className="error-text" id="description-error">Please describe the problem in at least {MIN} characters.</div>}
        </div>

        <div className="field">
          <label htmlFor="location">Where, or which session? <span className="opt">(optional)</span></label>
          <input id="location" maxLength={160} value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Room 2A, or the Day 2 keynote" disabled={submitting} />
        </div>

        <div aria-live="assertive">
          {state.kind === "error" && (
            <div className="alert" role="alert">
              <strong>Your report wasn't sent.</strong> {state.message} Your text is still here — try again.
            </div>
          )}
        </div>

        <button className="primary" type="submit" disabled={submitting} aria-busy={submitting}>
          {submitting ? "Sending…" : "Send report"}
        </button>
        <span className="sr-only" aria-live="polite">{submitting ? "Sending your report" : ""}</span>
      </form>
    </section>
  );
}
