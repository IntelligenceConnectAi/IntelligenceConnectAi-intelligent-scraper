import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({
  api: {
    getOrganization: vi.fn(),
    listMembers: vi.fn(),
    listInvitations: vi.fn(),
    createInvitation: vi.fn(),
  },
}));

import { api } from "../lib/api";
import TeamSection from "./TeamSection";

const baseOrg = { id: "org1", name: "Test Org", seats_used: 2, max_team_seats: 10 };

describe("TeamSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listMembers.mockResolvedValue([]);
    api.listInvitations.mockResolvedValue([]);
  });

  it("shows the invite form for an account_owner", async () => {
    api.getOrganization.mockResolvedValue({ ...baseOrg, my_role: "account_owner" });
    render(<TeamSection />);
    await waitFor(() => expect(screen.getByText("Invite a Team Member")).toBeInTheDocument());
  });

  it("hides the invite form for a client_member (server-returned role gates the UI)", async () => {
    api.getOrganization.mockResolvedValue({ ...baseOrg, my_role: "client_member" });
    render(<TeamSection />);
    await waitFor(() => expect(screen.getByText("2 / 10")).toBeInTheDocument());
    expect(screen.queryByText("Invite a Team Member")).not.toBeInTheDocument();
  });

  it("shows the one-time invite link after a successful invite", async () => {
    api.getOrganization.mockResolvedValue({ ...baseOrg, my_role: "account_owner" });
    api.createInvitation.mockResolvedValue({ invite_link: "http://localhost/join?token=abc123" });
    render(<TeamSection />);
    await waitFor(() => expect(screen.getByText("Invite a Team Member")).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("teammate@example.com"), {
      target: { value: "new@example.com" },
    });
    fireEvent.click(screen.getByText("Send Invite"));

    await waitFor(() => expect(api.createInvitation).toHaveBeenCalledWith("new@example.com", "client_member"));
    await waitFor(() => expect(screen.getByDisplayValue("http://localhost/join?token=abc123")).toBeInTheDocument());
  });
});
