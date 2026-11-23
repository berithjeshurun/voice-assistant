import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api, ApiError, ReminderItem } from "../api";
import RemindersPanel, { formatDue } from "./RemindersPanel";

const NOW = new Date(2026, 10, 11, 10, 0).getTime(); // Wed 11 Nov 2026 10:00 local
const ts = (d: Date) => d.getTime() / 1000;

const items: ReminderItem[] = [
  { id: 2, text: "call mom", kind: "reminder", due_ts: ts(new Date(2026, 10, 11, 18, 0)), repeat_text: "" },
  { id: 1, text: "timer", kind: "timer", due_ts: NOW / 1000 + 600, repeat_text: "" },
  { id: 3, text: "stand up", kind: "reminder", due_ts: ts(new Date(2026, 10, 12, 9, 0)), repeat_text: "every weekday" },
];

describe("formatDue", () => {
  it("is relative when soon and a clock time later", () => {
    expect(formatDue(NOW / 1000 + 30, NOW)).toBe("in 30 s");
    expect(formatDue(NOW / 1000 + 600, NOW)).toBe("in 10 min");
    expect(formatDue(NOW / 1000 - 5, NOW)).toBe("now");
    expect(formatDue(ts(new Date(2026, 10, 12, 9, 0)), NOW)).toMatch(/^tomorrow /);
    expect(formatDue(ts(new Date(2026, 10, 13, 17, 0)), NOW)).toMatch(/^Fri /);
  });
});

describe("RemindersPanel", () => {
  it("lists reminders soonest first with repeat info", () => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
    try {
      render(<RemindersPanel reminders={items} />);
      const rows = screen.getAllByRole("listitem").map((li) => li.textContent);
      expect(rows[0]).toContain("Timer");
      expect(rows[0]).toContain("in 10 min");
      expect(rows[1]).toContain("call mom");
      expect(rows[2]).toContain("every weekday");
    } finally {
      vi.useRealTimers();
    }
  });

  it("adds a reminder and clears the form", async () => {
    const add = vi
      .spyOn(api, "addReminder")
      .mockResolvedValue({ ok: true, reminder: { id: 9, message: "Okay, I'll remind you to water plants at 6 PM." } });
    render(<RemindersPanel reminders={[]} />);
    fireEvent.change(screen.getByLabelText("What to remember"), { target: { value: "water plants" } });
    fireEvent.change(screen.getByLabelText("When"), { target: { value: "at 6pm" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(add).toHaveBeenCalledWith({ text: "water plants", when: "at 6pm" });
    expect(await screen.findByRole("status")).toHaveTextContent("water plants at 6 PM");
    expect(screen.getByLabelText("What to remember")).toHaveValue("");
  });

  it("shows the server's explanation when a time is not understood", async () => {
    vi.spyOn(api, "addReminder").mockRejectedValue(
      new ApiError(400, "400 couldn't find a time in 'someday'"),
    );
    const onError = vi.fn();
    render(<RemindersPanel reminders={[]} onError={onError} />);
    fireEvent.change(screen.getByLabelText("What to remember"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("When"), { target: { value: "someday" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("status")).toHaveTextContent("couldn't find a time in 'someday'");
    expect(onError).toHaveBeenCalled();
    expect(screen.getByLabelText("What to remember")).toHaveValue("x");
  });

  it("starts quick timers and cancels reminders", async () => {
    const add = vi.spyOn(api, "addReminder").mockResolvedValue({ ok: true, reminder: { id: 4, message: "Timer set for 5 minutes." } });
    const cancel = vi.spyOn(api, "cancelReminder").mockResolvedValue({ ok: true, message: "Cancelled the reminder to call mom." });
    render(<RemindersPanel reminders={items} />);
    fireEvent.click(screen.getByRole("button", { name: "⏱ 5 min" }));
    expect(add).toHaveBeenCalledWith({ timer: "5 minutes" });
    await screen.findByText("Timer set for 5 minutes.");
    fireEvent.click(screen.getByRole("button", { name: "Cancel call mom" }));
    expect(cancel).toHaveBeenCalledWith(2);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Cancelled"));
  });

  it("is read-only for viewer devices", () => {
    render(<RemindersPanel reminders={items} canEdit={false} />);
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Cancel/ })).toBeNull();
    expect(screen.getByText("call mom")).toBeInTheDocument();
  });
});
