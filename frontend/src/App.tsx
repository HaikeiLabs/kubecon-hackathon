import { useEffect, useState } from "react";
import { USE_MOCK } from "./api";
import ReportPage from "./ReportPage";
import OrganizerPage from "./OrganizerPage";

type Route = "report" | "organizer";
const routeFromHash = (): Route => (location.hash === "#/organizer" ? "organizer" : "report");

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    document.title = route === "organizer" ? "Organizer inbox · Friction Desk" : "Report a problem · Friction Desk";
  }, [route]);

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <span className="brand">Friction Desk</span>
        <nav aria-label="Pages">
          <a href="#/report" aria-current={route === "report" ? "page" : undefined}>Report a problem</a>
          <a href="#/organizer" aria-current={route === "organizer" ? "page" : undefined}>Organizer</a>
        </nav>
        {USE_MOCK && <span className="badge">Demo data</span>}
      </header>
      <main id="main" tabIndex={-1}>
        {route === "report" ? <ReportPage /> : <OrganizerPage />}
      </main>
    </>
  );
}
