import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PoiFeatureCard, PoiRowCard } from "@/components/poi/PoiCard";
import { cubbon, lalbagh } from "@/test/fixtures";
import { renderApp } from "@/test/utils";

describe("place cards", () => {
  it("shows what NavigIQ knows and says why it was suggested", async () => {
    renderApp(<PoiFeatureCard poi={lalbagh} />);
    expect(await screen.findByRole("link", { name: "Lalbagh Botanical Garden" })).toBeInTheDocument();
    expect(screen.getByText("Shanti Nagar")).toBeInTheDocument();
    expect(screen.getByText(/Matches garden · Photogenic/)).toBeInTheDocument();
    expect(screen.getByText("~₹30")).toBeInTheDocument();
    expect(screen.getByText(/\/person est\./)).toBeInTheDocument();
    expect(screen.getByText("2 h")).toBeInTheDocument();
  });

  it("never shows a rating or review count", async () => {
    const { container } = renderApp(<PoiFeatureCard poi={lalbagh} />);
    await screen.findByRole("link", { name: "Lalbagh Botanical Garden" });
    expect(container.textContent).not.toMatch(/rating|stars?\b|reviews?/i);
  });

  it("labels free places as free, in the badge and in the facts", async () => {
    renderApp(<PoiFeatureCard poi={cubbon} />);
    await screen.findByRole("link", { name: "Cubbon Park" });
    expect(screen.getAllByText("Free")).toHaveLength(2);
    expect(screen.queryByText(/\/person est\./)).toBeNull();
  });

  it("uses category artwork when there is no photograph of the place", async () => {
    const { container } = renderApp(<PoiRowCard poi={lalbagh} />);
    await screen.findByRole("link", { name: "Lalbagh Botanical Garden" });
    expect(container.querySelector("img")).toBeNull();
  });

  it("asks anonymous visitors to sign in before saving", async () => {
    const user = userEvent.setup();
    renderApp(<PoiFeatureCard poi={lalbagh} />);
    await user.click(await screen.findByRole("button", { name: /^Save Lalbagh/ }));
    await waitFor(() => expect(screen.getByText("Sign in to save places")).toBeInTheDocument());
  });
});
