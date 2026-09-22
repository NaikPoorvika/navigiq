/**
 * Mood art. These are ILLUSTRATIONS (AI-generated in the original NavigIQ
 * design concept), not photographs of any particular place. They are only
 * used to set a mood — the hero, mood tiles, empty states — and every alt
 * text says so. A place is only ever shown with its own photograph (from
 * Wikimedia Commons, with attribution) or with its category artwork.
 *
 * Images that looked like specific Bengaluru landmarks were deliberately
 * left out of the product so nothing can be mistaken for a real place.
 */
import arcade from "@/assets/mood/arcade.jpg";
import brewery from "@/assets/mood/brewery.jpg";
import canopyPath from "@/assets/mood/canopy-path.jpg";
import coffeeBar from "@/assets/mood/coffee-bar.jpg";
import dinnerTable from "@/assets/mood/dinner-table.jpg";
import hillClouds from "@/assets/mood/hill-clouds.jpg";
import oldLane from "@/assets/mood/old-lane.jpg";
import quietCafe from "@/assets/mood/quiet-cafe.jpg";
import rainyStreet from "@/assets/mood/rainy-street.jpg";
import rainyWindow from "@/assets/mood/rainy-window.jpg";
import streetFood from "@/assets/mood/street-food.jpg";

export interface MoodArt {
  src: string;
  alt: string;
}

export const MOOD_ART = {
  canopyPath: { src: canopyPath, alt: "Illustration: morning light through a tree-lined park path" },
  hillClouds: { src: hillClouds, alt: "Illustration: a hilltop above a sea of clouds at dawn" },
  quietCafe: { src: quietCafe, alt: "Illustration: a quiet café corner with plants and daylight" },
  coffeeBar: { src: coffeeBar, alt: "Illustration: coffee being brewed at a café counter" },
  rainyWindow: { src: rainyWindow, alt: "Illustration: a cup of coffee by a rain-streaked café window" },
  rainyStreet: { src: rainyStreet, alt: "Illustration: a wet city street glowing with shop lights at dusk" },
  streetFood: { src: streetFood, alt: "Illustration: people sharing breakfast at a busy local eatery" },
  dinnerTable: { src: dinnerTable, alt: "Illustration: a warmly lit dinner table set with a banana-leaf platter" },
  brewery: { src: brewery, alt: "Illustration: copper brewing tanks in a dim taproom" },
  arcade: { src: arcade, alt: "Illustration: a neon-lit games arcade" },
  oldLane: { src: oldLane, alt: "Illustration: an old-city lane leading to a temple tower in golden light" },
} satisfies Record<string, MoodArt>;

export type MoodArtKey = keyof typeof MOOD_ART;

/** Hero art for the real time of day and the real forecast (never assumed). */
export function heroArt(timeOfDay: string | undefined, rainLikely: boolean): MoodArt {
  if (rainLikely) return timeOfDay === "night" || timeOfDay === "evening" ? MOOD_ART.rainyStreet : MOOD_ART.rainyWindow;
  switch (timeOfDay) {
    case "morning":
      return MOOD_ART.canopyPath;
    case "afternoon":
      return MOOD_ART.quietCafe;
    case "evening":
      return MOOD_ART.oldLane;
    case "night":
      return MOOD_ART.dinnerTable;
    default:
      return MOOD_ART.canopyPath;
  }
}
