import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Hoisted above imports by Vitest -- replaces the module before NotificationBell's
// own `import { api } from "../lib/api"` ever runs, so lib/supabase.js (which throws
// at import time without real env vars) is never evaluated at all.
vi.mock("../lib/api", () => ({
  api: {
    listNotifications: vi.fn(),
    markNotificationRead: vi.fn(),
    markAllNotificationsRead: vi.fn(),
  },
}));

import { api } from "../lib/api";
import NotificationBell from "./NotificationBell";

describe("NotificationBell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the unread count badge from the API on mount", async () => {
    api.listNotifications.mockResolvedValue({
      items: [{ id: "1", title: "Hi", body: "Body", is_read: false, created_at: new Date().toISOString(), link_section: null }],
      unread_count: 1,
    });
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
  });

  it("shows no badge when unread_count is 0", async () => {
    api.listNotifications.mockResolvedValue({ items: [], unread_count: 0 });
    render(<NotificationBell />);
    await waitFor(() => expect(api.listNotifications).toHaveBeenCalled());
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("marks a notification read and decrements the count on click", async () => {
    api.listNotifications.mockResolvedValue({
      items: [{ id: "1", title: "Hi", body: "Body", is_read: false, created_at: new Date().toISOString(), link_section: null }],
      unread_count: 1,
    });
    api.markNotificationRead.mockResolvedValue({});
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());

    fireEvent.click(screen.getByTitle("Notifications"));
    fireEvent.click(screen.getByText("Hi"));

    await waitFor(() => expect(api.markNotificationRead).toHaveBeenCalledWith("1"));
    await waitFor(() => expect(screen.queryByText("1")).not.toBeInTheDocument());
  });
});
