import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DonutChart from "./DonutChart";

describe("DonutChart", () => {
  it("shows the empty message and no NaN% when every segment value is 0", () => {
    render(<DonutChart segments={[
      { label: "A", value: 0, color: "red" },
      { label: "B", value: 0, color: "blue" },
    ]} />);
    expect(screen.getByText("No data yet")).toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });

  it("computes correct percentages for a normal 2-segment case", () => {
    render(<DonutChart segments={[
      { label: "With Website", value: 75, color: "green" },
      { label: "Without Website", value: 25, color: "gray" },
    ]} />);
    expect(screen.getByText(/75%/)).toBeInTheDocument();
    expect(screen.getByText(/25%/)).toBeInTheDocument();
  });

  it("respects a custom empty label", () => {
    render(<DonutChart segments={[]} emptyLabel="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
