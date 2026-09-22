/**
 * Category presentation: label, icon and tone. The keys and names mirror the
 * backend taxonomy (GET /api/v1/pois/categories); this file only decides how
 * they look. An unknown key still renders (as "other").
 */
import {
  Baby, Beer, Binoculars, Brush, Camera, Castle, Church, Coffee, Crown, Droplets,
  FlaskConical, Flower2, Footprints, Gamepad2, Heart, IceCreamCone, Landmark, Leaf, MapPin,
  MapPinned, Moon, Mountain, MountainSnow, Palette, ScrollText, Shield, ShoppingBag, Soup, Sparkle,
  Sparkles, Store, Ticket, Tractor, TreePine, Trees, Users, UtensilsCrossed, WavesHorizontal,
  Building, type LucideIcon,
} from "lucide-react";

export type CategoryGroup =
  | "nature" | "culture" | "spiritual" | "food" | "shopping" | "fun" | "experience" | "explore"
  | "theme" | "other";

interface CategoryMeta {
  label: string;
  group: CategoryGroup;
  icon: LucideIcon;
}

export const CATEGORY_META: Record<string, CategoryMeta> = {
  park: { label: "Park", group: "nature", icon: Trees },
  garden: { label: "Garden", group: "nature", icon: Flower2 },
  lake: { label: "Lake", group: "nature", icon: WavesHorizontal },
  nature: { label: "Nature reserve", group: "nature", icon: Leaf },
  hill: { label: "Hill", group: "nature", icon: Mountain },
  viewpoint: { label: "Viewpoint", group: "nature", icon: Binoculars },
  forest: { label: "Forest", group: "nature", icon: TreePine },
  waterfall: { label: "Waterfall", group: "nature", icon: Droplets },
  reservoir: { label: "Reservoir", group: "nature", icon: WavesHorizontal },
  museum: { label: "Museum", group: "culture", icon: Landmark },
  gallery: { label: "Art gallery", group: "culture", icon: Palette },
  science: { label: "Science centre", group: "culture", icon: FlaskConical },
  history: { label: "Historic site", group: "culture", icon: ScrollText },
  heritage: { label: "Heritage site", group: "culture", icon: Castle },
  palace: { label: "Palace", group: "culture", icon: Crown },
  fort: { label: "Fort", group: "culture", icon: Shield },
  monument: { label: "Monument", group: "culture", icon: Landmark },
  architecture: { label: "Architecture", group: "culture", icon: Building },
  temple: { label: "Temple", group: "spiritual", icon: Sparkles },
  church: { label: "Church", group: "spiritual", icon: Church },
  mosque: { label: "Mosque", group: "spiritual", icon: Moon },
  religious_site: { label: "Religious site", group: "spiritual", icon: Sparkle },
  cafe: { label: "Cafe", group: "food", icon: Coffee },
  restaurant: { label: "Restaurant", group: "food", icon: UtensilsCrossed },
  street_food: { label: "Street food", group: "food", icon: Soup },
  dessert: { label: "Dessert", group: "food", icon: IceCreamCone },
  shopping: { label: "Shopping", group: "shopping", icon: ShoppingBag },
  market: { label: "Market", group: "shopping", icon: Store },
  mall: { label: "Mall", group: "shopping", icon: ShoppingBag },
  entertainment: { label: "Entertainment", group: "fun", icon: Ticket },
  gaming: { label: "Gaming", group: "fun", icon: Gamepad2 },
  activity: { label: "Activity", group: "fun", icon: Footprints },
  adventure: { label: "Adventure", group: "fun", icon: MountainSnow },
  nightlife: { label: "Nightlife", group: "fun", icon: Beer },
  farm: { label: "Farm", group: "experience", icon: Tractor },
  experience: { label: "Experience", group: "experience", icon: Sparkle },
  workshop: { label: "Workshop", group: "experience", icon: Brush },
  neighborhood: { label: "Neighbourhood", group: "explore", icon: MapPinned },
  walking_area: { label: "Walking area", group: "explore", icon: Footprints },
  photography: { label: "Photography", group: "theme", icon: Camera },
  romantic: { label: "Romantic", group: "theme", icon: Heart },
  family: { label: "Family", group: "theme", icon: Users },
  kids: { label: "Kids", group: "theme", icon: Baby },
  other: { label: "Place", group: "other", icon: MapPin },
};

export function categoryMeta(key: string | null | undefined): CategoryMeta {
  return (key && CATEGORY_META[key]) || { label: humanize(key ?? "place"), group: "other", icon: MapPin };
}

export function humanize(value: string): string {
  const s = value.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Tailwind classes for a category group's tone (soft background + ink). */
export const GROUP_TONE: Record<CategoryGroup, { bg: string; ink: string; ring: string }> = {
  nature: { bg: "bg-cat-nature", ink: "text-cat-nature-ink", ring: "ring-cat-nature-ink/15" },
  culture: { bg: "bg-cat-culture", ink: "text-cat-culture-ink", ring: "ring-cat-culture-ink/15" },
  spiritual: { bg: "bg-cat-spiritual", ink: "text-cat-spiritual-ink", ring: "ring-cat-spiritual-ink/15" },
  food: { bg: "bg-cat-food", ink: "text-cat-food-ink", ring: "ring-cat-food-ink/15" },
  shopping: { bg: "bg-cat-shopping", ink: "text-cat-shopping-ink", ring: "ring-cat-shopping-ink/15" },
  fun: { bg: "bg-cat-fun", ink: "text-cat-fun-ink", ring: "ring-cat-fun-ink/15" },
  experience: { bg: "bg-cat-experience", ink: "text-cat-experience-ink", ring: "ring-cat-experience-ink/15" },
  explore: { bg: "bg-cat-explore", ink: "text-cat-explore-ink", ring: "ring-cat-explore-ink/15" },
  theme: { bg: "bg-cat-explore", ink: "text-cat-explore-ink", ring: "ring-cat-explore-ink/15" },
  other: { bg: "bg-surface-strong", ink: "text-muted-foreground", ring: "ring-border" },
};

/** Explore filters: a short list of the categories people actually browse by. */
export const EXPLORE_CATEGORIES = [
  "park", "lake", "garden", "museum", "heritage", "temple", "cafe", "restaurant", "street_food",
  "market", "gallery", "viewpoint", "hill", "waterfall", "activity", "nightlife", "workshop",
] as const;

export const MOODS = [
  { key: "peaceful", label: "Peaceful" },
  { key: "romantic", label: "Romantic" },
  { key: "adventurous", label: "Adventurous" },
  { key: "foodie", label: "Foodie" },
  { key: "cultural", label: "Cultural" },
  { key: "nature", label: "Outdoorsy" },
  { key: "social", label: "Social" },
  { key: "creative", label: "Creative" },
  { key: "photography", label: "Photogenic" },
  { key: "budget", label: "Easy on the wallet" },
  { key: "offbeat", label: "Offbeat" },
  { key: "quiet", label: "Quiet" },
] as const;

