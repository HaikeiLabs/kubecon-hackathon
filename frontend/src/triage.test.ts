import { describe, expect, it } from "vitest";
import { api } from "./api";
import { mock } from "./mock";
import { linkConcepts } from "./triage";

describe("mock concept linking", () => {
  it("tags Wi-Fi reports with fd:WifiOutage under Connectivity", () => {
    const r = linkConcepts("Wi-Fi keeps dropping in 2A");
    expect(r.concept_ids).toContain("fd:WifiOutage");
    expect(r.concept_ancestors).toContain("fd:Connectivity");
    expect(r.concept_tags[0].method).toBe("exact");
  });
});

describe("seeded triage dispositions", () => {
  it("covers existing, new and needs_review", async () => {
    await mock.reset();
    const byId = Object.fromEntries((await mock.listReports()).map((r) => [r.id, r]));
    expect(byId.r7.triage?.disposition).toBe("existing_bucket");
    expect(byId.r7.triage?.bucket_id).toBe("b-wifi");
    expect(byId.r7.triage!.confidence).toBeGreaterThanOrEqual(0.75);
    expect(byId.r8.triage?.disposition).toBe("new_bucket");
    expect(byId.r8.triage?.proposed_title).toBeTruthy();
    expect(byId.r9.triage?.disposition).toBe("needs_review");
    expect(byId.r9.triage?.governance.every((g) => g.decision === "allow")).toBe(true);
  });
});

describe("confirm governance", () => {
  it("denies attendee-agent with 403 and audits it; organizer is allowed", async () => {
    await mock.reset();
    api.setRole("attendee-agent");
    await expect(api.confirm("r7", { bucket_id: "b-wifi" })).rejects.toMatchObject({ status: 403, governance: { rule: "role-not-allowed", decision: "deny" } });
    expect((await api.listAudit(1))[0]).toMatchObject({ tool: "friction.assign_report", decision: "deny" });

    api.setRole("organizer");
    const r = await api.confirm("r8", { new_bucket_title: "Vegetarian lunch ran out" });
    expect(r.status).toBe("confirmed");
    const b = (await api.listBuckets()).find((x) => x.id === r.bucket_id);
    expect(b?.category).toBe("Food and beverage");
    expect((await api.listAudit(1))[0].decision).toBe("allow");
  });
});
