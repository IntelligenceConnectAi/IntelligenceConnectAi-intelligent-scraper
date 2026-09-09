import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BarListChart from "./BarListChart";

describe("BarListChart", () => {
  it("renders the empty label when items is empty", () => {
    render(<BarListChart items={[]} />);
    expect(screen.getByText("No data yet")).toBeInTheDocument();
  });

  it("respects a custom empty label", () => {
    render(<BarListChart items={[]} emptyLabel="Nothing yet" />);
    expect(screen.getByText("Nothing yet")).toBeInTheDocument();
  });

  it("renders a chart without throwing when every value is 0 (Math.max(1, ...) guard)", () => {
    const { container } = render(<BarListChart items={[{ label: "A", value: 0 }, { label: "B", value: 0 }]} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("renders a chart for non-zero values", () => {
    const { container } = render(<BarListChart items={[{ label: "A", value: 50 }, { label: "B", value: 100 }]} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});
