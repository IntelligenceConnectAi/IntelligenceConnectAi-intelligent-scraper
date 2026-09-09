import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RequestTabs from "./RequestTabs";

const tabs = [
  { id: "new", label: "New Request" },
  { id: "active", label: "Active Requests", count: 3 },
  { id: "completed", label: "Completed Requests", count: 0 },
];

describe("RequestTabs", () => {
  it("renders a count badge only for tabs whose count is not null", () => {
    render(<RequestTabs tabs={tabs} activeTab="new" onChange={() => {}} />);
    expect(screen.getByText("(3)")).toBeInTheDocument();
    expect(screen.getByText("(0)")).toBeInTheDocument();
    expect(screen.getByText("New Request").textContent).toBe("New Request");
  });

  it("applies active styling to the active tab only", () => {
    render(<RequestTabs tabs={tabs} activeTab="active" onChange={() => {}} />);
    expect(screen.getByText("Active Requests", { exact: false }).closest("button").className).toContain("btn-primary");
    expect(screen.getByText("New Request").closest("button").className).toContain("btn-ghost");
  });

  it("fires onChange with the clicked tab's id", () => {
    const onChange = vi.fn();
    render(<RequestTabs tabs={tabs} activeTab="new" onChange={onChange} />);
    fireEvent.click(screen.getByText("Completed Requests", { exact: false }));
    expect(onChange).toHaveBeenCalledWith("completed");
  });
});
