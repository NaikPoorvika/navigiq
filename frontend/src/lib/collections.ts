/** Presentation for backend collections (data/config/collections.yaml). */
import type { CategoryGroup } from "@/lib/categories";
import { MOOD_ART, type MoodArt } from "@/lib/media";

interface CollectionLook {
  art?: MoodArt;
  group: CategoryGroup;
}

const LOOK: Record<string, CollectionLook> = {
  rainy_day: { art: MOOD_ART.rainyWindow, group: "culture" },
  cafes: { art: MOOD_ART.coffeeBar, group: "food" },
  food: { art: MOOD_ART.streetFood, group: "food" },
  romantic: { art: MOOD_ART.dinnerTable, group: "food" },
  heritage: { art: MOOD_ART.oldLane, group: "culture" },
  nature_escapes: { art: MOOD_ART.canopyPath, group: "nature" },
  weekend_escapes: { art: MOOD_ART.hillClouds, group: "nature" },
  outside_bengaluru: { art: MOOD_ART.hillClouds, group: "nature" },
  quiet: { art: MOOD_ART.quietCafe, group: "explore" },
  something_different: { art: MOOD_ART.arcade, group: "fun" },
  outdoor: { group: "nature" },
  scenic: { group: "nature" },
  spiritual: { group: "spiritual" },
  creative: { group: "experience" },
  photography: { group: "explore" },
  family_day: { group: "fun" },
  with_parents: { group: "culture" },
  student_budget: { group: "shopping" },
  under_500: { group: "shopping" },
  hidden_gems: { group: "experience" },
  top_picks: { group: "culture" },
  for_you: { group: "explore" },
};

export function collectionLook(id: string): CollectionLook {
  return LOOK[id] ?? { group: "explore" };
}

/** A representative category for a group, for collections without art. */
export const GROUP_CATEGORY: Record<string, string> = {
  nature: "park", food: "cafe", culture: "museum", spiritual: "temple", fun: "entertainment",
  shopping: "market", experience: "workshop", explore: "neighborhood", theme: "photography",
  other: "other",
};
