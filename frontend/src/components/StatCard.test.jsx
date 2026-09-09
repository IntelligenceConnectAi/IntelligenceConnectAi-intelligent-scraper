import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StatCard from "./StatCard";

describe("StatCard", () => {
  it("renders the label and a formatted value", () => {
    render(<StatCard label="Total Leads" value={12345} />);
    expect(screen.getByText("Total Leads")).toBeInTheDocument();
    expect(screen.getByText("12,345")).toBeInTheDocument();
  });

  it("applies accent styling only when accent is true", () => {
    const { container } = render(<StatCard label="Accented" value={10} accent />);
    expect(container.querySelector(".kpi-value").className).toContain("accent-text");
  });

  it("does not apply accent styling by default", () => {
    const { container } = render(<StatCard label="Plain" value={10} />);
    expect(container.querySelector(".kpi-value").className).not.toContain("accent-text");
  });
});
