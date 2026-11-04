import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api, ApprovalRequest } from "../api";
import GuardPanel, { secondsLeft } from "./GuardPanel";

const ask: ApprovalRequest = {
  id: "a1",
  tool: "run_powershell",
  summary: "Get-ChildItem C:\\",
  reason: "shell command",
  risk: "high",
  expires_at: Date.now() / 1000 + 60,
};

describe("GuardPanel", () => {
  it("shows the guard mode and lockdown state", () => {
    const { rerender } = render(
      <GuardPanel approvals={[]} guard={{ enabled: true, mode: "strict", lockdown: false }} />,
    );
    expect(screen.getByText("GUARD STRICT")).toBeInTheDocument();
    rerender(<GuardPanel approvals={[]} guard={{ enabled: true, mode: "strict", lockdown: true }} />);
    expect(screen.getByText("LOCKDOWN")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlock" })).toBeEnabled();
  });

  it("approves a pending action once and disables the buttons", async () => {
    const approve = vi.spyOn(api, "approve").mockResolvedValue({ ok: true });
    render(<GuardPanel approvals={[ask]} />);
    expect(screen.getByText("APPROVAL · run_powershell")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(approve).toHaveBeenCalledWith("a1", true);
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Deny" })).toBeDisabled();
  });

  it("re-enables the buttons and reports when the call fails", async () => {
    vi.spyOn(api, "approve").mockRejectedValue(new Error("403 requires admin role"));
    const onError = vi.fn();
    render(<GuardPanel approvals={[ask]} onError={onError} />);
    fireEvent.click(screen.getByRole("button", { name: "Deny" }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith("403 requires admin role"));
    expect(screen.getByRole("button", { name: "Deny" })).toBeEnabled();
  });

  it("hides approve/deny for non-admin devices and blocks leaving lockdown", () => {
    render(
      <GuardPanel
        approvals={[ask]}
        guard={{ enabled: true, mode: "standard", lockdown: true }}
        canApprove={false}
      />,
    );
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByText(/Waiting for approval/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlock" })).toBeDisabled();
  });

  it("lets anyone enter lockdown", () => {
    const lockdown = vi.spyOn(api, "lockdown").mockResolvedValue({
      ok: true,
      enabled: true,
      mode: "standard",
      lockdown: true,
    });
    render(
      <GuardPanel
        approvals={[]}
        guard={{ enabled: true, mode: "standard", lockdown: false }}
        canApprove={false}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Lock" }));
    expect(lockdown).toHaveBeenCalledWith(true);
  });

  it("counts down without going negative", () => {
    expect(secondsLeft(100, 90_000)).toBe(10);
    expect(secondsLeft(100, 200_000)).toBe(0);
  });
});
