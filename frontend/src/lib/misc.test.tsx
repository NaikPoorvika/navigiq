import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AskBar } from "@/components/ask/AskBar";
import { MOOD_ART, heroArt } from "@/lib/media";
import { clearPrompts, recentPrompts, rememberPrompt } from "@/lib/recent";
import { getSessionId } from "@/lib/session";
import { categoryMeta } from "@/lib/categories";

describe("anonymous session", () => {
  it("is a stable id in the format the API accepts", () => {
    const a = getSessionId();
    expect(a).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
    expect(getSessionId()).toBe(a);
  });
});

describe("recent prompts", () => {
  beforeEach(() => clearPrompts());

  it("keeps the latest five, most recent first, without duplicates", () => {
    ["one a", "two b", "three c", "four d", "five e", "six f"].forEach(rememberPrompt);
    rememberPrompt("THREE C");
    expect(recentPrompts()).toEqual(["THREE C", "six f", "five e", "four d", "two b"]);
  });

  it("ignores trivial input", () => {
    rememberPrompt("  a ");
    expect(recentPrompts()).toEqual([]);
  });
});

describe("hero art", () => {
  it("follows the real forecast first, then the time of day", () => {
    expect(heroArt("morning", true)).toBe(MOOD_ART.rainyWindow);
    expect(heroArt("night", true)).toBe(MOOD_ART.rainyStreet);
    expect(heroArt("morning", false)).toBe(MOOD_ART.canopyPath);
    expect(heroArt(undefined, false)).toBe(MOOD_ART.canopyPath);
  });

  it("describes every image as an illustration", () => {
    for (const art of Object.values(MOOD_ART)) expect(art.alt).toMatch(/^Illustration: /);
  });
});

describe("categories", () => {
  it("renders unknown categories instead of failing", () => {
    expect(categoryMeta("hot_air_balloon").label).toBe("Hot air balloon");
    expect(categoryMeta(null).group).toBe("other");
  });
});

describe("ask bar", () => {
  it("sends trimmed text and clears", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<AskBar onSubmit={onSubmit} />);
    const input = screen.getByLabelText("Ask NavigIQ");
    await user.type(input, "  quiet cafes  {enter}");
    expect(onSubmit).toHaveBeenCalledWith("quiet cafes");
    expect(input).toHaveValue("");
  });

  it("won't send empty text or while busy", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<AskBar onSubmit={onSubmit} />);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    rerender(<AskBar onSubmit={onSubmit} busy />);
    await user.type(screen.getByLabelText("Ask NavigIQ"), "hello{enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
